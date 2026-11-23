"""Core domain entities and value objects for Brew (pure Pydantic v2, zero SDK dependencies)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.errors import ConflictError, DomainValidationError
from app.domain.types import (
    AgendaDescriptionText,
    AgendaTitleText,
    BriefWorkflowOperation,
    BriefWorkflowTerminalState,
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
    MemoryEpistemicStatus,
    MemoryLifecycleState,
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
    preferred_question_count: Annotated[int, Field(ge=1, le=15)] = 6
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
    epistemic_status: MemoryEpistemicStatus = MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
    supersedes_memory_id: EntityId | None = None
    conflict_summary: SourceExcerptText | None = None
    rejection_reason: SourceExcerptText | None = None
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
            if self.rejection_reason is not None:
                msg = "Pending proposals cannot have a rejection_reason."
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
            if self.rejection_reason is not None:
                msg = "Approved proposals cannot have a rejection_reason."
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

    @property
    def lifecycle_state(self) -> MemoryLifecycleState:
        """Return canonical 5-state ``MemoryLifecycleState`` for this proposal."""
        if self.status is ProposalStatus.PENDING:
            return MemoryLifecycleState.PROPOSED
        if self.status is ProposalStatus.APPROVED:
            return MemoryLifecycleState.APPROVED
        return MemoryLifecycleState.REJECTED

    def mark_approved(
        self,
        *,
        approved_memory_id: str,
        reviewed_at: datetime,
        supersedes_memory_id: str | None = None,
    ) -> MemoryProposal:
        """Transition a pending proposal to APPROVED and increment its version."""
        if self.status is not ProposalStatus.PENDING:
            raise ConflictError(
                f"Memory proposal '{self.id}' cannot be approved because its status is "
                f"'{self.status.value}'.",
                code="PROPOSAL_NOT_PENDING",
            )
        resolved_ts = max(reviewed_at, self.created_at)
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
            epistemic_status=self.epistemic_status,
            supersedes_memory_id=(
                supersedes_memory_id
                if supersedes_memory_id is not None
                else self.supersedes_memory_id
            ),
            conflict_summary=self.conflict_summary,
            rejection_reason=None,
            approved_memory_id=approved_memory_id,
            created_at=self.created_at,
            updated_at=resolved_ts,
            reviewed_at=resolved_ts,
            version=self.version + 1,
        )

    def mark_rejected(
        self,
        *,
        reviewed_at: datetime,
        rejection_reason: str | None = None,
    ) -> MemoryProposal:
        """Transition a pending proposal to REJECTED without creating an active memory."""
        if self.status is not ProposalStatus.PENDING:
            raise ConflictError(
                f"Memory proposal '{self.id}' cannot be rejected because its status is "
                f"'{self.status.value}'.",
                code="PROPOSAL_NOT_PENDING",
            )
        resolved_ts = max(reviewed_at, self.created_at)
        return MemoryProposal(
            id=self.id,
            owner_user_id=self.owner_user_id,
            scope=self.scope,
            contact_id=self.contact_id,
            memory_type=self.memory_type,
            text=self.text,
            rationale=self.rationale,
            source=self.source,
            status=ProposalStatus.REJECTED,
            epistemic_status=self.epistemic_status,
            supersedes_memory_id=self.supersedes_memory_id,
            conflict_summary=self.conflict_summary,
            rejection_reason=rejection_reason,
            approved_memory_id=None,
            created_at=self.created_at,
            updated_at=resolved_ts,
            reviewed_at=resolved_ts,
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
    lifecycle_state: MemoryLifecycleState = MemoryLifecycleState.APPROVED
    epistemic_status: MemoryEpistemicStatus = MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
    supersedes_memory_id: EntityId | None = None
    superseded_by_memory_id: EntityId | None = None
    superseded_at: UtcDatetime | None = None
    deleted_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_memory_invariants(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)

        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)

        if self.lifecycle_state in {MemoryLifecycleState.PROPOSED, MemoryLifecycleState.REJECTED}:
            msg = (
                f"Durable Memory records cannot carry proposal state "
                f"'{self.lifecycle_state.value}'."
            )
            raise ValueError(msg)

        if self.supersedes_memory_id == self.id:
            msg = "Memory cannot supersede itself."
            raise ValueError(msg)

        if self.lifecycle_state is MemoryLifecycleState.APPROVED:
            if self.superseded_by_memory_id is not None or self.superseded_at is not None:
                msg = "Active APPROVED memories cannot set superseded_by_memory_id."
                raise ValueError(msg)
            if self.deleted_at is not None:
                msg = "Active APPROVED memories cannot set deleted_at."
                raise ValueError(msg)
        elif self.lifecycle_state is MemoryLifecycleState.SUPERSEDED:
            if self.superseded_by_memory_id is None:
                msg = "SUPERSEDED memories must record superseded_by_memory_id."
                raise ValueError(msg)
            if self.superseded_by_memory_id == self.id:
                msg = "Memory cannot be superseded by itself."
                raise ValueError(msg)
            if self.superseded_at is None or self.superseded_at < self.created_at:
                msg = "SUPERSEDED memories must record a valid superseded_at >= created_at."
                raise ValueError(msg)
        elif self.lifecycle_state is MemoryLifecycleState.DELETED and (
            self.deleted_at is None or self.deleted_at < self.created_at
        ):
            msg = "DELETED memories must record a valid deleted_at >= created_at."
            raise ValueError(msg)

        return self

    @property
    def is_active(self) -> bool:
        """Return ``True`` only when consented, approved, and neither superseded nor deleted."""
        return (
            self.consent_status is ConsentStatus.APPROVED
            and self.lifecycle_state is MemoryLifecycleState.APPROVED
        )

    def apply_update(
        self,
        *,
        text: str | None = None,
        memory_type: MemoryType | None = None,
        consent_status: ConsentStatus | None = None,
        updated_at: datetime,
    ) -> Memory:
        """Apply partial updates to an approved memory and increment its version."""
        if self.lifecycle_state is not MemoryLifecycleState.APPROVED:
            raise ConflictError(
                f"Memory '{self.id}' cannot be updated because its lifecycle state is "
                f"'{self.lifecycle_state.value}'.",
                code="MEMORY_NOT_ACTIVE",
            )
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
            lifecycle_state=self.lifecycle_state,
            epistemic_status=self.epistemic_status,
            supersedes_memory_id=self.supersedes_memory_id,
            created_at=self.created_at,
            updated_at=max(updated_at, self.created_at),
            version=self.version + 1,
        )

    def mark_superseded(
        self,
        *,
        superseded_by_memory_id: str,
        superseded_at: datetime,
    ) -> Memory:
        """Transition an active memory to SUPERSEDED when replaced by a newer approved memory."""
        if self.lifecycle_state is not MemoryLifecycleState.APPROVED:
            raise ConflictError(
                f"Memory '{self.id}' cannot be superseded because its lifecycle state is "
                f"'{self.lifecycle_state.value}'.",
                code="MEMORY_NOT_ACTIVE",
            )
        resolved_ts = max(superseded_at, self.created_at)
        return Memory(
            id=self.id,
            owner_user_id=self.owner_user_id,
            scope=self.scope,
            contact_id=self.contact_id,
            memory_type=self.memory_type,
            text=self.text,
            source=self.source,
            consent_status=self.consent_status,
            lifecycle_state=MemoryLifecycleState.SUPERSEDED,
            epistemic_status=self.epistemic_status,
            supersedes_memory_id=self.supersedes_memory_id,
            superseded_by_memory_id=superseded_by_memory_id,
            superseded_at=resolved_ts,
            deleted_at=None,
            created_at=self.created_at,
            updated_at=resolved_ts,
            version=self.version + 1,
        )

    def mark_deleted(
        self,
        *,
        deleted_at: datetime,
    ) -> Memory:
        """Transition a memory to DELETED preserving provenance and deletion timestamp."""
        if self.lifecycle_state is MemoryLifecycleState.DELETED:
            raise ConflictError(
                f"Memory '{self.id}' is already deleted.",
                code="MEMORY_ALREADY_DELETED",
            )
        resolved_ts = max(deleted_at, self.created_at)
        return Memory(
            id=self.id,
            owner_user_id=self.owner_user_id,
            scope=self.scope,
            contact_id=self.contact_id,
            memory_type=self.memory_type,
            text=self.text,
            source=self.source,
            consent_status=self.consent_status,
            lifecycle_state=MemoryLifecycleState.DELETED,
            epistemic_status=self.epistemic_status,
            supersedes_memory_id=self.supersedes_memory_id,
            superseded_by_memory_id=self.superseded_by_memory_id,
            superseded_at=self.superseded_at,
            deleted_at=resolved_ts,
            created_at=self.created_at,
            updated_at=resolved_ts,
            version=self.version + 1,
        )


class ContextBudget(_ImmutableDomainModel):
    """Upper bounds enforced when assembling pre-brief context from durable storage."""

    max_recent_meetings: Annotated[int, Field(ge=1, le=20)] = 5
    max_contact_memories: Annotated[int, Field(ge=1, le=30)] = 8
    max_preference_memories: Annotated[int, Field(ge=1, le=20)] = 5
    max_total_chars: Annotated[int, Field(ge=200, le=32000)] = 4000


class RecentMeetingSummary(_ImmutableDomainModel):
    """Bounded summary of a recent relevant meeting with the selected contact."""

    meeting_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone
    objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    status: MeetingStatus
    notes_excerpt: SourceExcerptText | None = None
    updated_at: UtcDatetime


class ProvenanceMemoryItem(_ImmutableDomainModel):
    """Approved memory paired with explicit provenance for grounded brief synthesis."""

    memory_id: EntityId
    scope: MemoryScope
    contact_id: EntityId | None = None
    memory_type: MemoryType
    text: MemoryBodyText
    source: MemorySource
    epistemic_status: MemoryEpistemicStatus = MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_scope_binding(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)
        return self

    @classmethod
    def from_memory(cls, memory: Memory) -> ProvenanceMemoryItem:
        """Project a consented active ``Memory`` entity into a provenance-tagged context item."""
        if not memory.is_active:
            raise DomainValidationError(
                f"Cannot include inactive memory '{memory.id}' "
                f"(lifecycle_state='{memory.lifecycle_state.value}', "
                f"consent_status='{memory.consent_status.value}') in preparation context."
            )
        return cls(
            memory_id=memory.id,
            scope=memory.scope,
            contact_id=memory.contact_id,
            memory_type=memory.memory_type,
            text=memory.text,
            source=memory.source,
            epistemic_status=memory.epistemic_status,
            updated_at=memory.updated_at,
        )


class BriefPreparationContext(_ImmutableDomainModel):
    """Bounded, provenance-aware context assembled prior to brief generation or revision."""

    owner_user_id: EntityId
    contact: Contact
    user_preferences: UserPreferences | None = None
    preference_memories: list[ProvenanceMemoryItem] = Field(default_factory=list)
    contact_memories: list[ProvenanceMemoryItem] = Field(default_factory=list)
    recent_meetings: list[RecentMeetingSummary] = Field(default_factory=list)
    budget: ContextBudget = Field(default_factory=ContextBudget)
    total_context_chars: Annotated[int, Field(ge=0)] = 0
    was_truncated: bool = False

    @model_validator(mode="after")
    def _validate_ownership_and_bounds(self) -> Self:
        if self.contact.owner_user_id != self.owner_user_id:
            msg = "Selected contact does not belong to context owner_user_id."
            raise ValueError(msg)

        if (
            self.user_preferences is not None
            and self.user_preferences.owner_user_id != self.owner_user_id
        ):
            msg = "User preferences do not belong to context owner_user_id."
            raise ValueError(msg)

        for pref_item in self.preference_memories:
            if pref_item.scope is not MemoryScope.USER_PREFERENCE:
                msg = "preference_memories may only contain 'user_preference' memories."
                raise ValueError(msg)

        for contact_item in self.contact_memories:
            if contact_item.scope is not MemoryScope.CONTACT:
                msg = "contact_memories may only contain 'contact' memories."
                raise ValueError(msg)
            if contact_item.contact_id != self.contact.id:
                msg = "contact_memories item contact_id does not match selected contact."
                raise ValueError(msg)

        if len(self.recent_meetings) > self.budget.max_recent_meetings:
            msg = "recent_meetings exceeds budget.max_recent_meetings."
            raise ValueError(msg)
        if len(self.contact_memories) > self.budget.max_contact_memories:
            msg = "contact_memories exceeds budget.max_contact_memories."
            raise ValueError(msg)
        if len(self.preference_memories) > self.budget.max_preference_memories:
            msg = "preference_memories exceeds budget.max_preference_memories."
            raise ValueError(msg)
        if self.total_context_chars > self.budget.max_total_chars:
            msg = "total_context_chars exceeds budget.max_total_chars."
            raise ValueError(msg)

        return self

    @property
    def referenced_memory_ids(self) -> list[str]:
        """Return ordered IDs of all approved memories included in this context."""
        return [
            *(item.memory_id for item in self.preference_memories),
            *(item.memory_id for item in self.contact_memories),
        ]


class BriefWorkflowDiagnostics(_ImmutableDomainModel):
    """Structured execution diagnostics and safeguard telemetry for a brief workflow run."""

    request_id: EntityId
    trace_id: EntityId
    operation: BriefWorkflowOperation
    terminal_state: BriefWorkflowTerminalState
    attempt_count: Annotated[int, Field(ge=0, le=5)] = 1
    regeneration_count: Annotated[int, Field(ge=0, le=1)] = 0
    model_invocations: Annotated[int, Field(ge=0, le=50)] = 0
    tool_invocations: Annotated[int, Field(ge=0, le=100)] = 0
    replayed: bool = False
    quality_passed: bool = True
    degraded_sources: list[ShortTagText] = Field(default_factory=list, max_length=20)
    previous_version: VersionNumber | None = None


class BriefWorkflowResult(_ImmutableDomainModel):
    """Structured workflow outcome combining the persisted brief, meeting, and diagnostics."""

    brief: PreparationBrief
    meeting: Meeting
    diagnostics: BriefWorkflowDiagnostics


class WorkflowIdempotencyRecord(_ImmutableDomainModel):
    """Durable deduplication record binding a caller idempotency key to a persisted brief."""

    owner_user_id: EntityId
    operation: BriefWorkflowOperation
    idempotency_key: EntityId
    payload_fingerprint: Annotated[str, Field(min_length=8, max_length=128)]
    brief_id: EntityId
    brief_version: VersionNumber
    meeting_id: EntityId
    created_at: UtcDatetime
