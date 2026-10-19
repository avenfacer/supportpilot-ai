import math
from abc import ABC, abstractmethod

from app.ai.errors import ProviderResponseError


class EmbeddingProvider(ABC):
    name: str
    model: str
    dimensions: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def validate_vectors(vectors: list[list[float]], expected_count: int, dimensions: int) -> None:
    """Reject provider output that would otherwise be stored or searched as an invalid vector."""
    if len(vectors) != expected_count:
        raise ProviderResponseError(f"expected {expected_count} embeddings, got {len(vectors)}")
    for vector in vectors:
        if len(vector) != dimensions:
            raise ProviderResponseError(f"expected {dimensions} dimensions, got {len(vector)}")
        if not all(math.isfinite(x) for x in vector):
            raise ProviderResponseError("embedding contains non-finite values")
        if not any(vector):
            raise ProviderResponseError("embedding is a zero vector")
