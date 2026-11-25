"""Input and output contracts for the conversation_coach tools."""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.meetings.types import MeetingPurpose
from app.domain.memory.types import MemorySourceType
from app.domain.shared.types import EntityId

ToolStatus = Literal["success", "empty", "error"]
ToolErrorCode = Literal[
    "VALIDATION_ERROR",
    "AUTHENTICATION_REQUIRED",
    "IDENTITY_OVERRIDE_FORBIDDEN",
    "FORBIDDEN",
    "NOT_FOUND",
    "TIMEOUT",
    "SERVICE_UNAVAILABLE",
]
UntrustedDataTag = Literal["untrusted_user_data"]

APPROVAL_NOTICE = (
    "Candidates are staged as pending proposals only and require explicit user "
    "approval before becoming durable memories."
)


# ---------------------------------------------------------------------------
# TypedDict return schemas (JSON-serializable dicts + Vertex AI JSON Schema)
# ---------------------------------------------------------------------------


class ToolErrorDict(TypedDict):
    """Structured, recoverable error payload returned to the LLM."""

    code: ToolErrorCode
    message: str
    retryable: bool
    recovery_instruction: str


class MemorySummaryDict(TypedDict):
    """Minimal approved memory projection returned by coaching tools."""

    memory_id: str
    memory_type: str
    text: str


class UserPreferencesDataDict(TypedDict):
    """Typed successful/empty data payload for ``get_user_preferences``."""

    has_saved_preferences: bool
    default_tone: str | None
    default_duration_minutes: int | None
    preferred_question_count: int | None
    communication_style_notes: str | None
    focus_areas: list[str]
    approved_preference_memories: list[MemorySummaryDict]
    was_truncated: bool
    injection_detected: bool
    data_trust_level: UntrustedDataTag


class GetUserPreferencesResponseDict(TypedDict):
    """Top-level output contract for ``get_user_preferences``."""

    status: ToolStatus
    data: UserPreferencesDataDict | None
    error: ToolErrorDict | None


class ContactContextDataDict(TypedDict):
    """Typed successful data payload for ``get_contact_context``."""

    contact_id: str
    name: str
    title: str | None
    role: str | None
    organization: str | None
    context_notes: str | None
    approved_memories: list[MemorySummaryDict]
    has_prior_context: bool
    was_truncated: bool
    injection_detected: bool
    data_trust_level: UntrustedDataTag


class GetContactContextResponseDict(TypedDict):
    """Top-level output contract for ``get_contact_context``."""

    status: ToolStatus
    data: ContactContextDataDict | None
    error: ToolErrorDict | None


class MeetingHistoryItemDict(TypedDict):
    """Minimal meeting summary returned by ``get_meeting_history``."""

    meeting_id: str
    contact_id: str
    purpose: str
    tone: str
    objective: str
    duration_minutes: int
    status: str
    scheduled_at_utc: str | None
    notes_excerpt: str | None


class MeetingHistoryDataDict(TypedDict):
    """Typed successful/empty data payload for ``get_meeting_history``."""

    meetings: list[MeetingHistoryItemDict]
    total_returned: int
    was_truncated: bool
    injection_detected: bool
    data_trust_level: UntrustedDataTag


class GetMeetingHistoryResponseDict(TypedDict):
    """Top-level output contract for ``get_meeting_history``."""

    status: ToolStatus
    data: MeetingHistoryDataDict | None
    error: ToolErrorDict | None


class SuggestedMemoryCandidateDict(TypedDict):
    """Minimal pending memory candidate summary returned by ``suggest_memory_candidates``."""

    proposal_id: str
    scope: str
    contact_id: str | None
    memory_type: str
    text: str
    rationale: str
    status: Literal["pending"]
    requires_user_approval: bool


class SuggestMemoryCandidatesDataDict(TypedDict):
    """Typed successful/empty data payload for ``suggest_memory_candidates``."""

    candidates: list[SuggestedMemoryCandidateDict]
    total_suggested: int
    filtered_untrusted_directives: int
    approval_notice: str
    data_trust_level: UntrustedDataTag


class SuggestMemoryCandidatesResponseDict(TypedDict):
    """Top-level output contract for ``suggest_memory_candidates``."""

    status: ToolStatus
    data: SuggestMemoryCandidatesDataDict | None
    error: ToolErrorDict | None


# ---------------------------------------------------------------------------
# Strict Pydantic v2 Input & Output Contracts
# ---------------------------------------------------------------------------


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class GetUserPreferencesInput(_StrictContractModel):
    """Validated input contract for ``get_user_preferences``."""

    max_preference_memories: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of approved user-preference memories to return (1 to 10).",
    )


