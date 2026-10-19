from typing import Any

from pydantic import BaseModel, Field


class DocumentRecord(BaseModel):
    id: str
    title: str
    source_path: str
    content_hash: str


class ChunkRecord(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    section: str
    embedding: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    source_path: str
    section: str
    chunk_index: int
    content: str
    score: float


class SourceDocument(BaseModel):
    document_id: str
    title: str
    source_path: str
    chunk_count: int


class IngestionError(BaseModel):
    source_path: str
    error: str


class IngestionReport(BaseModel):
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    errors: list[IngestionError] = Field(default_factory=list)
    chunk_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors
