"""Word lists and patterns used by the brief quality rules."""

from __future__ import annotations

import re

QUESTION_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "are",
        "been",
        "before",
        "between",
        "both",
        "can",
        "could",
        "did",
        "does",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "into",
        "just",
        "like",
        "love",
        "make",
        "more",
        "most",
        "much",
        "over",
        "really",
        "share",
        "should",
        "some",
        "such",
        "tell",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "today",
        "very",
        "walk",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "with",
        "would",
        "you",
        "your",
    }
)


GOAL_LINK_ANCHOR_TERMS = frozenset(
    {
        "agenda",
        "align",
        "approach",
        "architecture",
        "bottleneck",
        "career",
        "challenge",
        "chat",
        "coaching",
        "connection",
        "context",
        "conversation",
        "criteria",
        "customer",
        "decision",
        "depth",
        "direction",
        "discovery",
        "discussion",
        "domain",
        "engineering",
        "evaluation",
        "example",
        "experience",
        "explore",
        "feedback",
        "focus",
        "follow",
        "future",
        "goal",
        "growth",
        "guidance",
        "history",
        "hypothesis",
        "impact",
        "insight",
        "leadership",
        "learn",
        "lesson",
        "mentor",
        "mentorship",
        "metric",
        "misconception",
        "networking",
        "next",
        "nuance",
        "objective",
        "onboarding",
        "opportunity",
        "outcome",
        "pain",
        "perspective",
        "plan",
        "practical",
        "practice",
        "priorit",
        "problem",
        "product",
        "project",
        "purpose",
        "question",
        "rapport",
        "reciprocity",
        "relationship",
        "reliability",
        "resource",
        "revised",
        "revision",
        "roadmap",
        "role",
        "scale",
        "scaling",
        "scope",
        "shift",
        "signal",
        "solution",
        "staff",
        "step",
        "story",
        "strategy",
        "system",
        "team",
        "technical",
        "thread",
        "timebox",
        "trade",
        "transition",
        "understand",
        "value",
        "workflow",
    }
)


FLATTERY_AND_CLICHE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("generic 'pick your brain' cliché", re.compile(r"\bpick your brain\b", re.IGNORECASE)),
    (
        "generic 'keeps you up at night' cliché",
        re.compile(r"\bkeeps you up at night\b", re.IGNORECASE),
    ),
    (
        "excessive sycophantic flattery",
        re.compile(
            r"\b(?:true visionary|legendary career|greatest leader|deeply humbled|"
            r"world-famous genius|unparalleled brilliance)\b",
            re.IGNORECASE,
        ),
    ),
)


OVERLY_FORMAL_PATTERNS = re.compile(
    r"\b(?:pursuant to|herewith|heretofore|dear sir or madam|esteemed colleague|"
    r"humbly request your audience)\b",
    re.IGNORECASE,
)


OVERLY_SLANGY_EXECUTIVE_PATTERNS = re.compile(
    r"\b(?:what's up dude|vibe check|spill the tea|lowkey|no cap)\b",
    re.IGNORECASE,
)


UNSUPPORTED_BIO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "unsupported academic credential or university",
        re.compile(
            r"\b(?:phd|mba|b\.s\.|m\.s\.|graduated from|alumnus of|alumni of|"
            r"studied at|degree from)\b(?:\s+[A-Za-z0-9.&'-]+){0,4}",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported past employer, tenure, or founding claim",
        re.compile(
            r"\b(?:previously worked at|formerly at|former (?:vp|director|cto|ceo|engineer|"
            r"lead|manager) at|co-founded|founded|spent \d+\+?\s+years at)\b"
            r"(?:\s+[A-Za-z0-9.&'-]+){0,4}",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported award, publication, or patent claim",
        re.compile(
            r"\b(?:keynote speaker at|authored the book|published a paper|"
            r"patent holder|won the [a-z0-9 -]+ award)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "private personal characteristic inference",
        re.compile(
            r"\b(?:married to|marital status|has \d+ children|has kids|pregnant|"
            r"religious beliefs|political affiliation|medical condition|personal net worth)\b",
            re.IGNORECASE,
        ),
    ),
)


DURATION_OVERRIDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:only have|shorten(?:ed)?(?:\s+it|\s+agenda)?\s+to|tighten(?:ed)?(?:\s+agenda)?\s+to|"
        r"cut(?:\s+it)?\s+to|down to|make it|cap(?:\s+it)?\s+at|have(?:\s+just|\s+only)?)\s+"
        r"(\d{1,3})\s*(?:-|\s)?(?:minutes?|mins?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,3})\s*(?:-|\s)?(?:minute|min)\s+(?:chat|meeting|call|session|sync|slot|agenda)\b",
        re.IGNORECASE,
    ),
)


ENGINEERING_CAREER_TERMS = frozenset(
    {
        "architecture",
        "career",
        "code",
        "coding",
        "design",
        "distributed",
        "engineer",
        "engineering",
        "ic",
        "infrastructure",
        "ladder",
        "lead",
        "leadership",
        "platform",
        "principal",
        "production",
        "reliability",
        "role",
        "scale",
        "scaling",
        "scope",
        "senior",
        "service",
        "software",
        "staff",
        "system",
        "systems",
        "tech",
        "technical",
    }
)


CUSTOMER_DISCOVERY_TERMS = frozenset(
    {
        "adopt",
        "adoption",
        "alternative",
        "bottleneck",
        "budget",
        "buyer",
        "buying",
        "cost",
        "current",
        "currently",
        "customer",
        "decide",
        "discovery",
        "evaluate",
        "friction",
        "manual",
        "measure",
        "metric",
        "onboarding",
        "pain",
        "pilot",
        "problem",
        "process",
        "solve",
        "solving",
        "spend",
        "team",
        "time",
        "tool",
        "tooling",
        "urgent",
        "value",
        "workaround",
        "workflow",
    }
)
