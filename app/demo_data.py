"""Loader for the synthetic Northstar Shop demo data (customers and orders)."""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models import Customer, Order
from app.schemas.order import OrderRecord

DEMO_STORE_PATH = PROJECT_ROOT / "data" / "demo" / "store.json"


class DemoCustomer(BaseModel):
    id: str
    display_name: str


@dataclass(frozen=True)
class DemoStore:
    customers: list[DemoCustomer]
    orders: list[OrderRecord]


def load_demo_store(path: Path = DEMO_STORE_PATH) -> DemoStore:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DemoStore(
        customers=[DemoCustomer.model_validate(c) for c in raw["customers"]],
        orders=[OrderRecord.model_validate(o) for o in raw["orders"]],
    )


def seed_database(session: Session, store: DemoStore) -> tuple[int, int]:
    """Idempotently upsert demo customers and orders. Returns (customers, orders) counts."""
    for customer in store.customers:
        session.merge(Customer(id=customer.id, display_name=customer.display_name))
    session.flush()
    for order in store.orders:
        session.merge(
            Order(
                order_id=order.order_id,
                customer_id=order.customer_id,
                status=order.status,
                created_at=order.created_at,
                estimated_delivery=order.estimated_delivery,
                tracking_number=order.tracking_number,
                items=[item.model_dump() for item in order.items],
            )
        )
    session.commit()
    return len(store.customers), len(store.orders)
