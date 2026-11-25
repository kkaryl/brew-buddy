"""Deterministic PII scrubbing for emails, SSNs and phone numbers."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

_PHONE_CANDIDATE = r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)"
# Digit runs the phone pattern would otherwise swallow, but which are ordinary note
# content: ISO-8601 dates, year ranges, and single-dot decimals. Anything with more
# structure than that (dotted or dashed groups, long digit runs) is still redacted.
_NON_PHONE_NUMERIC = (
    r"(?<![\w.+-])(?:"
    r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"|(?:19|20)\d{2}\s?-\s?(?:19|20)\d{2}"
    r"|\d+\.\d+"
    r")(?![\w-]|\.\d)"
)
# One left-to-right pass: a protected token is consumed whole, so the phone pattern can
# never start inside it.
_PHONE_OR_PROTECTED_RE = re.compile(f"(?P<keep>{_NON_PHONE_NUMERIC})|(?P<phone>{_PHONE_CANDIDATE})")


def _redact_phone_match(match: re.Match[str]) -> str:
    return match.group(0) if match.group("keep") is not None else "[REDACTED_PHONE]"


def redact_pii_text(text: str) -> tuple[str, bool]:
    """Deterministically redact email addresses, SSNs, and phone numbers."""
    after_email = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    after_ssn = _SSN_RE.sub("[REDACTED_SSN]", after_email)
    after_phone = _PHONE_OR_PROTECTED_RE.sub(_redact_phone_match, after_ssn)
    return after_phone, (after_phone != text)
