import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import ProviderError
from app.ai.fake_embedding import FakeEmbeddingProvider
from app.ai.fake_llm import FakeLLMProvider
from app.ai.llm_provider import (
    AnswerResult,
    ContextPassage,
    LLMProvider,
    PlanResult,
    ToolCallProposal,
    ToolSpec,
)
from app.api.deps import Repositories, get_repositories
from app.core.config import Settings
from app.demo_data import load_demo_store
from app.main import create_app
from app.models import EMBEDDING_DIMENSIONS
from app.repositories.memory import (
    InMemoryKnowledgeRepository,
    InMemoryOrderRepository,
    InMemoryTicketRepository,
)
from app.services.chat_service import ChatService, build_chat_service
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_settings(**overrides: Any) -> Settings:
    return Settings(app_env="test", _env_file=None, **overrides)  # type: ignore[call-arg]


class ScriptedLLM(LLMProvider):
    """Test double that returns pre-programmed tool calls / answers, or raises."""

    name = "scripted"
    model = "scripted"

    def __init__(
        self,
        *,
        tool: str | None = None,
        arguments: dict[str, Any] | str | None = None,
        answer: dict[str, Any] | str | None = None,
        plan_error: ProviderError | None = None,
        answer_error: ProviderError | None = None,
    ):
        self.tool = tool
        self.arguments = arguments
        self.answer = answer
        self.plan_error = plan_error
        self.answer_error = answer_error
        self.answer_prompts: list[str] = []

    def plan(self, *, system_prompt: str, user_message: str, tools: list[ToolSpec]) -> PlanResult:
        if self.plan_error:
            raise self.plan_error
        if self.tool is None:
            return PlanResult(tool_call=None)
        args = self.arguments if isinstance(self.arguments, str) else json.dumps(self.arguments)
        return PlanResult(tool_call=ToolCallProposal(name=self.tool, arguments=args or "{}"))

    def generate_answer(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        question: str,
        passages: list[ContextPassage],
    ) -> AnswerResult:
        self.answer_prompts.append(user_prompt)
        if self.answer_error:
            raise self.answer_error
        raw = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return AnswerResult(raw_text=raw)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)


@pytest.fixture
def knowledge_repo(
    settings: Settings, embedder: FakeEmbeddingProvider
) -> InMemoryKnowledgeRepository:
    repo = InMemoryKnowledgeRepository()
    report = IngestionService(
        repo, embedder, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    ).ingest_directory(settings.knowledge_base_dir)
    assert report.ok, report.errors
    return repo


@pytest.fixture
def order_repo() -> InMemoryOrderRepository:
    return InMemoryOrderRepository(load_demo_store().orders)


@pytest.fixture
def ticket_repo() -> InMemoryTicketRepository:
    return InMemoryTicketRepository()


@pytest.fixture
def retrieval(
    settings: Settings,
    knowledge_repo: InMemoryKnowledgeRepository,
    embedder: FakeEmbeddingProvider,
) -> RetrievalService:
    return RetrievalService(
        knowledge_repo,
        embedder,
        top_k=settings.retrieval_top_k,
        min_score=settings.effective_min_score,
    )


ChatServiceFactory = Callable[..., ChatService]
ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_chat_service(
    knowledge_repo: InMemoryKnowledgeRepository,
    order_repo: InMemoryOrderRepository,
    ticket_repo: InMemoryTicketRepository,
    embedder: FakeEmbeddingProvider,
) -> ChatServiceFactory:
    def factory(llm: LLMProvider | None = None, **setting_overrides: Any) -> ChatService:
        return build_chat_service(
            settings=make_settings(**setting_overrides),
            llm=llm or FakeLLMProvider(),
            embedder=embedder,
            knowledge=knowledge_repo,
            orders=order_repo,
            tickets=ticket_repo,
        )

    return factory


@pytest.fixture
def make_client(
    knowledge_repo: InMemoryKnowledgeRepository,
    order_repo: InMemoryOrderRepository,
    ticket_repo: InMemoryTicketRepository,
    embedder: FakeEmbeddingProvider,
) -> ClientFactory:
    def factory(llm: LLMProvider | None = None, **setting_overrides: Any) -> TestClient:
        app = create_app(
            make_settings(**setting_overrides), llm=llm or FakeLLMProvider(), embedder=embedder
        )
        app.dependency_overrides[get_repositories] = lambda: Repositories(
            knowledge=knowledge_repo, orders=order_repo, tickets=ticket_repo
        )
        return TestClient(app, raise_server_exceptions=False)

    return factory
