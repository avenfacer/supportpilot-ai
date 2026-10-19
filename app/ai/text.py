"""Lightweight text normalization shared by the deterministic (fake) providers."""

import re

STOPWORDS = frozenset(
    """
    a an the and or but if of to in on at by for with from as is are was were be been being it its
    this that these those i me my we our you your he she they them their what which who whom how
    when where why do does did doing can could would should will shall may might must have has had
    having not no so than too very just about into over under again then once there here any all
    some such only own same other more most both each few nor up down out off also get got please
    hi hello thanks thank us am
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_DOUBLE_CONSONANT_RE = re.compile(r"([bcdfghjklmnpqrstvwxz])\1$")


def stem(word: str) -> str:
    """A tiny suffix stripper; good enough to match shipping/shipped/ship in the fake embedder."""
    word = word.removesuffix("'s")
    for suffix, replacement, min_len in (
        ("ations", "", 8),
        ("ation", "", 7),
        ("ies", "y", 5),
        ("ing", "", 6),
        ("ery", "er", 6),
        ("ed", "", 5),
        ("s", "", 4),
    ):
        if len(word) >= min_len and word.endswith(suffix) and not word.endswith("ss"):
            word = word[: -len(suffix)] + replacement
            break
    return _DOUBLE_CONSONANT_RE.sub(r"\1", word)


def content_tokens(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]
