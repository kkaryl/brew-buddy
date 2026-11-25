"""Deterministic email and phone redaction used by the scripted agents."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def scrub_basic_pii(text: str) -> str:
    """Deterministically redact email addresses and phone numbers from free-form text."""
    scrubbed = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    return _PHONE_RE.sub("[REDACTED_PHONE]", scrubbed)
