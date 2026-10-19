from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_ticket_service
from app.core.errors import NotFoundError
from app.core.security import CustomerContext, require_customer
from app.schemas.ticket import TicketResponse
from app.services.ticket_service import TicketService

router = APIRouter(tags=["tickets"])


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: Annotated[str, Path(pattern=r"^TKT-[0-9A-F]{8}$")],
    customer: Annotated[CustomerContext, Depends(require_customer)],
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketResponse:
    """Read one of the signed-in customer's tickets. Other customers' tickets return 404."""
    ticket = service.get_for_customer(ticket_id, customer.customer_id)
    if ticket is None:
        raise NotFoundError("Ticket not found.")
    return TicketResponse.from_record(ticket)
