"""User preferences, memory provenance, staged proposals and approved memories."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import Field, model_validator

from app.domain.meetings.types import MeetingTone
from app.domain.memory.types import (
    ConsentStatus,
    MemoryEpistemicStatus,
    MemoryLifecycleState,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.errors import ConflictError, DomainValidationError
from app.domain.shared.types import (
    EntityId,
    MeetingDurationMinutes,
    MemoryBodyText,
    RationaleText,
    ShortLabelText,
    ShortTagText,
    SourceExcerptText,
    UtcDatetime,
    VersionNumber,
)


class UserPreferences(ImmutableDomainModel):
    """User-level coaching and preparation defaults."""

    id: EntityId
    owner_user_id: EntityId
    preferred_display_name: ShortLabelText | None = None
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


class MemorySource(ImmutableDomainModel):
    """Provenance and source reference for a proposed or approved memory."""

    source_type: MemorySourceType
    meeting_id: EntityId | None = None
    brief_id: EntityId | None = None
    proposal_id: EntityId | None = None
    excerpt: SourceExcerptText | None = None
    recorded_at: UtcDatetime


def validate_memory_scope_contact_binding(
    scope: MemoryScope,
    contact_id: str | None,
) -> None:
    if scope is MemoryScope.CONTACT and contact_id is None:
        msg = "contact_id is required when scope is 'contact'."
        raise ValueError(msg)
    if scope is MemoryScope.USER_PREFERENCE and contact_id is not None:
        msg = "contact_id must be omitted when scope is 'user_preference'."
        raise ValueError(msg)


class MemoryProposal(ImmutableDomainModel):
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
        validate_memory_scope_contact_binding(self.scope, self.contact_id)

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


class Memory(ImmutableDomainModel):
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
        validate_memory_scope_contact_binding(self.scope, self.contact_id)

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
