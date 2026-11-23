"""Async domain-specific repository, auth, ID, and agent ports (no generic repository base)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    AuthenticatedPrincipal,
    BriefPreparationContext,
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    PreparationBrief,
    TimeBoxedAgendaItem,
    UserPreferences,
    WorkflowIdempotencyRecord,
    _validate_memory_scope_contact_binding,
)
from app.domain.types import (
    BriefWorkflowOperation,
    ContextSummaryText,
    EntityId,
    FollowUpTopicText,
    MeetingDurationMinutes,
    MeetingTone,
    MemoryBodyText,
    MemoryScope,
    MemoryType,
    ObjectiveText,
    OpenerText,
    ProposalStatus,
    RationaleText,
    SourceExcerptText,
)


class IdGeneratorPort(Protocol):
    """Port generating collision-resistant domain entity identifiers."""

    def new_id(self, prefix: str) -> str:
        """Return a fresh identifier prefixed with ``prefix``."""


class AuthenticatorPort(Protocol):
    """Port verifying bearer credentials and returning the authenticated principal."""

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Validate ``token`` and return the authenticated user or raise ``AuthenticationError``."""


class UserPreferencesRepository(Protocol):
    """Async persistence port for ``users/{uid}/preferences/default``."""

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        """Return preferences for ``owner_user_id``, or ``None`` if not configured."""

    async def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        """Persist new or updated preferences enforcing optimistic version checks."""


class ContactRepository(Protocol):
    """Async persistence port for ``users/{uid}/contacts/{contactId}``."""

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        """Fetch ``contact_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        """Return ``True`` if ``contact_id`` exists under any user partition."""

    async def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        """List contacts belonging to ``owner_user_id`` ordered deterministically."""

    async def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        """Persist a new or updated contact enforcing optimistic version checks."""


class MeetingRepository(Protocol):
    """Async persistence port for ``users/{uid}/meetings/{meetingId}``."""

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        """Fetch ``meeting_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        """Return ``True`` if ``meeting_id`` exists under any user partition."""

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings belonging to ``owner_user_id``, optionally filtered by ``contact_id``."""

    async def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        """Persist a new or updated meeting enforcing optimistic version checks."""


class BriefRepository(Protocol):
    """Async persistence port for ``users/{uid}/briefs/{briefId}``."""

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        """Fetch ``brief_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        """Return ``True`` if ``brief_id`` exists under any user partition."""

    async def list_by_meeting(
        self,
        owner_user_id: str,
        meeting_id: str,
    ) -> list[PreparationBrief]:
        """List preparation briefs owned by ``owner_user_id`` for ``meeting_id``."""

    async def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        """Persist a new or revised brief enforcing optimistic version checks."""

    async def list_revisions(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> list[PreparationBrief]:
        """Return immutable historical revisions of ``brief_id`` ordered by version."""

    async def get_revision(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> PreparationBrief | None:
        """Fetch a specific immutable historical revision of ``brief_id``."""


class MemoryProposalRepository(Protocol):
    """Dedicated async persistence port for ``users/{uid}/memoryProposals/{proposalId}``."""

    async def get_for_owner(
        self,
        owner_user_id: str,
        proposal_id: str,
    ) -> MemoryProposal | None:
        """Fetch ``proposal_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, proposal_id: str) -> bool:
        """Return ``True`` if ``proposal_id`` exists under any user partition."""

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        """List memory proposals belonging to ``owner_user_id``."""

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        """Persist a new or reviewed proposal enforcing optimistic version checks."""


class MemoryRepository(Protocol):
    """Dedicated async persistence port for ``users/{uid}/memories/{memoryId}``."""

    async def get_for_owner(self, owner_user_id: str, memory_id: str) -> Memory | None:
        """Fetch ``memory_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, memory_id: str) -> bool:
        """Return ``True`` if ``memory_id`` exists under any user partition."""

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
        include_superseded: bool = False,
    ) -> list[Memory]:
        """List approved memories belonging to ``owner_user_id`` matching optional filters."""

    async def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        """Persist an approved memory enforcing optimistic version checks."""

    async def delete(
        self,
        owner_user_id: str,
        memory_id: str,
        *,
        expected_version: int | None = None,
        deleted_snapshot: Memory | None = None,
    ) -> None:
        """Delete an approved memory under ``owner_user_id`` enforcing version checks."""

    async def get_deleted_for_owner(
        self,
        owner_user_id: str,
        memory_id: str,
    ) -> Memory | None:
        """Return the archived ``DELETED`` tombstone for ``memory_id``, if any."""


