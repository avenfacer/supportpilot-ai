"""Offline evaluation harness.

Runs every case in `evals/cases.jsonl` through the real chat pipeline (orchestrator, registry,
retrieval, grounding checks, order and ticket services) backed by in-memory repositories, then
computes outcome, retrieval, citation, safety, latency, and token metrics.
"""

import json
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.grounded_answer import ungrounded_numbers
from app.ai.llm_provider import LLMProvider
from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import AppError
from app.core.security import CustomerContext
from app.demo_data import load_demo_store
from app.repositories.memory import (
    InMemoryKnowledgeRepository,
    InMemoryOrderRepository,
    InMemoryTicketRepository,
)
from app.schemas.chat import ChatRequest, ChatStatus
from app.schemas.knowledge import RetrievedChunk
from app.services.chat_service import build_chat_service
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService

CASES_PATH = PROJECT_ROOT / "evals" / "cases.jsonl"
SAFE_ABSTAIN = {ChatStatus.UNSUPPORTED, ChatStatus.HANDOFF, ChatStatus.NEEDS_CLARIFICATION}
# Illustrative list prices (USD per 1M tokens) for cost estimates; verify current pricing.
PRICE_PER_MTOK = {"gpt-4o-mini": (0.15, 0.60)}


class EvalCase(BaseModel):
    id: str
    category: str
    message: str
    customer_id: str | None = None
    order_api_mode: Literal["none", "timeout", "unavailable"] = "none"
    expected_status: list[ChatStatus]
    expected_sources: list[str] = Field(default_factory=list)
    expected_tool: str | None = None
    expect_ticket: bool | None = None
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    notes: str = ""


class CaseResult(BaseModel):
    id: str
    category: str
    passed: bool
    failures: list[str]
    status: str
    tool: str | None
    answer: str
    citation_ids: list[str]
    citations_valid: bool
    ticket_created: bool
    retrieval_hit_at_k: bool | None = None
    grounded: bool | None = None
    latency_ms: float
    timings_ms: dict[str, float]
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class EvalEnvironment:
    settings: Settings
    llm: LLMProvider
    embedder: EmbeddingProvider
    knowledge: InMemoryKnowledgeRepository
    orders: InMemoryOrderRepository

    @property
    def chunk_index(self) -> dict[str, str]:
        return {c.id: c.content for chunks in self.knowledge.chunks.values() for c in chunks}


def load_cases(path: Path = CASES_PATH) -> list[EvalCase]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EvalCase.model_validate(json.loads(line)) for line in lines if line.strip()]


def build_environment(
    settings: Settings, llm: LLMProvider, embedder: EmbeddingProvider
) -> EvalEnvironment:
    knowledge = InMemoryKnowledgeRepository()
    report = IngestionService(
        knowledge, embedder, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    ).ingest_directory(settings.knowledge_base_dir)
    if not report.ok:
        raise RuntimeError(f"knowledge base ingestion failed: {report.errors}")
    return EvalEnvironment(
        settings, llm, embedder, knowledge, InMemoryOrderRepository(load_demo_store().orders)
    )


def _retrieval_hit(env: EvalEnvironment, case: EvalCase) -> bool | None:
    if not case.expected_sources or case.expected_tool != "search_knowledge":
        return None
    service = RetrievalService(
        env.knowledge, env.embedder, top_k=env.settings.retrieval_top_k, min_score=-1.0
    )
    top_docs = {c.document_id for c in service.retrieve(case.message).candidates}
    return bool(top_docs & set(case.expected_sources))


def run_case(env: EvalEnvironment, case: EvalCase) -> CaseResult:
    tickets = InMemoryTicketRepository()
    settings = env.settings.model_copy(update={"mock_order_failure_mode": case.order_api_mode})
    service = build_chat_service(
        settings=settings,
        llm=env.llm,
        embedder=env.embedder,
        knowledge=env.knowledge,
        orders=env.orders,
        tickets=tickets,
    )
    customer = CustomerContext(case.customer_id) if case.customer_id else None

    started = time.perf_counter()
    try:
        turn = service.handle(ChatRequest(message=case.message), customer)
    except AppError as exc:
        return CaseResult(
            id=case.id,
            category=case.category,
            passed=False,
            failures=[f"request failed: {exc.code}"],
            status=f"error:{exc.code}",
            tool=None,
            answer="",
            citation_ids=[],
            citations_valid=True,
            ticket_created=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            timings_ms={},
        )
    latency = round((time.perf_counter() - started) * 1000, 2)
    response = turn.response
    failures: list[str] = []

    if response.status not in case.expected_status:
        expected = "/".join(s.value for s in case.expected_status)
        failures.append(f"status {response.status.value} not in {expected}")
    if case.expected_tool and turn.tool != case.expected_tool:
        failures.append(f"tool {turn.tool} != {case.expected_tool}")
    answer_lower = response.answer.lower()
    failures += [f"missing '{s}'" for s in case.must_include if s.lower() not in answer_lower]
    failures += [f"leaked '{s}'" for s in case.must_not_include if s.lower() in answer_lower]

    citation_ids = [c.source_id for c in response.citations]
    retrieved = set(turn.retrieved_chunk_ids)
    citations_valid = all(cid in retrieved for cid in citation_ids)
    if not citations_valid:
        failures.append("citation not in retrieval results")
    cited_docs = {c.document_id for c in response.citations}
    if (
        case.expected_sources
        and response.status is ChatStatus.ANSWERED
        and not cited_docs & set(case.expected_sources)
    ):
        failures.append(f"cited {sorted(cited_docs)} instead of {case.expected_sources}")

    ticket_created = bool(tickets.tickets)
    if case.expect_ticket is not None and ticket_created != case.expect_ticket:
        failures.append(f"ticket_created={ticket_created}, expected {case.expect_ticket}")
    if any(t.status.value != "pending_human_review" for t in tickets.tickets.values()):
        failures.append("ticket not pending_human_review")

    grounded: bool | None = None
    if response.status is ChatStatus.ANSWERED and turn.tool == "search_knowledge":
        index = env.chunk_index
        cited = [
            RetrievedChunk(
                chunk_id=cid,
                document_id="",
                document_title="",
                source_path="",
                section="",
                chunk_index=0,
                content=index.get(cid, ""),
                score=0,
            )
            for cid in citation_ids
        ]
        grounded = bool(cited) and not ungrounded_numbers(response.answer, cited)

    return CaseResult(
        id=case.id,
        category=case.category,
        passed=not failures,
        failures=failures,
        status=response.status.value,
        tool=turn.tool,
        answer=response.answer,
        citation_ids=citation_ids,
        citations_valid=citations_valid,
        ticket_created=ticket_created,
        retrieval_hit_at_k=_retrieval_hit(env, case),
        grounded=grounded,
        latency_ms=latency,
        timings_ms=turn.timings_ms,
        prompt_tokens=turn.usage.prompt_tokens,
        completion_tokens=turn.usage.completion_tokens,
    )


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 2)


