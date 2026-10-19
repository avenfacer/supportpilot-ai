"""Generate an answer from retrieved passages and validate it before it reaches the customer."""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from string import Template

from pydantic import BaseModel, Field, ValidationError

from app.ai.errors import ProviderResponseError
from app.ai.llm_provider import ContextPassage, LLMProvider, TokenUsage
from app.ai.prompts import load_prompt
from app.ai.safety import escape_reference_text
from app.schemas.knowledge import RetrievedChunk

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


class AnswerOutcome(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


class _AnswerPayload(BaseModel):
    answer: str = Field(default="", max_length=2000)
    citation_ids: list[str] = Field(default_factory=list, max_length=20)
    sufficient_evidence: bool
    conflicting_evidence: bool = False


@dataclass
class GroundedAnswer:
    outcome: AnswerOutcome
    answer: str = ""
    citations: list[RetrievedChunk] = field(default_factory=list)
    dropped_citation_ids: list[str] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


def format_passages(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f'<untrusted_reference id="{c.chunk_id}" title="{escape_reference_text(c.document_title)}" '
        f'section="{escape_reference_text(c.section)}">\n'
        f"{escape_reference_text(c.content)}\n</untrusted_reference>"
        for c in chunks
    )


def ungrounded_numbers(answer: str, cited: list[RetrievedChunk]) -> list[str]:
    """Numbers in the answer that appear in none of the cited passages (likely fabricated)."""
    source_numbers = {n for c in cited for n in _NUMBER_RE.findall(c.content)}
    return [n for n in _NUMBER_RE.findall(answer) if n not in source_numbers]


class GroundedAnswerer:
    def __init__(self, llm: LLMProvider):
        self._llm = llm
        self._system_prompt = load_prompt("answer_system")
        self._user_template = Template(load_prompt("answer_user"))

    def answer(self, question: str, chunks: list[RetrievedChunk]) -> GroundedAnswer:
        if not chunks:
            return GroundedAnswer(AnswerOutcome.INSUFFICIENT)

        user_prompt = self._user_template.safe_substitute(
            question=escape_reference_text(question), passages=format_passages(chunks)
        )
        result = self._llm.generate_answer(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            question=question,
            passages=[
                ContextPassage(c.chunk_id, c.document_title, c.section, c.content) for c in chunks
            ],
        )
        try:
            payload = _AnswerPayload.model_validate(json.loads(result.raw_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ProviderResponseError("answer is not valid JSON for the expected schema") from exc

        requested = list(dict.fromkeys(payload.citation_ids))
        retrieved_ids = {c.chunk_id for c in chunks}
        citations = [c for c in chunks if c.chunk_id in set(requested)]
        dropped = [cid for cid in requested if cid not in retrieved_ids]
        if dropped:
            logger.warning("citations_dropped", extra={"dropped_citation_ids": dropped})

        def outcome(kind: AnswerOutcome, text: str = "") -> GroundedAnswer:
            return GroundedAnswer(
                kind,
                answer=text,
                citations=citations if text or kind is AnswerOutcome.CONFLICTING else [],
                dropped_citation_ids=dropped,
                usage=result.usage,
            )

        if payload.conflicting_evidence:
            return outcome(AnswerOutcome.CONFLICTING)
        answer = payload.answer.strip()
        if not payload.sufficient_evidence or not answer or not citations:
            return outcome(AnswerOutcome.INSUFFICIENT)

        unsupported = ungrounded_numbers(answer, citations)
        if unsupported:
            logger.warning("answer_rejected_ungrounded", extra={"numbers": unsupported})
            return outcome(AnswerOutcome.INSUFFICIENT)

        return outcome(AnswerOutcome.ANSWERED, answer)
