import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.db.session import build_engine, build_session_factory
from app.demo_data import load_demo_store, seed_database

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL is not set. Run `docker compose up -d db` and set "
            "TEST_DATABASE_URL to run the integration tests (see README)."
        )
    return url


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = build_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE support_tickets, orders, customers, knowledge_chunks, "
                "knowledge_documents CASCADE"
            )
        )
    factory = build_session_factory(migrated_engine)
    with factory() as session:
        seed_database(session, load_demo_store())
        yield session
