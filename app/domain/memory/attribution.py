"""Epistemic attribution of memory text."""

from __future__ import annotations

import re

from app.domain.memory.types import MemoryEpistemicStatus, MemoryScope

_LEADING_PRONOUN_RE = re.compile(
    r"^(?:he|she|they)\s+(?=[a-z])",
    re.IGNORECASE,
)


_WE_DISCUSSED_HIS_HER_RE = re.compile(
    r"^we\s+discussed\s+(?:his|her|their)\s+",
    re.IGNORECASE,
)


def default_epistemic_status_for_scope(scope: MemoryScope) -> MemoryEpistemicStatus:
    """Return canonical epistemic framing for ``scope``."""
    if scope is MemoryScope.USER_PREFERENCE:
        return MemoryEpistemicStatus.USER_STATED_PREFERENCE
    return MemoryEpistemicStatus.USER_REPORTED_OBSERVATION


def ensure_attributed_epistemic_text(
    text: str,
    *,
    scope: MemoryScope,
    contact_name: str | None = None,
) -> str:
    """Normalize memory phrasing so observations remain attributed rather than universal claims."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return cleaned

    if scope is MemoryScope.USER_PREFERENCE:
        lowered = cleaned.lower()
        if lowered.startswith("i prefer "):
            cleaned = "Prefers " + cleaned[9:]
        elif lowered.startswith("i like "):
            cleaned = "Likes " + cleaned[7:]
        return cleaned[:1000]

    if contact_name:
        first_name = contact_name.strip().split()[0]
        if first_name and first_name.lower() not in cleaned.lower():
            if _WE_DISCUSSED_HIS_HER_RE.match(cleaned):
                remainder = _WE_DISCUSSED_HIS_HER_RE.sub("", cleaned, count=1)
                cleaned = f"{contact_name.strip()} discussed {remainder}"
            elif _LEADING_PRONOUN_RE.match(cleaned):
                remainder = _LEADING_PRONOUN_RE.sub("", cleaned, count=1)
                cleaned = f"{contact_name.strip()} {remainder}"
            elif cleaned.lower().startswith("we discussed "):
                remainder = cleaned[13:].strip()
                cleaned = f"Discussed with {contact_name.strip()}: {remainder}"
    return cleaned[:1000]
