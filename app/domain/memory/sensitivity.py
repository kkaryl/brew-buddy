"""Filter for sensitive or speculative third-party memory content."""

from __future__ import annotations

import re

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


def detect_sensitive_or_third_party_assumption(text: str) -> str | None:
    """Return a rejection reason if ``text`` contains sensitive or speculative assumptions."""
    for reason, pattern in _SENSITIVE_AND_SPECULATIVE_PATTERNS:
        if pattern.search(text) is not None:
            return reason
    return None
