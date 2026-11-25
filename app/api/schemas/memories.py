"""HTTP request and response contracts for memory proposals and approved memories."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from app.api.schemas.base import ResponseModel, StrictRequestModel
from app.domain.memory.models import Memory, MemoryProposal, MemorySource
from app.domain.memory.types import (
    ConsentStatus,
    MemoryEpistemicStatus,
    MemoryLifecycleState,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
    RawSessionNotesText,
)
from app.domain.shared.types import EntityId, MemoryBodyText, SourceExcerptText, VersionNumber


class MemorySourceResponse(ResponseModel):
    """Serialized ``MemorySource`` provenance reference."""

    source_type: MemorySourceType = Field(description="Originating workflow stage.")
    meeting_id: str | None = Field(default=None, description="Originating meeting ID, if any.")
    brief_id: str | None = Field(default=None, description="Originating brief ID, if any.")
    proposal_id: str | None = Field(
        default=None,
        description="Originating memory proposal ID once approved.",
    )
    excerpt: str | None = Field(default=None, description="PII-scrubbed source excerpt.")
    recorded_at: datetime = Field(description="UTC timestamp when provenance was recorded.")

    @classmethod
    def from_domain(cls, source: MemorySource) -> MemorySourceResponse:
        return cls(
            source_type=source.source_type,
            meeting_id=source.meeting_id,
            brief_id=source.brief_id,
            proposal_id=source.proposal_id,
            excerpt=source.excerpt,
            recorded_at=source.recorded_at,
        )


class ProposeMemoriesRequest(StrictRequestModel):
    """Request payload for ``POST /api/v1/memories/propose``."""

    notes: RawSessionNotesText = Field(
        description="Post-meeting notes or session reflections used to propose memories.",
    )
    source_type: MemorySourceType = Field(
        default=MemorySourceType.MEETING_NOTES,
        description="Provenance source type.",
    )
    meeting_id: EntityId | None = Field(
        default=None,
        description="Optional meeting ID associated with the notes.",
    )
    contact_id: EntityId | None = Field(
        default=None,
        description="Optional contact ID associated with the notes.",
    )
    brief_id: EntityId | None = Field(
        default=None,
        description="Optional preparation brief ID associated with the notes.",
    )


class MemoryProposalResponse(ResponseModel):
    """Serialized ``MemoryProposal`` staged in the separate proposal store."""

    id: str = Field(description="Unique memory proposal identifier.")
    scope: MemoryScope = Field(description="Target memory scope.")
    contact_id: str | None = Field(
        default=None,
        description="Related contact ID when scope is 'contact'.",
    )
    memory_type: MemoryType = Field(description="Semantic classification of the memory.")
    text: str = Field(description="Proposed memory statement.")
    rationale: str = Field(description="Why Brew proposed saving this memory.")
    source: MemorySourceResponse = Field(description="Provenance reference.")
    status: ProposalStatus = Field(description="Current review status.")
    lifecycle_state: MemoryLifecycleState = Field(
        description=(
            "Canonical 5-state memory lifecycle status ('proposed', 'approved', 'rejected')."
        ),
    )
    epistemic_status: MemoryEpistemicStatus = Field(
        description="Epistemic framing indicating session-attributed context, not world fact.",
    )
    supersedes_memory_id: str | None = Field(
        default=None,
        description="Existing active memory ID this proposal updates or contradicts, if any.",
    )
    conflict_summary: str | None = Field(
        default=None,
        description="Human-readable explanation when resolving an update or contradiction.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Optional user-supplied reason recorded when rejected.",
    )
    approved_memory_id: str | None = Field(
        default=None,
        description="ID of the approved Memory record once approved.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")
    reviewed_at: datetime | None = Field(
        default=None,
        description="UTC review timestamp once approved or rejected.",
    )
    version: int = Field(description="Optimistic concurrency version.")

    @classmethod
    def from_domain(cls, proposal: MemoryProposal) -> MemoryProposalResponse:
        return cls(
            id=proposal.id,
            scope=proposal.scope,
            contact_id=proposal.contact_id,
            memory_type=proposal.memory_type,
            text=proposal.text,
            rationale=proposal.rationale,
            source=MemorySourceResponse.from_domain(proposal.source),
            status=proposal.status,
            lifecycle_state=proposal.lifecycle_state,
            epistemic_status=proposal.epistemic_status,
            supersedes_memory_id=proposal.supersedes_memory_id,
            conflict_summary=proposal.conflict_summary,
            rejection_reason=proposal.rejection_reason,
            approved_memory_id=proposal.approved_memory_id,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            reviewed_at=proposal.reviewed_at,
            version=proposal.version,
        )


class MemoryProposalBatchResponse(ResponseModel):
    """Response payload for proposing or listing staged memory proposals."""

    proposals: list[MemoryProposalResponse] = Field(
        description="Candidate memory proposals staged for or reviewed by the user.",
    )
    total: int = Field(ge=0, description="Number of proposals returned.")
    skipped_duplicates: int = Field(
        default=0,
        ge=0,
        description="Candidate items skipped because an equivalent active memory already exists.",
    )
    filtered_sensitive_count: int = Field(
        default=0,
        ge=0,
        description="Note clauses rejected as sensitive or speculative third-party assumptions.",
    )


class ApproveMemoryProposalRequest(StrictRequestModel):
    """Request payload for ``POST /api/v1/memories/{id}/approve``."""

    expected_version: VersionNumber = Field(
        default=1,
        description="Expected version of the pending memory proposal.",
    )
    edited_text: MemoryBodyText | None = Field(
        default=None,
        description="Optional user-edited memory text to persist upon approval.",
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Optional overridden memory classification.",
    )
    supersedes_memory_id: EntityId | None = Field(
        default=None,
        description="Optional existing active memory ID explicitly superseded by this approval.",
    )


class RejectMemoryProposalRequest(StrictRequestModel):
    """Request payload for ``POST /api/v1/memories/{id}/reject``."""

    expected_version: VersionNumber = Field(
        default=1,
        description="Expected version of the pending memory proposal.",
    )
    reason: SourceExcerptText | None = Field(
        default=None,
        description="Optional user reason for rejecting the candidate memory.",
    )


class UpdateMemoryRequest(StrictRequestModel):
    """Request payload for ``PATCH /api/v1/memories/{id}``."""

    expected_version: VersionNumber = Field(
        description="Current memory version expected by caller for optimistic concurrency.",
    )
    text: MemoryBodyText | None = Field(
        default=None,
        description="Updated memory text.",
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Updated memory type.",
    )
    consent_status: ConsentStatus | None = Field(
        default=None,
        description="Updated user consent status (e.g. 'revoked').",
    )

    @model_validator(mode="after")
    def _ensure_at_least_one_patch_field(self) -> Self:
        if self.text is None and self.memory_type is None and self.consent_status is None:
            msg = "At least one of 'text', 'memory_type', or 'consent_status' must be provided."
            raise ValueError(msg)
        return self


class MemoryResponse(ResponseModel):
    """Serialized user-approved ``Memory``."""

    id: str = Field(description="Unique approved memory identifier.")
    owner_user_id: str = Field(description="Authenticated owner user identifier.")
    scope: MemoryScope = Field(description="Scope ('user_preference' or 'contact').")
    contact_id: str | None = Field(
        default=None,
        description="Related contact ID when scope is 'contact'.",
    )
    memory_type: MemoryType = Field(description="Semantic memory type.")
    text: str = Field(description="Approved memory text.")
    source: MemorySourceResponse = Field(description="Provenance / source reference.")
    consent_status: ConsentStatus = Field(description="User consent status.")
    lifecycle_state: MemoryLifecycleState = Field(
        description="Canonical lifecycle state ('approved' or 'superseded').",
    )
    epistemic_status: MemoryEpistemicStatus = Field(
        description="Epistemic framing indicating session-attributed context, not world fact.",
    )
    supersedes_memory_id: str | None = Field(
        default=None,
        description="Prior memory ID superseded by this memory, if any.",
    )
    superseded_by_memory_id: str | None = Field(
        default=None,
        description="Newer memory ID that superseded this memory, if superseded.",
    )
    superseded_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when this memory was superseded.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")
    version: int = Field(description="Optimistic concurrency version.")

    @classmethod
    def from_domain(cls, memory: Memory) -> MemoryResponse:
        return cls(
            id=memory.id,
            owner_user_id=memory.owner_user_id,
            scope=memory.scope,
            contact_id=memory.contact_id,
            memory_type=memory.memory_type,
            text=memory.text,
            source=MemorySourceResponse.from_domain(memory.source),
            consent_status=memory.consent_status,
            lifecycle_state=memory.lifecycle_state,
            epistemic_status=memory.epistemic_status,
            supersedes_memory_id=memory.supersedes_memory_id,
            superseded_by_memory_id=memory.superseded_by_memory_id,
            superseded_at=memory.superseded_at,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            version=memory.version,
        )


class MemoryListResponse(ResponseModel):
    """Collection response for ``GET /api/v1/memories``."""

    items: list[MemoryResponse] = Field(description="Approved memories matching query filters.")
    total: int = Field(ge=0, description="Total number of approved memories returned.")
