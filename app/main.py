import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.factory import build_embedding_provider, build_llm_provider
from app.ai.llm_provider import LLMProvider
from app.api.health import router as health_router
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, request_id_var
from app.db.session import build_engine, build_session_factory

logger = logging.getLogger("app.request")


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Grounded customer-support assistant for the fictional Northstar Shop. "
            "All customer and order data is synthetic. Identity uses a DEMO-ONLY header."
        ),
    )
    app.state.settings = settings
    # create_engine does not connect; connections are opened lazily on first use.
    app.state.engine = build_engine(settings.database_url)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.llm = llm or build_llm_provider(settings)
    app.state.embedder = embedder or build_embedding_provider(settings)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
