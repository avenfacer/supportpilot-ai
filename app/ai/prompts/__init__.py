"""Versioned prompt templates. Bump PROMPT_VERSION and add new *_vN.md files to change them."""

from functools import lru_cache
from pathlib import Path

PROMPT_VERSION = "v1"
_PROMPT_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str, version: str = PROMPT_VERSION) -> str:
    return (_PROMPT_DIR / f"{name}_{version}.md").read_text(encoding="utf-8").strip()
