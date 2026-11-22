"""Core domain entities and value objects for Brew (pure Pydantic v2, zero SDK dependencies)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.errors import ConflictError, DomainValidationError
from app.domain.types import (
    AgendaDescriptionText,
    AgendaTitleText,
    ConsentStatus,
    ContextSummaryText,
    EntityId,
    FollowUpTopicText,
    MeetingDurationMinutes,
    MeetingNotesText,
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryBodyText,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ObjectiveText,
    OpenerText,
    OrganizationNameText,
    ProposalStatus,
    QuestionPromptText,
    RationaleText,
    ShortLabelText,
    ShortTagText,
    SourceExcerptText,
    UtcDatetime,
    VersionNumber,
)


class _ImmutableDomainModel(BaseModel):
    """Base configuration for immutable, strictly validated domain models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class AuthenticatedPrincipal(_ImmutableDomainModel):
    """Authenticated caller identity resolved by the authentication port."""

    user_id: EntityId
    display_name: ShortLabelText | None = None


class UserPreferences(_ImmutableDomainModel):
    """User-level coaching and preparation defaults."""

    id: EntityId
    owner_user_id: EntityId
    default_tone: MeetingTone = MeetingTone.WARM_CASUAL
    default_duration_minutes: MeetingDurationMinutes = 30
    preferred_question_count: Annotated[int, Field(ge=1, le=15)] = 4
    communication_style_notes: MemoryBodyText | None = None
    focus_areas: list[ShortTagText] = Field(default_factory=list, max_length=10)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self


class Contact(_ImmutableDomainModel):
    """Counterpart profile owned by an authenticated Brew user."""

    id: EntityId
    owner_user_id: EntityId
    name: ShortLabelText
    title: ShortLabelText | None = None
    role: ShortLabelText | None = None
    organization: OrganizationNameText | None = None
    context_notes: ContextSummaryText | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self


class Meeting(_ImmutableDomainModel):
    """Scheduled or planned conversation between a user and a contact."""

    id: EntityId
    owner_user_id: EntityId
    contact_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone = MeetingTone.WARM_CASUAL
    objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    notes: MeetingNotesText | None = None
    status: MeetingStatus = MeetingStatus.PREPARING
    latest_brief_id: EntityId | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self


class TimeBoxedAgendaItem(_ImmutableDomainModel):
    """Single time-allocated segment within a preparation brief's agenda."""

    title: AgendaTitleText
    duration_minutes: Annotated[int, Field(ge=1, le=180)]
    description: AgendaDescriptionText


class ConversationQuestion(_ImmutableDomainModel):
    """Suggested question paired with its coaching rationale."""

    id: EntityId
    question: QuestionPromptText
    rationale: RationaleText
    category: ShortTagText | None = None


class PreparationBrief(_ImmutableDomainModel):
    """Versioned, time-boxed preparation brief for a meeting."""

    id: EntityId
    owner_user_id: EntityId
    meeting_id: EntityId
    contact_id: EntityId
    duration_minutes: MeetingDurationMinutes
    tone: MeetingTone
    contact_context: ContextSummaryText
    meeting_objective: ObjectiveText
    conversation_openers: list[OpenerText] = Field(min_length=1, max_length=10)
    time_boxed_agenda: list[TimeBoxedAgendaItem] = Field(min_length=1, max_length=12)
    suggested_questions: list[ConversationQuestion] = Field(min_length=1, max_length=15)
    suggested_follow_up_topics: list[FollowUpTopicText] = Field(min_length=1, max_length=10)
    referenced_memory_ids: list[EntityId] = Field(default_factory=list, max_length=50)
    revision_summary: MemoryBodyText | None = None
    version: VersionNumber = 1
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_brief_invariants(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)

        allocated_total = sum(segment.duration_minutes for segment in self.time_boxed_agenda)
        if allocated_total != self.duration_minutes:
            msg = (
                f"Time-boxed agenda segments must sum to {self.duration_minutes} minutes, "
                f"got {allocated_total} minutes."
            )
            raise ValueError(msg)

        question_ids = [item.id for item in self.suggested_questions]
        if len(set(question_ids)) != len(question_ids):
            msg = "Suggested questions must have unique IDs within a brief."
            raise ValueError(msg)

        return self


class MemorySource(_ImmutableDomainModel):
    """Provenance and source reference for a proposed or approved memory."""

    source_type: MemorySourceType
    meeting_id: EntityId | None = None
    brief_id: EntityId | None = None
    proposal_id: EntityId | None = None
    excerpt: SourceExcerptText | None = None
    recorded_at: UtcDatetime


