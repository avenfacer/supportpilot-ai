"""Seed the database with synthetic Northstar Shop customers and orders (idempotent).

Usage: uv run python scripts/seed_demo_data.py
"""

import sys

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.demo_data import load_demo_store, seed_database


def main() -> int:
    engine = build_engine(get_settings().database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        customers, orders = seed_database(session, load_demo_store())
    engine.dispose()
    print(f"Seeded {customers} synthetic customers and {orders} synthetic orders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
