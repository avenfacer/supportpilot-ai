import pytest

from app.ai.llm_provider import ToolCallProposal
from app.tools.names import ToolName
from app.tools.order_lookup import LookupOrderArgs
from app.tools.registry import ToolValidationError, default_registry

registry = default_registry()


def test_registry_exposes_exactly_the_allowlisted_tools() -> None:
    assert set(registry.names) == {t.value for t in ToolName}
    for spec in registry.specs():
        assert spec.parameters["type"] == "object"
        assert spec.parameters.get("additionalProperties") is False


def test_valid_order_lookup_is_normalized() -> None:
    call = registry.validate(ToolCallProposal("lookup_order", '{"order_id": " ord-1002 "}'))
    assert call.name is ToolName.LOOKUP_ORDER
    assert isinstance(call.args, LookupOrderArgs)
    assert call.args.order_id == "ORD-1002"


@pytest.mark.parametrize(
    ("name", "arguments", "code"),
    [
        ("run_sql", '{"query": "DROP TABLE orders"}', "unknown_tool"),
        ("execute_shell", "{}", "unknown_tool"),
        ("lookup_order", '{"order_id": "1002; DROP"}', "invalid_arguments"),
        ("lookup_order", "{}", "invalid_arguments"),
        ("lookup_order", "not json", "invalid_arguments"),
        ("lookup_order", '["ORD-1002"]', "arguments_not_object"),
        (
            "lookup_order",
            '{"order_id": "ORD-1002", "customer_id": "CUST-002"}',
            "invalid_arguments",
        ),
        (
            "create_support_request",
            '{"request_type": "refund", "reason": "x"}',
            "invalid_arguments",
        ),
        ("search_knowledge", '{"query": "' + "a" * 5000 + '"}', "arguments_too_large"),
    ],
)
def test_invalid_proposals_are_rejected(name: str, arguments: str, code: str) -> None:
    with pytest.raises(ToolValidationError) as excinfo:
        registry.validate(ToolCallProposal(name, arguments))
    assert excinfo.value.code == code
