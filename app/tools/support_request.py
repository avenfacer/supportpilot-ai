from typing import Literal

from pydantic import Field

from app.tools.base import OrderId, ToolArgs, ToolDefinition
from app.tools.names import ToolName


class CreateSupportRequestArgs(ToolArgs):
    request_type: Literal["return", "cancellation"]
    order_id: OrderId | None = Field(
        default=None, description="Order ID written by the customer, if any."
    )
    reason: str = Field(min_length=1, max_length=500, description="The customer's stated reason.")


class RequestHumanHandoffArgs(ToolArgs):
    reason: str = Field(min_length=1, max_length=300, description="Why a human is needed.")


CREATE_SUPPORT_REQUEST = ToolDefinition(
    ToolName.CREATE_SUPPORT_REQUEST,
    "Prepare a return or cancellation request for human review. This never approves, cancels, "
    "or refunds anything; it creates a ticket with status pending_human_review.",
    CreateSupportRequestArgs,
)
REQUEST_HUMAN_HANDOFF = ToolDefinition(
    ToolName.REQUEST_HUMAN_HANDOFF,
    "Hand the conversation over to a human support agent.",
    RequestHumanHandoffArgs,
)
