from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from app.ai.errors import ProviderError, ProviderResponseError, ProviderTimeoutError
from app.ai.fake_embedding import FakeEmbeddingProvider
from app.ai.llm_provider import ToolSpec
from app.ai.openai_provider import OpenAIEmbeddingProvider, OpenAILLMProvider

_REQUEST = httpx2.Request("POST", "https://api.openai.invalid/v1/chat/completions")
TOOLS = [ToolSpec(name="search_knowledge", description="d", parameters={"type": "object"})]


class FakeCompletions:
    def __init__(self, outcome: Any):
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome: Any) -> Any:
    completions = FakeCompletions(outcome)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions), embeddings=FakeCompletions(outcome)
    )


def _llm(outcome: Any) -> OpenAILLMProvider:
    return OpenAILLMProvider(
        api_key="test", model="gpt-test", timeout_seconds=1, client=_client(outcome)
    )


def _response(message: Any) -> Any:
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_fake_embeddings_are_deterministic_and_normalized() -> None:
    provider = FakeEmbeddingProvider(64)
    a, b = provider.embed_documents(["Refund timeline", "Refund timeline"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert provider.embed_query("") != [0.0] * 64


def test_openai_plan_parses_tool_call_and_usage() -> None:
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="search_knowledge", arguments='{"query": "x"}')
    )
    llm = _llm(_response(SimpleNamespace(tool_calls=[tool_call], content=None)))
    result = llm.plan(system_prompt="s", user_message="u", tools=TOOLS)
    assert result.tool_call is not None
    assert result.tool_call.name == "search_knowledge"
    assert result.usage.prompt_tokens == 11


def test_openai_plan_without_tool_call_returns_none() -> None:
    llm = _llm(_response(SimpleNamespace(tool_calls=None, content="hello")))
    assert llm.plan(system_prompt="s", user_message="u", tools=TOOLS).tool_call is None


def test_openai_timeout_maps_to_provider_timeout() -> None:
    llm = _llm(openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(ProviderTimeoutError):
        llm.plan(system_prompt="s", user_message="u", tools=TOOLS)


def test_openai_status_error_maps_to_provider_error_without_raw_message() -> None:
    response = httpx2.Response(500, request=_REQUEST)
    llm = _llm(openai.InternalServerError("secret upstream details", response=response, body=None))
    with pytest.raises(ProviderError) as excinfo:
        llm.generate_answer(system_prompt="s", user_prompt="u", question="q", passages=[])
    assert "secret upstream details" not in str(excinfo.value)


@pytest.mark.parametrize(
    "response", [SimpleNamespace(choices=[], usage=None), _response(SimpleNamespace(content=None))]
)
def test_openai_malformed_answer_raises_response_error(response: Any) -> None:
    with pytest.raises(ProviderResponseError):
        _llm(response).generate_answer(
            system_prompt="s", user_prompt="u", question="q", passages=[]
        )


def test_openai_embeddings_validate_dimensions() -> None:
    bad = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])])
    provider = OpenAIEmbeddingProvider(
        api_key="test", model="emb", dimensions=3, timeout_seconds=1, client=_client(bad)
    )
    with pytest.raises(ProviderResponseError):
        provider.embed_documents(["text"])
