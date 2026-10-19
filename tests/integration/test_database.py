import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import check_database, check_pgvector
from app.demo_data import load_demo_store, seed_database
from app.repositories.sql import SqlOrderRepository

pytestmark = pytest.mark.integration


def test_migrations_enable_pgvector(migrated_engine: Engine) -> None:
    assert check_database(migrated_engine)
    assert check_pgvector(migrated_engine)


def test_seed_is_idempotent_and_orders_are_readable(db_session: Session) -> None:
    seed_database(db_session, load_demo_store())  # second run must not duplicate or fail

    order = SqlOrderRepository(db_session).get("ORD-1002")
    assert order is not None
    assert order.customer_id == "CUST-001"
    assert order.items[0].name == "Trail Daypack 20L"
    assert SqlOrderRepository(db_session).get("ORD-9999") is None
