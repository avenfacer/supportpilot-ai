import logging
from dataclasses import dataclass, field

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.safety import looks_like_prompt_injection
from app.repositories.base import KnowledgeRepository
from app.schemas.knowledge import RetrievedChunk

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 1000


def normalize_query(query: str) -> str:
    return " ".join(query.split())[:MAX_QUERY_CHARS]


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk]
    top_score: float | None
    candidates: list[RetrievedChunk] = field(default_factory=list)
    quarantined_ids: list[str] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return bool(self.chunks)

    @property
    def chunk_ids(self) -> set[str]:
        return {c.chunk_id for c in self.chunks}


class RetrievalService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: EmbeddingProvider,
        *,
        top_k: int,
        min_score: float,
    ):
        self._repo = repository
        self._embedder = embedder
        self.top_k = top_k
        self.min_score = min_score

    def retrieve(self, query: str) -> RetrievalResult:
        normalized = normalize_query(query)
        if not normalized:
            return RetrievalResult(query=normalized, chunks=[], top_score=None)

        candidates = self._repo.search(self._embedder.embed_query(normalized), self.top_k)
        quarantined = [c.chunk_id for c in candidates if looks_like_prompt_injection(c.content)]
        if quarantined:
            logger.warning("retrieval_quarantined_chunks", extra={"chunk_ids": quarantined})

        relevant = [
            c for c in candidates if c.score >= self.min_score and c.chunk_id not in quarantined
        ]
        top_score = candidates[0].score if candidates else None
        logger.info(
            "retrieval_completed",
            extra={
                "candidates": len(candidates),
                "relevant": len(relevant),
                "top_score": round(top_score, 4) if top_score is not None else None,
                "min_score": self.min_score,
            },
        )
        return RetrievalResult(
            query=normalized,
            chunks=relevant,
            top_score=top_score,
            candidates=candidates,
            quarantined_ids=quarantined,
        )
