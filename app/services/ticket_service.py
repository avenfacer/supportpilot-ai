import logging
import secrets
from collections.abc import Callable
from datetime import datetime

from app.core.logging import redact
from app.models.base import utcnow
from app.repositories.base import TicketRepository
from app.schemas.ticket import RequestType, TicketRecord, TicketStatus

logger = logging.getLogger(__name__)

MAX_REASON_CHARS = 500
MAX_SUMMARY_CHARS = 1000


class TicketCreationError(Exception):
    pass


def new_ticket_id() -> str:
    return f"TKT-{secrets.token_hex(4).upper()}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(redact(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class TicketService:
    """Creates support tickets. Tickets always start in `pending_human_review`; there is
    deliberately no method to approve or change a ticket's status."""

    def __init__(
        self,
        repository: TicketRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        id_factory: Callable[[], str] = new_ticket_id,
    ):
        self._repo = repository
        self._clock = clock
        self._id_factory = id_factory

    def create_pending(
        self,
        *,
        customer_id: str,
        request_type: RequestType,
        order_id: str | None,
        reason: str,
        summary: str,
    ) -> TicketRecord:
        now = self._clock()
        ticket = TicketRecord(
            id=self._id_factory(),
            customer_id=customer_id,
            order_id=order_id,
            request_type=request_type,
            reason=_clip(reason, MAX_REASON_CHARS),
            status=TicketStatus.PENDING_HUMAN_REVIEW,
            summary=_clip(summary, MAX_SUMMARY_CHARS),
            created_at=now,
            updated_at=now,
        )
        try:
            created = self._repo.create(ticket)
        except Exception as exc:
            logger.error("ticket_creation_failed", extra={"error_type": type(exc).__name__})
            raise TicketCreationError("could not persist ticket") from exc
        logger.info(
            "ticket_created",
            extra={
                "ticket_id": created.id,
                "request_type": created.request_type.value,
                "customer_id": customer_id,
            },
        )
        return created

    def get_for_customer(self, ticket_id: str, customer_id: str) -> TicketRecord | None:
        ticket = self._repo.get(ticket_id)
        if ticket is None or ticket.customer_id != customer_id:
            return None
        return ticket
