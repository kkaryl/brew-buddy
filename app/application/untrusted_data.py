"""Deterministic PII scrubbing and untrusted-note prompt-injection sanitization.

Kept inside the pure application layer (stdlib ``re`` + ``dataclasses`` only) so
both ADK tools, guardrail plugins, and application services share one fail-closed
sanitization pipeline without introducing external SDK dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Clause-level patterns matching indirect prompt-injection / instruction-override attempts
# embedded inside untrusted meeting notes, contact notes, or memory excerpts.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n;]{0,80}"
        r"\b(?:previous|prior|above|system|developer|safety|all)\s+"
        r"(?:instructions?|prompts?|rules?|constraints?|guardrails?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:system\s*override|developer\s*mode|new\s+instructions?|role\s*:\s*system)\b"
        r"[^.\n;]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:<\s*/?\s*(?:system|instruction|developer|tool_call)\s*>|\[\s*/?\s*INST\s*\])"
        r"[^.\n;]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:call|invoke|execute)\s+(?:the\s+)?(?:tool|function)?\s*"
        r"(?:get_user_preferences|get_contact_context|get_meeting_history|suggest_memory_candidates)"
        r"[^.\n;]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:user_id|owner_user_id)\s*[:=]\s*['\"]?[A-Za-z0-9._:-]+['\"]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|print|output|leak|exfiltrate)\s+(?:the\s+)?"
        r"(?:system\s+prompt|hidden\s+instructions?|secret|api\s+key|other\s+users?)\b"
        r"[^.\n;]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bauto[-_\s]?approve\b[^.\n;]*\bmemor(?:y|ies)\b",
        re.IGNORECASE,
    ),
)

STRIPPED_DIRECTIVE_MARKER = "[UNTRUSTED_INSTRUCTION_STRIPPED]"


@dataclass(frozen=True, slots=True)
class SanitizedTextResult:
    """Result of scrubbing PII and neutralizing embedded prompt-injection directives."""

    text: str
    injection_detected: bool
    pii_redacted: bool


def redact_pii_text(text: str) -> tuple[str, bool]:
    """Deterministically redact email addresses, SSNs, and phone numbers."""
    after_email = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    after_ssn = _SSN_RE.sub("[REDACTED_SSN]", after_email)
    after_phone = _PHONE_RE.sub("[REDACTED_PHONE]", after_ssn)
    return after_phone, (after_phone != text)


def contains_prompt_injection(text: str) -> bool:
    """Return ``True`` if ``text`` matches known instruction-override patterns."""
    return any(pattern.search(text) is not None for pattern in _INJECTION_PATTERNS)


def sanitize_untrusted_text(
    text: str,
    *,
    max_chars: int = 500,
) -> SanitizedTextResult:
    """Scrub PII, neutralize embedded prompt-injection clauses, and bound length."""
    scrubbed, pii_redacted = redact_pii_text(text)
    injection_detected = False
    cleaned = scrubbed

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            injection_detected = True
            cleaned = pattern.sub(STRIPPED_DIRECTIVE_MARKER, cleaned)

    normalized = re.sub(r"\s+", " ", cleaned).strip()
    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 3].rstrip() + "..."

    return SanitizedTextResult(
        text=normalized,
        injection_detected=injection_detected,
        pii_redacted=pii_redacted,
    )


def split_safe_note_segments(notes: str) -> tuple[list[str], int]:
    """Split notes into PII-scrubbed factual clauses while dropping injected directives.

    Returns:
        Tuple of ``(safe_segments, dropped_injection_count)``.
    """
    scrubbed, _ = redact_pii_text(notes)
    raw_clauses = [clause.strip() for clause in re.split(r"[\n.;]+", scrubbed) if clause.strip()]

    safe_segments: list[str] = []
    dropped_count = 0
    for clause in raw_clauses:
        if contains_prompt_injection(clause):
            dropped_count += 1
            continue
        sanitized = sanitize_untrusted_text(clause, max_chars=1000)
        if sanitized.injection_detected:
            dropped_count += 1
            continue
        if len(sanitized.text) >= 5:
            safe_segments.append(sanitized.text)

    return safe_segments, dropped_count
