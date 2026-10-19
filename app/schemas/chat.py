from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.knowledge import RetrievedChunk

EXCERPT_CHARS = 240


class ChatStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    HANDOFF = "handoff"
    TOOL_ERROR = "tool_error"
    UNSUPPORTED = "unsupported"


class ChatRequest(BaseModel):
    # Identity is never accepted in the body; it comes from the trusted request context.
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,64}$")

    @field_validator("message")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class Citation(BaseModel):
    source_id: str = Field(description="Stable chunk ID, e.g. returns:001")
    document_id: str
    document_title: str
    section: str
    source_path: str
    excerpt: str

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> "Citation":
        excerpt = chunk.content
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."
        return cls(
            source_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            section=chunk.section,
            source_path=chunk.source_path,
            excerpt=excerpt,
        )


class ChatResponse(BaseModel):
    status: ChatStatus
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    ticket_id: str | None = None
    needs_human: bool = False
    handoff_reason: str | None = None
    conversation_id: str | None = None
