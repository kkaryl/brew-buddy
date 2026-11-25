"""Identifier, timestamp, text and workflow-outcome types used by several contexts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

MIN_SUPPORTED_YEAR = 2000


MAX_SUPPORTED_YEAR = 2100


ENTITY_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


def normalize_utc_datetime(value: datetime) -> datetime:
    """Require timezone-aware datetimes and normalize them to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "Timestamp must be timezone-aware."
        raise ValueError(msg)
    normalized = value.astimezone(UTC)
    if normalized.year < MIN_SUPPORTED_YEAR or normalized.year > MAX_SUPPORTED_YEAR:
        msg = (
            f"Timestamp year must be between {MIN_SUPPORTED_YEAR} "
            f"and {MAX_SUPPORTED_YEAR}, got {normalized.year}."
        )
        raise ValueError(msg)
    return normalized


EntityId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=ENTITY_ID_PATTERN,
    ),
]


UtcDatetime = Annotated[datetime, AfterValidator(normalize_utc_datetime)]


MeetingDurationMinutes = Annotated[
    int,
    Field(
        ge=5,
        le=180,
        description="Meeting duration in minutes (5 to 180).",
    ),
]


VersionNumber = Annotated[
    int,
    Field(
        ge=1,
        description="Optimistic concurrency version counter starting at 1.",
    ),
]


ShortLabelText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


ShortTagText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=80),
]


ObjectiveText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]


RationaleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]


ContextSummaryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=2000),
]


MemoryBodyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=1000),
]


SourceExcerptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


MeetingNotesText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]
