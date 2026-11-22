"""Domain-specific repository, authentication, ID, and agent ports (no generic repository base)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    AuthenticatedPrincipal,
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    PreparationBrief,
    TimeBoxedAgendaItem,
    UserPreferences,
    _validate_memory_scope_contact_binding,
)
from app.domain.types import (
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
    """Persistence port for ``UserPreferences`` records."""

    def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        """Return preferences for ``owner_user_id``, or ``None`` if not configured."""

    def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        """Persist new or updated preferences enforcing optimistic version checks."""


class ContactRepository(Protocol):
    """Persistence port for ``Contact`` entities."""

    def get_by_id(self, contact_id: str) -> Contact | None:
        """Fetch a contact by ID across storage (caller enforces ownership)."""

    def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        """List contacts belonging to ``owner_user_id`` ordered deterministically."""

    def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        """Persist a new or updated contact enforcing optimistic version checks."""


class MeetingRepository(Protocol):
    """Persistence port for ``Meeting`` entities."""

    def get_by_id(self, meeting_id: str) -> Meeting | None:
        """Fetch a meeting by ID across storage (caller enforces ownership)."""

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings belonging to ``owner_user_id``, optionally filtered by ``contact_id``."""

    def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        """Persist a new or updated meeting enforcing optimistic version checks."""


class BriefRepository(Protocol):
    """Persistence port for ``PreparationBrief`` entities."""

    def get_by_id(self, brief_id: str) -> PreparationBrief | None:
        """Fetch a preparation brief by ID (caller enforces ownership)."""

    def list_by_meeting(self, meeting_id: str) -> list[PreparationBrief]:
        """List preparation briefs associated with ``meeting_id``."""

    def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        """Persist a new or revised brief enforcing optimistic version checks."""


class MemoryProposalRepository(Protocol):
    """Dedicated persistence port for unapproved/reviewed ``MemoryProposal`` entities."""

    def get_by_id(self, proposal_id: str) -> MemoryProposal | None:
        """Fetch a memory proposal by ID (caller enforces ownership)."""

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
    ) -> list[MemoryProposal]:
        """List memory proposals belonging to ``owner_user_id``."""

    def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        """Persist a new or reviewed proposal enforcing optimistic version checks."""


class MemoryRepository(Protocol):
    """Dedicated persistence port for user-approved ``Memory`` entities."""

    def get_by_id(self, memory_id: str) -> Memory | None:
        """Fetch an approved memory by ID (caller enforces ownership)."""

    def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        """List approved memories belonging to ``owner_user_id`` matching optional filters."""

    def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        """Persist an approved memory enforcing optimistic version checks."""

    def delete(self, memory_id: str, *, expected_version: int | None = None) -> None:
        """Delete an approved memory enforcing optional optimistic version checks."""


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

    @model_validator(mode="after")
    def _validate_scope_binding(self) -> Self:
        _validate_memory_scope_contact_binding(self.scope, self.contact_id)
        return self


class BriefCoachAgentPort(Protocol):
    """Agent interface synthesizing and revising structured meeting preparation briefs."""

    def generate_brief(
        self,
        *,
        meeting: Meeting,
        contact: Contact,
        user_preferences: UserPreferences | None,
        approved_memories: Sequence[Memory],
    ) -> GeneratedBriefContent:
        """Synthesize an initial time-boxed preparation brief grounded in inputs and memories."""

    def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        contact: Contact,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        user_preferences: UserPreferences | None,
        approved_memories: Sequence[Memory],
    ) -> GeneratedBriefContent:
        """Revise an existing preparation brief according to natural-language instructions."""


class MemoryProposalAgentPort(Protocol):
    """Agent interface extracting candidate memory proposals from raw session notes."""

    def propose_memories(
        self,
        *,
        notes: str,
        meeting: Meeting | None,
        contact: Contact | None,
        existing_memories: Sequence[Memory],
    ) -> list[ProposedMemoryCandidate]:
        """Extract candidate memories requiring human-in-the-loop approval."""
