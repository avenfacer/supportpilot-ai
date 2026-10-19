import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.llm_provider import ToolCallProposal, ToolSpec
from app.tools.base import ToolArgs, ToolDefinition
from app.tools.conversation import ASK_CLARIFICATION, DECLINE_UNSUPPORTED, SEARCH_KNOWLEDGE
from app.tools.names import ToolName
from app.tools.order_lookup import LOOKUP_ORDER
from app.tools.support_request import CREATE_SUPPORT_REQUEST, REQUEST_HUMAN_HANDOFF

logger = logging.getLogger(__name__)

MAX_ARGUMENT_CHARS = 4000


class ToolValidationError(Exception):
    def __init__(self, code: str, tool_name: str):
        super().__init__(f"{code}: {tool_name}")
        self.code = code
        self.tool_name = tool_name


@dataclass(frozen=True)
class ValidatedToolCall:
    name: ToolName
    args: ToolArgs


class ToolRegistry:
    """Fixed allowlist of tools. Model proposals are validated here before anything executes."""

    def __init__(self, tools: list[ToolDefinition]):
        self._tools = {t.name.value: t for t in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def validate(self, proposal: ToolCallProposal) -> ValidatedToolCall:
        tool = self._tools.get(proposal.name)
        if tool is None:
            logger.warning("tool_rejected_unknown", extra={"tool_name": proposal.name[:64]})
            raise ToolValidationError("unknown_tool", proposal.name[:64])
        if len(proposal.arguments) > MAX_ARGUMENT_CHARS:
            raise ToolValidationError("arguments_too_large", tool.name)
        try:
            raw = json.loads(proposal.arguments or "{}")
            if not isinstance(raw, dict):
                raise ToolValidationError("arguments_not_object", tool.name)
            args = tool.args_model.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            fields = (
                [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
                if isinstance(exc, ValidationError)
                else []
            )
            logger.warning(
                "tool_rejected_invalid_arguments",
                extra={"tool_name": tool.name.value, "invalid_fields": fields},
            )
            raise ToolValidationError("invalid_arguments", tool.name) from exc
        return ValidatedToolCall(name=tool.name, args=args)


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            SEARCH_KNOWLEDGE,
            LOOKUP_ORDER,
            CREATE_SUPPORT_REQUEST,
            REQUEST_HUMAN_HANDOFF,
            ASK_CLARIFICATION,
            DECLINE_UNSUPPORTED,
        ]
    )
