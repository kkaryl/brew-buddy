"""Capability-restricted facades: read-only readers and a pending-only proposal stager."""

from __future__ import annotations

from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactReaderPort
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingReaderPort
from app.domain.memory.models import Memory, MemoryProposal, UserPreferences
from app.domain.memory.ports import (
    ApprovedMemoryReaderPort,
    PendingMemoryProposalStagerPort,
    UserPreferencesReaderPort,
)
from app.domain.memory.types import MemoryScope, MemoryType, ProposalStatus
from app.domain.shared.errors import ConflictError


class ReadOnlyPreferencesFacade:
    """Capability-restricted proxy exposing only ``get_by_owner``."""

    def __init__(self, reader: UserPreferencesReaderPort) -> None:
        self._reader = reader

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        return await self._reader.get_by_owner(owner_user_id)


class ReadOnlyContactFacade:
    """Capability-restricted proxy exposing only owner-scoped contact reads."""

    def __init__(self, reader: ContactReaderPort) -> None:
        self._reader = reader

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        return await self._reader.get_for_owner(owner_user_id, contact_id)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        return await self._reader.exists_for_any_owner(contact_id)


class ReadOnlyMeetingFacade:
    """Capability-restricted proxy exposing only owner-scoped meeting reads."""

    def __init__(self, reader: MeetingReaderPort) -> None:
        self._reader = reader

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        return await self._reader.get_for_owner(owner_user_id, meeting_id)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        return await self._reader.exists_for_any_owner(meeting_id)

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        return await self._reader.list_by_owner(owner_user_id, contact_id=contact_id)


class ReadOnlyApprovedMemoryFacade:
    """Capability-restricted proxy exposing only consented memory listing (no writes/deletes)."""

    def __init__(self, reader: ApprovedMemoryReaderPort) -> None:
        self._reader = reader

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        del include_revoked  # Agent tools may never request revoked memories.
        return await self._reader.list_by_owner(
            owner_user_id,
            scope=scope,
            contact_id=contact_id,
            memory_type=memory_type,
            include_revoked=False,
        )


class PendingProposalOnlyFacade:
    """Capability-restricted proxy allowing only new ``PENDING`` proposal creation."""

    def __init__(self, stager: PendingMemoryProposalStagerPort) -> None:
        self._stager = stager

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        if expected_version is not None or proposal.status is not ProposalStatus.PENDING:
            raise ConflictError(
                "Agent tools may only stage new pending memory proposals.",
                code="AGENT_WRITE_RESTRICTED",
            )
        return await self._stager.save(proposal, expected_version=None)
