import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
DEFAULT_SECTION = "Overview"


@dataclass(frozen=True)
class Chunk:
    document_id: str
    chunk_index: int
    section: str
    content: str

    @property
    def chunk_id(self) -> str:
        return f"{self.document_id}:{self.chunk_index:03d}"


@dataclass(frozen=True)
class ParsedDocument:
    document_id: str
    title: str
    source_path: str
    chunks: list[Chunk]


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace inside paragraphs while keeping paragraph breaks."""
    paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    cleaned = (" ".join(p.split()) for p in paragraphs)
    return "\n\n".join(p for p in cleaned if p)


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into windows of at most chunk_size characters, breaking on whitespace."""
    if len(text) <= chunk_size:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return pieces


def parse_markdown(
    *, document_id: str, source_path: str, text: str, chunk_size: int, overlap: int
) -> ParsedDocument:
    title = document_id.replace("_", " ").title()
    sections: list[tuple[str, list[str]]] = [(DEFAULT_SECTION, [])]
    current_h2: str | None = None

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if not match:
            sections[-1][1].append(line)
            continue
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1:
            title = heading
        elif level == 2:
            current_h2 = heading
            sections.append((heading, []))
        else:
            sections.append((f"{current_h2} > {heading}" if current_h2 else heading, []))

    chunks: list[Chunk] = []
    for section, lines in sections:
        body = normalize_whitespace("\n".join(lines))
        for piece in split_text(body, chunk_size, overlap):
            chunks.append(Chunk(document_id, len(chunks), section, piece))
    return ParsedDocument(document_id, title, source_path, chunks)