class UserPreferencesReaderPort(Protocol):
    """Least-privilege read-only port exposing only caller-owned user preferences."""

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        """Return saved preferences for ``owner_user_id``, or ``None`` if unset."""


class ContactReaderPort(Protocol):
    """Least-privilege read-only port exposing only caller-owned contact lookups."""

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        """Fetch ``contact_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        """Return ``True`` if ``contact_id`` exists under any user partition."""


class MeetingReaderPort(Protocol):
    """Least-privilege read-only port exposing only caller-owned meeting lookups."""

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        """Fetch ``meeting_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        """Return ``True`` if ``meeting_id`` exists under any user partition."""

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings belonging to ``owner_user_id``, optionally filtered by ``contact_id``."""


class ApprovedMemoryReaderPort(Protocol):
    """Least-privilege read-only port exposing only consented caller-owned memories."""

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        """List approved memories belonging to ``owner_user_id`` matching optional filters."""


class PendingMemoryProposalStagerPort(Protocol):
    """Least-privilege write port restricted exclusively to staging pending proposals."""

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        """Persist a newly staged ``PENDING`` memory proposal."""


class GeneratedBriefContent(BaseModel):
    """Validated structured output returned by the brief coaching agent port."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contact_context: ContextSummaryText
    meeting_objective: ObjectiveText
    conversation_openers: list[OpenerText] = Field(min_length=1, max_length=10)
    time_boxed_agenda: list[TimeBoxedAgendaItem] = Field(min_length=1, max_length=12)
    suggested_questions: list[ConversationQuestion] = Field(min_length=1, max_length=15)
    suggested_follow_up_topics: list[FollowUpTopicText] = Field(min_length=1, max_length=10)
    referenced_memory_ids: list[EntityId] = Field(default_factory=list, max_length=50)
    revision_summary: MemoryBodyText | None = None


class ProposedMemoryCandidate(BaseModel):
    """Validated candidate memory produced by the memory extraction agent port."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: MemoryScope
    contact_id: EntityId | None = None
    memory_type: MemoryType
    text: MemoryBodyText
    rationale: RationaleText
    excerpt: SourceExcerptText | None = None
    supersedes_memory_id: EntityId | None = None

    @model_validator(mode="after")
    def _validate_scope_binding(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)
        return self


class BriefAttemptMetrics(BaseModel):
    """Per-attempt execution telemetry and safeguard budget shared with coach adapters."""

    model_config = ConfigDict(extra="forbid")

    remaining_model_budget: int = Field(default=6, ge=0, le=50)
    max_tool_retries: int = Field(default=1, ge=0, le=5)
    model_invocations: int = Field(default=0, ge=0)
    tool_invocations: int = Field(default=0, ge=0)
    degraded_tools: list[str] = Field(default_factory=list)


class WorkflowIdempotencyRepository(Protocol):
    """Async persistence port for workflow request deduplication records."""

    async def get(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> WorkflowIdempotencyRecord | None:
        """Fetch an existing deduplication record for ``owner_user_id``."""

    async def save(
        self,
        record: WorkflowIdempotencyRecord,
    ) -> WorkflowIdempotencyRecord:
        """Persist a workflow deduplication record."""


class BriefCoachAgentPort(Protocol):
    """Async agent interface synthesizing and revising structured preparation briefs."""

    async def generate_brief(
        self,
        *,
        meeting: Meeting,
        context: BriefPreparationContext,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Synthesize an initial time-boxed brief grounded in ``BriefPreparationContext``."""

    async def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        context: BriefPreparationContext,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Revise an existing preparation brief grounded in ``BriefPreparationContext``."""


class MemoryProposalAgentPort(Protocol):
    """Async agent interface extracting candidate memory proposals from raw session notes."""

    async def propose_memories(
        self,
        *,
        notes: str,
        meeting: Meeting | None,
        contact: Contact | None,
        existing_memories: Sequence[Memory],
    ) -> list[ProposedMemoryCandidate]:
        """Extract candidate memories requiring human-in-the-loop approval."""
