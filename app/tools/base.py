from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

from app.ai.llm_provider import ToolSpec
from app.tools.names import ToolName


def _normalize_order_id(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


OrderId = Annotated[
    str, BeforeValidator(_normalize_order_id), StringConstraints(pattern=r"^ORD-\d{4,8}$")
]


class ToolArgs(BaseModel):
    """Base for tool arguments. Unknown fields (e.g. a model-supplied customer_id) are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


@dataclass(frozen=True)
class ToolDefinition:
    name: ToolName
    description: str
    args_model: type[ToolArgs]

    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name.value, description=self.description, parameters=schema)
