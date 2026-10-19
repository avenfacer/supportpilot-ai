from pydantic import Field

from app.tools.base import OrderId, ToolArgs, ToolDefinition
from app.tools.names import ToolName


class LookupOrderArgs(ToolArgs):
    order_id: OrderId = Field(description="Order ID written by the customer, e.g. ORD-1234.")


LOOKUP_ORDER = ToolDefinition(
    ToolName.LOOKUP_ORDER,
    "Look up the status, estimated delivery, and tracking number of one of the signed-in "
    "customer's orders. Ownership is verified by the backend.",
    LookupOrderArgs,
)
