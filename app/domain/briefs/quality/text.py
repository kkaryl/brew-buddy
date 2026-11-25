"""Tokenizing and similarity helpers shared by the brief quality rules."""

from __future__ import annotations

import re

from app.domain.briefs.quality.lexicons import QUESTION_STOPWORDS

WORD_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def normalize_text_for_dedup(text: str) -> str:
    return " ".join(WORD_TOKEN_RE.findall(text.lower()))


def question_content_tokens(text: str, *, ignored_names: set[str]) -> set[str]:
    tokens = set(WORD_TOKEN_RE.findall(text.lower()))
    return {
        tok
        for tok in tokens
        if len(tok) >= 3 and tok not in QUESTION_STOPWORDS and tok not in ignored_names
    }


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
