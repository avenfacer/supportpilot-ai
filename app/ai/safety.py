"""Deterministic guardrail heuristics applied outside the model.

These are a first line of defence, not a guarantee: authorization, the tool allowlist, citation
validation, and the fixed ticket status are what actually bound the system's behaviour.
"""

import re

_INJECTION_PATTERNS = [
    r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+"
    r"(instructions|rules|messages|prompts?)",
    r"\bdisregard\s+(all\s+|the\s+|your\s+)?(system|previous|prior)\s+(prompt|instructions|rules)",
    r"\b(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+"
    r"(system\s+prompt|hidden\s+prompt|instructions|configuration)",
    r"\byou\s+are\s+now\s+(in\s+)?(developer|dan|admin|god)\s+mode",
    r"\b(act|behave)\s+as\s+(an?\s+)?(admin|administrator|system|developer)\b",
    r"\bsystem\s+prompt\b",
    r"\bnew\s+instructions\s*:",
    r"<\s*/?\s*(system|untrusted_reference)\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_HUMAN_REQUEST_RE = re.compile(
    r"\b(talk|speak|chat)\s+(to|with)\s+(a|an|some)?\s*(human|person|agent|someone|"
    r"representative|operator)\b|\b(real|live)\s+(person|human|agent)\b|"
    r"\bhuman\s+(agent|support|help)\b",
    re.IGNORECASE,
)

_SENSITIVE_RE = re.compile(
    r"\b(fraud|fraudulent|unauthori[sz]ed\s+(charge|payment|transaction)s?|stolen\s+card|"
    r"chargeback|hacked|account\s+(was\s+)?compromised|identity\s+theft|lawyer|lawsuit|legal\s+"
    r"action|sue|injur(y|ed|ies)|caught\s+fire|burn(ed|t)|electric\s+shock|unsafe)\b",
    re.IGNORECASE,
)


def looks_like_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def is_human_request(text: str) -> bool:
    return bool(_HUMAN_REQUEST_RE.search(text))


def is_sensitive_request(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(text))


def escape_reference_text(text: str) -> str:
    """Prevent retrieved text from closing or opening the reference delimiters in the prompt."""
    return text.replace("<", "&lt;").replace(">", "&gt;")