def _validate_memory_scope_contact_binding(
    scope: MemoryScope,
    contact_id: str | None,
) -> None:
    if scope is MemoryScope.CONTACT and contact_id is None:
        msg = "contact_id is required when scope is 'contact'."
        raise ValueError(msg)
    if scope is MemoryScope.USER_PREFERENCE and contact_id is not None:
        msg = "contact_id must be omitted when scope is 'user_preference'."
        raise ValueError(msg)


class MemoryProposal(_ImmutableDomainModel):
    """Candidate memory staged separately from approved memories pending user consent."""

    id: EntityId
    owner_user_id: EntityId
    scope: MemoryScope
    contact_id: EntityId | None = None
    memory_type: MemoryType
    text: MemoryBodyText
    rationale: RationaleText
    source: MemorySource
    status: ProposalStatus = ProposalStatus.PENDING
    approved_memory_id: EntityId | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    reviewed_at: UtcDatetime | None = None
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_proposal_invariants(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)

        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)

        if self.status is ProposalStatus.PENDING:
            if self.approved_memory_id is not None:
                msg = "Pending proposals cannot reference an approved_memory_id."
                raise ValueError(msg)
            if self.reviewed_at is not None:
                msg = "Pending proposals cannot have a reviewed_at timestamp."
                raise ValueError(msg)
        elif self.status is ProposalStatus.APPROVED:
            if self.approved_memory_id is None:
                msg = "Approved proposals must record approved_memory_id."
                raise ValueError(msg)
            if self.reviewed_at is None:
                msg = "Approved proposals must record reviewed_at."
                raise ValueError(msg)
            if self.reviewed_at < self.created_at:
                msg = "reviewed_at cannot be earlier than created_at."
                raise ValueError(msg)
        elif self.status is ProposalStatus.REJECTED:
            if self.approved_memory_id is not None:
                msg = "Rejected proposals cannot reference an approved_memory_id."
                raise ValueError(msg)
            if self.reviewed_at is None:
                msg = "Rejected proposals must record reviewed_at."
                raise ValueError(msg)
            if self.reviewed_at < self.created_at:
                msg = "reviewed_at cannot be earlier than created_at."
                raise ValueError(msg)

        return self

    def mark_approved(
        self,
        *,
        approved_memory_id: str,
        reviewed_at: datetime,
    ) -> MemoryProposal:
        """Transition a pending proposal to APPROVED and increment its version."""
        if self.status is not ProposalStatus.PENDING:
            raise ConflictError(
                f"Memory proposal '{self.id}' cannot be approved because its status is "
                f"'{self.status.value}'.",
                code="PROPOSAL_NOT_PENDING",
            )
        return MemoryProposal(
            id=self.id,
            owner_user_id=self.owner_user_id,
            scope=self.scope,
            contact_id=self.contact_id,
            memory_type=self.memory_type,
            text=self.text,
            rationale=self.rationale,
            source=self.source,
            status=ProposalStatus.APPROVED,
            approved_memory_id=approved_memory_id,
            created_at=self.created_at,
            updated_at=reviewed_at,
            reviewed_at=reviewed_at,
            version=self.version + 1,
        )


class Memory(_ImmutableDomainModel):
    """Durable, user-consented memory stored separately from unapproved proposals."""

    id: EntityId
    owner_user_id: EntityId
    scope: MemoryScope
    contact_id: EntityId | None = None
    memory_type: MemoryType
    text: MemoryBodyText
    source: MemorySource
    consent_status: ConsentStatus = ConsentStatus.APPROVED
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_memory_invariants(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)

        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self

    def apply_update(
        self,
        *,
        text: str | None = None,
        memory_type: MemoryType | None = None,
        consent_status: ConsentStatus | None = None,
        updated_at: datetime,
    ) -> Memory:
        """Apply partial updates to an approved memory and increment its version."""
        if text is None and memory_type is None and consent_status is None:
            raise DomainValidationError(
                "At least one of 'text', 'memory_type', or 'consent_status' must be provided."
            )
        return Memory(
            id=self.id,
            owner_user_id=self.owner_user_id,
            scope=self.scope,
            contact_id=self.contact_id,
            memory_type=memory_type if memory_type is not None else self.memory_type,
            text=text if text is not None else self.text,
            source=self.source,
            consent_status=(consent_status if consent_status is not None else self.consent_status),
            created_at=self.created_at,
            updated_at=updated_at,
            version=self.version + 1,
        )
