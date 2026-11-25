"""Validated primitive value types and domain enumerations for Brew."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
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

OrganizationNameText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]

ShortTagText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=80),
]

ObjectiveText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]

OpenerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=400),
]

AgendaTitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
]

AgendaDescriptionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=400),
]

QuestionPromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=400),
]

RationaleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=500),
]

FollowUpTopicText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=300),
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

RawSessionNotesText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=10000),
]


class MeetingPurpose(StrEnum):
    """Supported meeting archetypes in Brew."""

    COFFEE_CHAT = "coffee_chat"
    NETWORKING = "networking"
    MENTORSHIP = "mentorship"
    CUSTOMER_DISCOVERY = "customer_discovery"


class MeetingTone(StrEnum):
    """Supported coaching and conversation tones."""

    WARM_CASUAL = "warm_casual"
    CURIOUS_EXPLORATORY = "curious_exploratory"
    STRUCTURED_EXECUTIVE = "structured_executive"
    CANDID_COACHING = "candid_coaching"


class MeetingStatus(StrEnum):
    """Lifecycle states of a meeting session."""

    PREPARING = "preparing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MemoryScope(StrEnum):
    """Target scope of a memory or memory proposal."""

    USER_PREFERENCE = "user_preference"
    CONTACT = "contact"


class MemoryType(StrEnum):
    """Semantic classification of a proposed or approved memory."""

    COMMUNICATION_PREFERENCE = "communication_preference"
    AGENDA_PREFERENCE = "agenda_preference"
    COUNTERPART_BACKGROUND = "counterpart_background"
    SHARED_INTEREST = "shared_interest"
    FOLLOW_UP_COMMITMENT = "follow_up_commitment"
    RELATIONSHIP_NOTE = "relationship_note"


class ConsentStatus(StrEnum):
    """User consent status for durable memories."""

    APPROVED = "approved"
    REVOKED = "revoked"


class ProposalStatus(StrEnum):
    """Human-in-the-loop review status of a memory proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemoryExtractionJobStatus(StrEnum):
    """Lifecycle of a background memory-extraction job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` once the job can no longer change."""
        return self in {MemoryExtractionJobStatus.SUCCEEDED, MemoryExtractionJobStatus.FAILED}


class MemoryLifecycleState(StrEnum):
    """Canonical lifecycle state across staged proposals and durable memories."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryEpistemicStatus(StrEnum):
    """Epistemic status ensuring memories are framed as attributed context, not world facts."""

    USER_REPORTED_OBSERVATION = "user_reported_observation"
    USER_STATED_PREFERENCE = "user_stated_preference"


class MemorySourceType(StrEnum):
    """Originating workflow context for a memory or memory proposal."""

    MEETING_NOTES = "meeting_notes"
    BRIEF_REFINEMENT = "brief_refinement"
    DIRECT_USER_INPUT = "direct_user_input"


class BriefWorkflowTerminalState(StrEnum):
    """Explicit terminal outcomes for the meeting preparation and refinement workflow."""

    COMPLETED = "completed"
    COMPLETED_REPAIRED = "completed_repaired"
    COMPLETED_IDEMPOTENT_REPLAY = "completed_idempotent_replay"
    FAILED_INPUT_VALIDATION = "failed_input_validation"
    FAILED_NOT_FOUND = "failed_not_found"
    FAILED_FORBIDDEN = "failed_forbidden"
    FAILED_CONFLICT = "failed_conflict"
    FAILED_OUTPUT_VALIDATION = "failed_output_validation"
    FAILED_MODEL_TIMEOUT = "failed_model_timeout"
    FAILED_MODEL_ERROR = "failed_model_error"
    FAILED_PERSISTENCE = "failed_persistence"


class BriefWorkflowOperation(StrEnum):
    """Supported brief workflow execution modes."""

    GENERATE = "generate"
    REVISE = "revise"


BRIEF_SYNTHESIZER_AGENT_NAME = "brief_synthesizer"
BRIEF_REFINER_AGENT_NAME = "brief_refiner"


def brief_specialist_agent_name(operation: BriefWorkflowOperation) -> str:
    """Return the name of the specialist agent that serves ``operation``."""
    if operation is BriefWorkflowOperation.GENERATE:
        return BRIEF_SYNTHESIZER_AGENT_NAME
    return BRIEF_REFINER_AGENT_NAME
