"""Helpers for parsing the brief specialists' raw model output."""

from __future__ import annotations

import re

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def strip_optional_json_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    match = _JSON_FENCE_RE.match(cleaned)
    if match is not None:
        return match.group(1).strip()
    return cleaned
