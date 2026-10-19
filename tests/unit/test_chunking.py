from app.services.chunking import normalize_whitespace, parse_markdown, split_text

DOC = """# Returns and Exchanges

Intro   line with   extra spaces.

## Return window

Most items can be returned within 30 days.

## Exchanges

### Sizes

Exchange for another size.
"""


def test_parse_markdown_preserves_title_sections_and_indexes() -> None:
    parsed = parse_markdown(
        document_id="returns", source_path="kb/returns.md", text=DOC, chunk_size=800, overlap=100
    )
    assert parsed.title == "Returns and Exchanges"
    assert parsed.source_path == "kb/returns.md"
    assert [c.section for c in parsed.chunks] == ["Overview", "Return window", "Exchanges > Sizes"]
    assert [c.chunk_index for c in parsed.chunks] == [0, 1, 2]
    assert [c.chunk_id for c in parsed.chunks] == ["returns:000", "returns:001", "returns:002"]
    assert parsed.chunks[0].content == "Intro line with extra spaces."
    assert all(c.document_id == "returns" for c in parsed.chunks)


def test_long_sections_are_split_with_overlap_and_size_limit() -> None:
    text = " ".join(f"word{i}" for i in range(400))
    pieces = split_text(text, chunk_size=300, overlap=60)
    assert len(pieces) > 1
    assert all(len(p) <= 300 for p in pieces)
    first_tail = pieces[0].split()[-3:]
    assert any(token in pieces[1].split() for token in first_tail), "expected overlapping words"
    assert " ".join(pieces).split()[-1] == "word399"


def test_split_text_never_cuts_words() -> None:
    text = " ".join(["supercalifragilistic"] * 60)
    for piece in split_text(text, chunk_size=200, overlap=40):
        assert set(piece.split()) == {"supercalifragilistic"}


def test_normalize_whitespace_keeps_paragraph_breaks() -> None:
    assert normalize_whitespace("a  b\n c\n\n\n d") == "a b c\n\nd"
