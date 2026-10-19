"""OpenAI adapters. The only module that imports the OpenAI SDK."""

import logging
from collections.abc import Callable
from typing import Any, TypeVar

import openai

from app.ai.embedding_provider import EmbeddingProvider, validate_vectors
from app.ai.errors import ProviderError, ProviderResponseError, ProviderTimeoutError
from app.ai.llm_provider import (
    AnswerResult,
    ContextPassage,
    LLMProvider,
    PlanResult,
    TokenUsage,
    ToolCallProposal,
    ToolSpec,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")

_EMBEDDING_BATCH_SIZE = 64


def _call(operation: str, fn: Callable[[], T]) -> T:
    """Map SDK exceptions to provider-neutral errors without leaking raw provider messages."""
    try:
        return fn()
    except openai.APITimeoutError as exc:
        logger.warning("provider_timeout", extra={"operation": operation})
        raise ProviderTimeoutError(f"{operation} timed out") from exc
    except openai.APIStatusError as exc:
        logger.warning(
            "provider_status_error",
            extra={"operation": operation, "status_code": exc.status_code},
        )
        raise ProviderError(f"{operation} failed with status {exc.status_code}") from exc
    except openai.APIError as exc:
        logger.warning(
            "provider_error", extra={"operation": operation, "error_type": type(exc).__name__}
        )
        raise ProviderError(f"{operation} failed: {type(exc).__name__}") from exc


def _usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _first_message(response: Any) -> Any:
    choices = getattr(response, "choices", None)
    if not choices:
        raise ProviderResponseError("response has no choices")
    return choices[0].message


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(
        self, *, api_key: str, model: str, timeout_seconds: float, client: Any | None = None
    ):
        self.model = model
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=1
        )

    def plan(self, *, system_prompt: str, user_message: str, tools: list[ToolSpec]) -> PlanResult:
        response = _call(
            "plan",
            lambda: self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        },
                    }
                    for t in tools
                ],
                tool_choice="required",
                parallel_tool_calls=False,
            ),
        )
        message = _first_message(response)
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return PlanResult(tool_call=None, usage=_usage(response))
        function = tool_calls[0].function
        return PlanResult(
            tool_call=ToolCallProposal(name=str(function.name), arguments=str(function.arguments)),
            usage=_usage(response),
        )

    def generate_answer(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        question: str,
        passages: list[ContextPassage],
    ) -> AnswerResult:
        response = _call(
            "generate_answer",
            lambda: self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
        )
        content = getattr(_first_message(response), "content", None)
        if not content:
            raise ProviderResponseError("answer response has no content")
        return AnswerResult(raw_text=str(content), usage=_usage(response))


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        client: Any | None = None,
    ):
        self.model = model
        self.dimensions = dimensions
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=2
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + _EMBEDDING_BATCH_SIZE]
            response = _call(
                "embed",
                lambda batch=batch: self._client.embeddings.create(  # type: ignore[misc]
                    model=self.model, input=batch, dimensions=self.dimensions
                ),
            )
            data = sorted(getattr(response, "data", None) or [], key=lambda d: d.index)
            vectors.extend([list(map(float, d.embedding)) for d in data])
        validate_vectors(vectors, len(texts), self.dimensions)
        return vectors
