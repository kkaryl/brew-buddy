"""Pure domain rules for memory safety filtering, attribution, deduplication, and supersession."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import Memory
from app.domain.types import MemoryEpistemicStatus, MemoryScope, MemoryType

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_MEMORY_STOPWORDS = frozenset(
    {
        "about",
        "also",
        "and",
        "are",
        "been",
        "discussed",
        "during",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "her",
        "him",
        "his",
        "into",
        "mentioned",
        "more",
        "noted",
        "our",
        "said",
        "session",
        "shared",
        "she",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "was",
        "were",
        "with",
        "would",
    }
)

_SENSITIVE_AND_SPECULATIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sensitive health or medical assumption",
        re.compile(
            r"\b(?:medical leave|medical condition|chronic illness|mental health|"
            r"struggling with anxiety|depression|in therapy|pregnant|pregnancy|"
            r"looks burned out|seems burned out|severe burnout)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sensitive family or marital assumption",
        re.compile(
            r"\b(?:going through a divorce|marital (?:problems|issues|trouble)|"
            r"custody battle|family crisis|estranged spouse)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sensitive religious, political, or financial assumption",
        re.compile(
            r"\b(?:religious beliefs|political affiliation|voted for|"
            r"financial trouble|personal debt|going bankrupt|severely underpaid)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "speculative third-party or employment rumor",
        re.compile(
            r"\b(?:getting fired|about to be fired|about to be laid off|"
            r"on a pip|failed (?:his|her|their) performance review|"
            r"secretly interviewing|rumor (?:is|that)|gossip that|heard a rumor|"
            r"i assume (?:his|her|their|coworker|manager|boss)|"
            r"my guess is (?:his|her|their)|"
            r"(?:coworker|colleague|manager|boss)\s+[a-z]+\s+is\s+"
            r"(?:incompetent|dishonest|toxic|getting fired))\b",
            re.IGNORECASE,
        ),
    ),
)

_OPPOSING_STANCE_GROUPS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (
        frozenset({"informal", "casual", "relaxed", "unstructured", "conversational"}),
        frozenset({"formal", "structured", "executive", "scripted"}),
    ),
    (
        frozenset({"concise", "short", "brief", "quick", "compact"}),
        frozenset({"detailed", "deep", "long", "thorough", "comprehensive"}),
    ),
    (
        frozenset({"prefer", "prefers", "like", "likes", "always", "include", "using", "adopted"}),
        frozenset(
            {
                "avoid",
                "avoids",
                "dislike",
                "dislikes",
                "never",
                "exclude",
                "stopped",
                "dropped",
                "abandoned",
            }
        ),
    ),
)

_EXPLICIT_UPDATE_MARKERS: tuple[str, ...] = (
    "instead of",
    "rather than",
    "no longer",
    "switched from",
    "switched to",
    "moved away from",
    "changed from",
    "actually prefer",
    "actually prefers",
    "now prefer",
    "now prefers",
    "updated preference",
)

_LEADING_PRONOUN_RE = re.compile(
    r"^(?:he|she|they)\s+(?=[a-z])",
    re.IGNORECASE,
)
_WE_DISCUSSED_HIS_HER_RE = re.compile(
    r"^we\s+discussed\s+(?:his|her|their)\s+",
    re.IGNORECASE,
)


class MemoryRelationKind(StrEnum):
    """Classification of a candidate memory relative to existing active memories."""

    DISTINCT = "distinct"
    DUPLICATE = "duplicate"
    SUPERSEDES = "supersedes"


@dataclass(frozen=True, slots=True)
class MemoryRelationResolution:
    """Deterministic outcome comparing a candidate memory against active storage."""

    kind: MemoryRelationKind
    matched_memory: Memory | None = None
    reason: str | None = None


def detect_sensitive_or_third_party_assumption(text: str) -> str | None:
    """Return a rejection reason if ``text`` contains sensitive or speculative assumptions."""
    for reason, pattern in _SENSITIVE_AND_SPECULATIVE_PATTERNS:
        if pattern.search(text) is not None:
            return reason
    return None


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


def _normalize_tokens(text: str, *, ignored_names: set[str]) -> set[str]:
    raw_tokens = set(_TOKEN_RE.findall(text.lower()))
    normalized: set[str] = set()
    for tok in raw_tokens:
        if tok in _MEMORY_STOPWORDS or tok in ignored_names or len(tok) < 3:
            continue
        stem = tok[:-1] if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss") else tok
        normalized.add(stem)
    return normalized


def _numeric_figures(text: str) -> frozenset[str]:
    """Return every number written in ``text`` (word tokens drop one-digit figures)."""
    return frozenset(_NUMBER_RE.findall(text))


def _has_opposing_stance(candidate_text: str, existing_text: str) -> bool:
    cand_words = set(_TOKEN_RE.findall(candidate_text.lower()))
    exist_words = set(_TOKEN_RE.findall(existing_text.lower()))

    for side_a, side_b in _OPPOSING_STANCE_GROUPS:
        if (cand_words & side_a and exist_words & side_b) or (
            cand_words & side_b and exist_words & side_a
        ):
            return True

    cand_lower = candidate_text.lower()
    return any(marker in cand_lower for marker in _EXPLICIT_UPDATE_MARKERS)


def classify_candidate_against_existing(
    *,
    scope: MemoryScope,
    contact_id: str | None,
    memory_type: MemoryType,
    text: str,
    existing_memories: Sequence[Memory],
    explicit_supersedes_memory_id: str | None = None,
    contact_name: str | None = None,
) -> MemoryRelationResolution:
    """Classify whether a candidate is distinct, duplicate, or supersedes an existing memory."""
    active_same_partition = [
        mem
        for mem in existing_memories
        if mem.is_active and mem.scope is scope and mem.contact_id == contact_id
    ]
    if not active_same_partition:
        return MemoryRelationResolution(kind=MemoryRelationKind.DISTINCT)

    if explicit_supersedes_memory_id is not None:
        for mem in active_same_partition:
            if mem.id == explicit_supersedes_memory_id:
                return MemoryRelationResolution(
                    kind=MemoryRelationKind.SUPERSEDES,
                    matched_memory=mem,
                    reason=f"Explicitly supersedes prior memory '{mem.id}'.",
                )

    ignored_names = (
        set(_TOKEN_RE.findall(contact_name.lower())) if contact_name is not None else set()
    )
    cand_norm_exact = " ".join(_TOKEN_RE.findall(text.lower()))
    cand_tokens = _normalize_tokens(text, ignored_names=ignored_names)

    best_contradiction: Memory | None = None
    best_contradiction_overlap = 0

    for mem in active_same_partition:
        # Word tokens need two characters, so "3 reports" and "5 reports" normalize to the
        # same string. Figures are compared separately so a changed number is never read
        # as a repeat.
        same_figures = _numeric_figures(text) == _numeric_figures(mem.text)
        exist_norm_exact = " ".join(_TOKEN_RE.findall(mem.text.lower()))
        if cand_norm_exact == exist_norm_exact and same_figures:
            return MemoryRelationResolution(
                kind=MemoryRelationKind.DUPLICATE,
                matched_memory=mem,
                reason=f"Exact normalized match with active memory '{mem.id}'.",
            )

        exist_tokens = _normalize_tokens(mem.text, ignored_names=ignored_names)
        shared = cand_tokens & exist_tokens
        union = cand_tokens | exist_tokens
        jaccard = (len(shared) / len(union)) if union else 0.0

        opposing = _has_opposing_stance(text, mem.text)
        if opposing and (len(shared) >= 1 or (mem.memory_type is memory_type and jaccard >= 0.2)):
            if len(shared) >= best_contradiction_overlap:
                best_contradiction = mem
                best_contradiction_overlap = len(shared)
            continue

        if not opposing and jaccard >= 0.68:
            if not same_figures:
                # The same statement with a different figure ("12 engineers" -> "40
                # engineers") is an update the user must review, not a repeat to drop.
                if len(shared) >= best_contradiction_overlap:
                    best_contradiction = mem
                    best_contradiction_overlap = len(shared)
                continue
            return MemoryRelationResolution(
                kind=MemoryRelationKind.DUPLICATE,
                matched_memory=mem,
                reason=(
                    f"Semantic duplicate of active memory '{mem.id}' (similarity={jaccard:.2f})."
                ),
            )

    if best_contradiction is not None:
        return MemoryRelationResolution(
            kind=MemoryRelationKind.SUPERSEDES,
            matched_memory=best_contradiction,
            reason=(
                f"Updates or contradicts active memory '{best_contradiction.id}': "
                f"{best_contradiction.text[:120]}"
            ),
        )

    return MemoryRelationResolution(kind=MemoryRelationKind.DISTINCT)