class GetContactContextInput(_StrictContractModel):
    """Validated input contract for ``get_contact_context``."""

    contact_id: EntityId = Field(
        description="Saved contact identifier owned by the authenticated user (e.g. 'cnt_...')."
    )
    meeting_objective: str | None = Field(
        default=None,
        max_length=500,
        description="Optional current meeting objective used to rank relevant contact memories.",
    )
    max_memories: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of approved contact memories to return (1 to 10).",
    )

    @field_validator("meeting_objective")
    @classmethod
    def _clean_optional_objective(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class GetMeetingHistoryInput(_StrictContractModel):
    """Validated input contract for ``get_meeting_history``."""

    contact_id: EntityId | None = Field(
        default=None,
        description="Optional saved contact identifier ('cnt_...') to scope meeting history.",
    )
    purpose: MeetingPurpose | None = Field(
        default=None,
        description="Optional meeting purpose filter/boost for relevance ranking.",
    )
    objective_hint: str | None = Field(
        default=None,
        max_length=500,
        description="Optional topic or objective keywords to prioritize relevant past meetings.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of recent non-cancelled meetings to return (1 to 10).",
    )

    @field_validator("contact_id", mode="before")
    @classmethod
    def _normalize_blank_contact_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("objective_hint")
    @classmethod
    def _clean_optional_hint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SuggestMemoryCandidatesInput(_StrictContractModel):
    """Validated input contract for ``suggest_memory_candidates``."""

    notes: str = Field(
        min_length=5,
        max_length=5000,
        description="Raw meeting notes or explicit preference takeaways (5 to 5000 chars).",
    )
    contact_id: EntityId | None = Field(
        default=None,
        description="Optional saved contact identifier ('cnt_...') associated with the notes.",
    )
    meeting_id: EntityId | None = Field(
        default=None,
        description="Optional saved meeting identifier ('mtg_...') associated with the notes.",
    )
    source_type: MemorySourceType = Field(
        default=MemorySourceType.MEETING_NOTES,
        description=(
            "Workflow source of the notes "
            "('meeting_notes', 'brief_refinement', or 'direct_user_input')."
        ),
    )
    max_candidates: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of candidate memory proposals to stage (1 to 10).",
    )

    @field_validator("notes")
    @classmethod
    def _validate_notes_non_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            msg = "notes must contain at least 5 non-whitespace characters."
            raise ValueError(msg)
        return cleaned

    @field_validator("contact_id", "meeting_id", mode="before")
    @classmethod
    def _normalize_blank_optional_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ToolErrorDetail(_StrictContractModel):
    """Validated structured error model returned on recoverable tool failures."""

    code: ToolErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool
    recovery_instruction: str = Field(min_length=1, max_length=600)


class MemorySummaryOutput(_StrictContractModel):
    memory_id: EntityId
    memory_type: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1000)


class UserPreferencesDataOutput(_StrictContractModel):
    has_saved_preferences: bool
    default_tone: str | None = None
    default_duration_minutes: int | None = None
    preferred_question_count: int | None = None
    communication_style_notes: str | None = None
    focus_areas: list[str] = Field(default_factory=list)
    approved_preference_memories: list[MemorySummaryOutput] = Field(default_factory=list)
    was_truncated: bool = False
    injection_detected: bool = False
    data_trust_level: UntrustedDataTag = "untrusted_user_data"


class GetUserPreferencesOutput(_StrictContractModel):
    status: ToolStatus
    data: UserPreferencesDataOutput | None = None
    error: ToolErrorDetail | None = None


class ContactContextDataOutput(_StrictContractModel):
    contact_id: EntityId
    name: str = Field(min_length=1, max_length=120)
    title: str | None = None
    role: str | None = None
    organization: str | None = None
    context_notes: str | None = None
    approved_memories: list[MemorySummaryOutput] = Field(default_factory=list)
    has_prior_context: bool
    was_truncated: bool = False
    injection_detected: bool = False
    data_trust_level: UntrustedDataTag = "untrusted_user_data"


class GetContactContextOutput(_StrictContractModel):
    status: ToolStatus
    data: ContactContextDataOutput | None = None
    error: ToolErrorDetail | None = None


class MeetingHistoryItemOutput(_StrictContractModel):
    meeting_id: EntityId
    contact_id: EntityId
    purpose: str
    tone: str
    objective: str
    duration_minutes: int = Field(ge=5, le=180)
    status: str
    scheduled_at_utc: str | None = None
    notes_excerpt: str | None = None


class MeetingHistoryDataOutput(_StrictContractModel):
    meetings: list[MeetingHistoryItemOutput] = Field(default_factory=list)
    total_returned: int = Field(ge=0)
    was_truncated: bool = False
    injection_detected: bool = False
    data_trust_level: UntrustedDataTag = "untrusted_user_data"


class GetMeetingHistoryOutput(_StrictContractModel):
    status: ToolStatus
    data: MeetingHistoryDataOutput | None = None
    error: ToolErrorDetail | None = None


class SuggestedMemoryCandidateOutput(_StrictContractModel):
    proposal_id: EntityId
    scope: str
    contact_id: EntityId | None = None
    memory_type: str
    text: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=500)
    status: Literal["pending"] = "pending"
    requires_user_approval: Literal[True] = True


class SuggestMemoryCandidatesDataOutput(_StrictContractModel):
    candidates: list[SuggestedMemoryCandidateOutput] = Field(default_factory=list)
    total_suggested: int = Field(ge=0)
    filtered_untrusted_directives: int = Field(ge=0)
    approval_notice: str = Field(default=APPROVAL_NOTICE)
    data_trust_level: UntrustedDataTag = "untrusted_user_data"


class SuggestMemoryCandidatesOutput(_StrictContractModel):
    status: ToolStatus
    data: SuggestMemoryCandidatesDataOutput | None = None
    error: ToolErrorDetail | None = None
