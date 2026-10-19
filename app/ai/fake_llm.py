"""Deterministic, offline stand-in for an LLM. For tests, evals, and key-less demos.

The planner is a small rule set and the answerer is extractive (it copies sentences from the
retrieved passages). It honours the same output contracts as the real provider, so the
application's validation logic is exercised identically.
"""

import json
import re

from app.ai.llm_provider import (
    AnswerResult,
    ContextPassage,
    LLMProvider,
    PlanResult,
    ToolCallProposal,
    ToolSpec,
)
from app.ai.text import content_tokens, split_sentences
from app.tools.names import ToolName

ORDER_ID_RE = re.compile(r"\bORD[-\s]?(\d{4,8})\b", re.IGNORECASE)
_HUMAN_RE = re.compile(
    r"\b(human|real person|live agent|support agent|representative|speak to someone|"
    r"talk to someone)\b",
    re.IGNORECASE,
)
_REQUEST_PREFIX = (
    r"(i want to|i'd like to|i would like to|i need to|i wish to|please|help me|"
    r"can you|could you)"
)
_CANCEL_REQUEST_RE = re.compile(
    rf"(\b{_REQUEST_PREFIX}\b[^.?!]*\bcancel\b|^\s*cancel\b)", re.IGNORECASE
)
_RETURN_REQUEST_RE = re.compile(
    rf"(\b{_REQUEST_PREFIX}\b[^.?!]*\b(return|send back)\b|^\s*return\b)", re.IGNORECASE
)
_ORDER_STATUS_RE = re.compile(
    r"\b(where is|where's|status of|track|tracking|shipped yet|arrive|my order|my package)\b",
    re.IGNORECASE,
)
_MIN_ANSWER_OVERLAP = 2
_VAGUE_TOKENS = frozenset(
    {"problem", "issue", "help", "question", "something", "wrong", "need", "want", "thing", "it"}
)


def normalize_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search(text)
    return f"ORD-{match.group(1)}" if match else None


def _proposal(name: ToolName, **arguments: object) -> PlanResult:
    return PlanResult(tool_call=ToolCallProposal(name=name.value, arguments=json.dumps(arguments)))


class FakeLLMProvider(LLMProvider):
    name = "fake"
    model = "fake-rules-v1"

    def plan(self, *, system_prompt: str, user_message: str, tools: list[ToolSpec]) -> PlanResult:
        order_id = normalize_order_id(user_message)
        reason = user_message.strip()[:300]

        if _HUMAN_RE.search(user_message):
            return _proposal(ToolName.REQUEST_HUMAN_HANDOFF, reason="Customer asked for a human.")
        if _CANCEL_REQUEST_RE.search(user_message):
            return _proposal(
                ToolName.CREATE_SUPPORT_REQUEST,
                request_type="cancellation",
                order_id=order_id,
                reason=reason,
            )
        if _RETURN_REQUEST_RE.search(user_message):
            return _proposal(
                ToolName.CREATE_SUPPORT_REQUEST,
                request_type="return",
                order_id=order_id,
                reason=reason,
            )
        if order_id:
            return _proposal(ToolName.LOOKUP_ORDER, order_id=order_id)
        if _ORDER_STATUS_RE.search(user_message):
            return _proposal(
                ToolName.ASK_CLARIFICATION,
                question="Could you share the order ID? It looks like ORD-1234.",
            )
        if set(content_tokens(user_message)) <= _VAGUE_TOKENS:
            return _proposal(
                ToolName.ASK_CLARIFICATION,
                question="Could you tell me a bit more about what you need help with?",
            )
        return _proposal(ToolName.SEARCH_KNOWLEDGE, query=user_message.strip())

    def generate_answer(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        question: str,
        passages: list[ContextPassage],
    ) -> AnswerResult:
        question_tokens = set(content_tokens(question))
        min_overlap = max(1, min(_MIN_ANSWER_OVERLAP, len(question_tokens)))
        scored: list[tuple[int, int, int, str, str]] = []
        for rank, passage in enumerate(passages):
            section_tokens = set(content_tokens(passage.section))
            for position, sentence in enumerate(split_sentences(passage.content)):
                sentence_tokens = set(content_tokens(sentence))
                overlap = len(question_tokens & (sentence_tokens | section_tokens))
                if overlap >= min_overlap and question_tokens & sentence_tokens:
                    scored.append((overlap, -rank, -position, sentence, passage.chunk_id))
        scored.sort(reverse=True)
        chosen = scored[:2]
        payload = {
            "answer": " ".join(s for *_, s, _ in chosen),
            "citation_ids": sorted({cid for *_, cid in chosen}),
            "sufficient_evidence": bool(chosen),
            "conflicting_evidence": False,
        }
        return AnswerResult(raw_text=json.dumps(payload))
