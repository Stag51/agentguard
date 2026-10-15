"""Redaction of sensitive text before it is stored (requirement N5).

WHY: traces capture prompts and tool outputs, which can hold secrets or
personal data. Redacting at the SDK/collector boundary means nothing sensitive
reaches the database or payload files.

This is a pragmatic regex filter, not a guarantee. Real deployments should add
rules for their own data. Order ids like ORD-1003 are deliberately NOT redacted.
"""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_NUMBER]"),
]


def redact(text: str) -> str:
    """Return `text` with keys, emails and long digit runs masked."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
