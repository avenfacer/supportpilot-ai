from datetime import date, datetime

from pydantic import BaseModel


class OrderItem(BaseModel):
    sku: str
    name: str
    quantity: int


class OrderRecord(BaseModel):
    """Full order as stored by the (mock) store backend. Never returned to clients directly."""

    order_id: str
    customer_id: str
    status: str
    created_at: datetime
    estimated_delivery: date | None
    tracking_number: str | None
    items: list[OrderItem]


class OrderItemSummary(BaseModel):
    name: str
    quantity: int


class OrderSummary(BaseModel):
    """Customer-facing order view: only the fields needed to answer status questions."""

    order_id: str
    status: str
    created_at: datetime
    estimated_delivery: date | None
    tracking_number: str | None
    items: list[OrderItemSummary]

    @classmethod
    def from_record(cls, record: OrderRecord) -> "OrderSummary":
        return cls(
            order_id=record.order_id,
            status=record.status,
            created_at=record.created_at,
            estimated_delivery=record.estimated_delivery,
            tracking_number=record.tracking_number,
            items=[OrderItemSummary(name=i.name, quantity=i.quantity) for i in record.items],
        )
