"""Memory, proposal, preferences and extraction-job ports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.contacts.models import Contact
from app.domain.meetings.models import Meeting
from app.domain.memory.jobs import MemoryExtractionJob
from app.domain.memory.models import (
    Memory,
    MemoryProposal,
    UserPreferences,
    validate_memory_scope_contact_binding,
)
from app.domain.memory.types import MemoryScope, MemoryType, ProposalStatus
from app.domain.shared.types import EntityId, MemoryBodyText, RationaleText, SourceExcerptText


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
        validate_memory_scope_contact_binding(self.scope, self.contact_id)
        return self


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


class MemoryExtractionJobRepository(Protocol):
    """Async persistence port for background memory-extraction job records."""

    async def get_for_owner(
        self,
        owner_user_id: str,
        job_id: str,
    ) -> MemoryExtractionJob | None:
        """Fetch a job by ID, returning None when it is absent or owned by another user."""

    async def save(self, job: MemoryExtractionJob) -> MemoryExtractionJob:
        """Create or replace the job record at its owner-scoped path."""
