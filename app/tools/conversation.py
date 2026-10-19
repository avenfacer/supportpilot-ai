from pydantic import Field

from app.tools.base import ToolArgs, ToolDefinition
from app.tools.names import ToolName


class SearchKnowledgeArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500, description="The policy/FAQ question.")


class AskClarificationArgs(ToolArgs):
    question: str = Field(min_length=1, max_length=300, description="One short question.")


class DeclineUnsupportedArgs(ToolArgs):
    reason: str = Field(
        min_length=1, max_length=300, description="Why the request is out of scope."
    )


SEARCH_KNOWLEDGE = ToolDefinition(
    ToolName.SEARCH_KNOWLEDGE,
    "Search Northstar Shop's help articles (shipping, returns, cancellations, refunds, warranty, "
    "payments, contact) to answer a policy or FAQ question.",
    SearchKnowledgeArgs,
)
ASK_CLARIFICATION = ToolDefinition(
    ToolName.ASK_CLARIFICATION,
    "Ask the customer one short clarifying question when required details are missing.",
    AskClarificationArgs,
)
DECLINE_UNSUPPORTED = ToolDefinition(
    ToolName.DECLINE_UNSUPPORTED,
    "Decline a request that is unrelated to Northstar Shop customer support.",
    DeclineUnsupportedArgs,
)