def summarize(env: EvalEnvironment, results: list[CaseResult]) -> dict[str, Any]:
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    answerable = [r for r in results if r.category in {"faq", "paraphrase", "confusable"}]
    unsupported = by_category.get("unsupported", [])
    authz = by_category.get("order_unauthorized", []) + by_category.get("prompt_injection", [])
    tool_cases = [r for r in results if r.category == "order_success"]
    timings: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for stage, value in r.timings_ms.items():
            timings[stage].append(value)

    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)
    price = PRICE_PER_MTOK.get(env.llm.model)
    cost = (
        round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 5)
        if price
        else None
    )

    return {
        "llm_provider": f"{env.llm.name} ({env.llm.model})",
        "embedding_provider": env.embedder.name,
        "top_k": env.settings.retrieval_top_k,
        "min_score": env.settings.effective_min_score,
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "metrics": {
            "outcome_pass_rate": _rate([r.passed for r in results]),
            "retrieval_recall_at_k": _rate(
                [r.retrieval_hit_at_k for r in results if r.retrieval_hit_at_k is not None]
            ),
            "answerable_answered_rate": _rate([r.status == "answered" for r in answerable]),
            "citation_validity": _rate(
                [r.citations_valid for r in results if r.citation_ids] or [True]
            ),
            "grounded_answer_rate": _rate(
                [bool(r.grounded) for r in results if r.grounded is not None]
            ),
            "unsupported_abstention_rate": _rate(
                [r.status in SAFE_ABSTAIN and not r.citation_ids for r in unsupported]
            ),
            "tool_success_rate": _rate([r.passed for r in tool_cases]),
            "authorization_pass_rate": _rate(
                [not any(f.startswith("leaked") for f in r.failures) for r in authz]
            ),
        },
        "category_pass_rate": {
            cat: f"{sum(r.passed for r in rs)}/{len(rs)}" for cat, rs in sorted(by_category.items())
        },
        "latency_ms": {
            "p50_total": _percentile(timings["total"], 50),
            "p95_total": _percentile(timings["total"], 95),
            **{
                f"mean_{stage}": round(statistics.mean(values), 2)
                for stage, values in sorted(timings.items())
                if stage != "total"
            },
        },
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "estimated_cost_usd": cost,
    }


def render_markdown(summary: dict[str, Any], results: list[CaseResult]) -> str:
    m = summary["metrics"]
    lines = [
        "# Evaluation results",
        "",
        f"- LLM provider: `{summary['llm_provider']}`",
        f"- Embedding provider: `{summary['embedding_provider']}`",
        f"- Retrieval: top_k={summary['top_k']}, min_score={summary['min_score']}",
        f"- Cases: {summary['cases']}, passed: {summary['passed']}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        *[f"| {name} | {value} |" for name, value in m.items()],
        "",
        "## Pass rate by category",
        "",
        "| Category | Passed |",
        "| --- | --- |",
        *[f"| {cat} | {value} |" for cat, value in summary["category_pass_rate"].items()],
        "",
        "## Latency (ms, in-process, excludes network)",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        *[f"| {name} | {value} |" for name, value in summary["latency_ms"].items()],
        "",
        f"Tokens: prompt={summary['tokens']['prompt']}, "
        f"completion={summary['tokens']['completion']}. "
        f"Estimated cost (USD): {summary['estimated_cost_usd']}",
        "",
        "## Failed cases",
        "",
    ]
    failed = [r for r in results if not r.passed]
    if not failed:
        lines.append("None.")
    else:
        lines += ["| Case | Category | Status | Failures |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {r.id} | {r.category} | {r.status} | {'; '.join(r.failures)} |" for r in failed
        ]
    return "\n".join(lines) + "\n"


def run_evaluation(
    settings: Settings, llm: LLMProvider, embedder: EmbeddingProvider, cases: list[EvalCase]
) -> tuple[dict[str, Any], list[CaseResult]]:
    env = build_environment(settings, llm, embedder)
    results = [run_case(env, case) for case in cases]
    return summarize(env, results), results
