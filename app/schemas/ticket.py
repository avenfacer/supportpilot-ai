from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class RequestType(StrEnum):
    RETURN = "return"
    CANCELLATION = "cancellation"
    OTHER = "other"


class TicketStatus(StrEnum):
    PENDING_HUMAN_REVIEW = "pending_human_review"
    # The states below are reserved for human agents in a back-office tool. No code path in this
    # application (and nothing the model outputs) can move a ticket into them.
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"


class TicketRecord(BaseModel):
    id: str
    customer_id: str
    order_id: str | None
    request_type: RequestType
    reason: str
    status: TicketStatus
    summary: str
    created_at: datetime
    updated_at: datetime


class TicketResponse(BaseModel):
    ticket_id: str
    request_type: RequestType
    order_id: str | None
    status: TicketStatus
    summary: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: TicketRecord) -> "TicketResponse":
        return cls(
            ticket_id=record.id,
            request_type=record.request_type,
            order_id=record.order_id,
            status=record.status,
            summary=record.summary,
            created_at=record.created_at,
        )
