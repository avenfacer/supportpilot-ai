"""Deterministic, offline embedding provider (feature hashing). For tests, evals, and demos.

It captures lexical overlap only, not meaning, so paraphrases with no shared words score low.
"""

import hashlib
import itertools
import math

from app.ai.embedding_provider import EmbeddingProvider, validate_vectors
from app.ai.text import content_tokens


class FakeEmbeddingProvider(EmbeddingProvider):
    name = "fake"
    model = "fake-hashing-v1"

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dimensions, 1.0 if (value >> 63) & 1 else -1.0

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = content_tokens(text)
        features: list[tuple[str, float]] = [(f"w:{t}", 1.0) for t in tokens]
        features += [(f"b:{a}_{b}", 0.5) for a, b in itertools.pairwise(tokens)]
        if not features:
            features = [("empty", 1.0)]
        for feature, weight in features:
            index, sign = self._bucket(feature)
            vector[index] += sign * weight
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = [self._embed(t) for t in texts]
        validate_vectors(vectors, len(texts), self.dimensions)
        return vectors
