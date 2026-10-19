from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_order_service
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.core.security import CustomerContext, require_customer
from app.schemas.order import OrderSummary
from app.services.order_service import OrderService

router = APIRouter(tags=["orders"])


@router.get("/orders/{order_id}", response_model=OrderSummary)
def get_order(
    order_id: Annotated[str, Path(pattern=r"^ORD-\d{4,8}$")],
    customer: Annotated[CustomerContext, Depends(require_customer)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderSummary:
    """Demo order lookup. Returns 404 for both unknown orders and other customers' orders."""
    result = service.lookup(order_id, customer.customer_id)
    if result.is_failure:
        raise ServiceUnavailableError(
            "order_service_unavailable", "Order lookup is temporarily unavailable."
        )
    if result.order is None:
        raise NotFoundError("Order not found.")
    return result.order
