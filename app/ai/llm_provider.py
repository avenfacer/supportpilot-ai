from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCallProposal:
    """A tool call suggested by the model. Untrusted until validated by the tool registry."""

    name: str
    arguments: str


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: "TokenUsage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


@dataclass(frozen=True)
class PlanResult:
    tool_call: ToolCallProposal | None
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class ContextPassage:
    chunk_id: str
    title: str
    section: str
    content: str


@dataclass(frozen=True)
class AnswerResult:
    raw_text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMProvider(ABC):
    """Task-level interface so business logic never touches a vendor SDK directly.

    Implementations return raw model output; parsing and validation happen in application code.
    """

    name: str
    model: str

    @abstractmethod
    def plan(self, *, system_prompt: str, user_message: str, tools: list[ToolSpec]) -> PlanResult:
        """Ask the model to pick exactly one tool from `tools` for the user's message."""

    @abstractmethod
    def generate_answer(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        question: str,
        passages: list[ContextPassage],
    ) -> AnswerResult:
        """Return a JSON string answering `question` using only `passages`."""
