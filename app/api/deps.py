from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.llm_provider import LLMProvider
from app.api.state import get_settings_dep
from app.core.config import Settings
from app.db.session import check_database, check_pgvector
from app.repositories.base import KnowledgeRepository, OrderRepository, TicketRepository
from app.repositories.sql import SqlKnowledgeRepository, SqlOrderRepository, SqlTicketRepository
from app.services.chat_service import ChatService, build_chat_service, build_order_service
from app.services.ingestion_service import IngestionService
from app.services.order_service import OrderService
from app.services.ticket_service import TicketService

ReadinessCheck = Callable[[], bool]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@dataclass(frozen=True)
class Repositories:
    knowledge: KnowledgeRepository
    orders: OrderRepository
    tickets: TicketRepository


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_db_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session


def get_repositories(session: Annotated[Session, Depends(get_db_session)]) -> Repositories:
    return Repositories(
        knowledge=SqlKnowledgeRepository(session),
        orders=SqlOrderRepository(session),
        tickets=SqlTicketRepository(session),
    )


RepositoriesDep = Annotated[Repositories, Depends(get_repositories)]


def get_llm(request: Request) -> LLMProvider:
    llm: LLMProvider = request.app.state.llm
    return llm


def get_embedder(request: Request) -> EmbeddingProvider:
    embedder: EmbeddingProvider = request.app.state.embedder
    return embedder


def get_order_service(repos: RepositoriesDep, settings: SettingsDep) -> OrderService:
    return build_order_service(repos.orders, settings)


def get_ticket_service(repos: RepositoriesDep) -> TicketService:
    return TicketService(repos.tickets)


def get_chat_service(
    repos: RepositoriesDep,
    settings: SettingsDep,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    embedder: Annotated[EmbeddingProvider, Depends(get_embedder)],
    order_service: Annotated[OrderService, Depends(get_order_service)],
) -> ChatService:
    return build_chat_service(
        settings=settings,
        llm=llm,
        embedder=embedder,
        knowledge=repos.knowledge,
        orders=repos.orders,
        tickets=repos.tickets,
        order_service=order_service,
    )


def get_ingestion_service(
    repos: RepositoriesDep,
    settings: SettingsDep,
    embedder: Annotated[EmbeddingProvider, Depends(get_embedder)],
) -> IngestionService:
    return IngestionService(
        repos.knowledge,
        embedder,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


def get_readiness_checks(request: Request) -> dict[str, ReadinessCheck]:
    engine = get_engine(request)
    return {
        "database": lambda: check_database(engine),
        "pgvector": lambda: check_pgvector(engine),
    }
