"""Deterministic input checks that run before any LLM call."""

import re

from app.prompts import templates

# Phrases typical of attempts to override the assistant's instructions. The
# classifier is also told to reject these; this layer doesn't depend on the model.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|rules|prompts?|guidelines)\b",
        r"\b(system|developer)\s+(prompt|message|instructions?)\b",
        r"\b(reveal|show|print|repeat|output)\b.{0,30}\b(your|the)\s+(prompt|instructions|rules)\b",
        r"\byou are (now|no longer)\b",
        r"\bpretend (to be|you are)\b",
        r"\b(jailbreak|DAN mode|developer mode)\b",
        r"</?\s*(system|user_message|request)\s*>",
    )
]


def check_input(text: str, max_chars: int) -> tuple[str, str] | None:
    """Return (reason, message) if the input must be rejected, else None."""
    if not text.strip():
        return "invalid_input", templates.EMPTY_INPUT
    if len(text) > max_chars:
        return "invalid_input", templates.TOO_LONG.format(max_chars=max_chars)
    if any(p.search(text) for p in _INJECTION_PATTERNS):
        return "unsafe_input", templates.UNSAFE_INPUT
    return None
