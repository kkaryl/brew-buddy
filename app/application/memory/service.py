"""Memory facade combining retrieval and persistence behind one service."""

from __future__ import annotations

from app.application.memory.persistence import MemoryPersistenceService
from app.application.memory.proposals import MemoryProposalBatchResult
from app.application.memory.retrieval import MemoryRetrievalService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.memory.models import Memory, MemoryProposal
from app.domain.memory.types import (
    ConsentStatus,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)


class MemoryService:
    """Cohesive facade combining ``MemoryRetrievalService`` and ``MemoryPersistenceService``."""

    def __init__(
        self,
        *,
        retrieval: MemoryRetrievalService,
        persistence: MemoryPersistenceService,
    ) -> None:
        self._retrieval = retrieval
        self._persistence = persistence

    @property
    def retrieval(self) -> MemoryRetrievalService:
        return self._retrieval

    @property
    def persistence(self) -> MemoryPersistenceService:
        return self._persistence

    async def propose_memories_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> MemoryProposalBatchResult:
        return await self._persistence.propose_memories_batch(
            principal=principal,
            notes=notes,
            source_type=source_type,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

    async def propose_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> list[MemoryProposal]:
        return await self._persistence.propose_memories(
            principal=principal,
            notes=notes,
            source_type=source_type,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

    async def list_proposals(
        self,
        *,
        principal: AuthenticatedPrincipal,
        status: ProposalStatus | None = None,
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        return await self._persistence.list_proposals(
            principal=principal,
            status=status,
            contact_id=contact_id,
        )

    async def approve_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None = None,
        memory_type: MemoryType | None = None,
        supersedes_memory_id: str | None = None,
    ) -> Memory:
        return await self._persistence.approve_proposal(
            principal=principal,
            proposal_id=proposal_id,
            expected_version=expected_version,
            edited_text=edited_text,
            memory_type=memory_type,
            supersedes_memory_id=supersedes_memory_id,
        )

    async def reject_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int = 1,
        reason: str | None = None,
    ) -> MemoryProposal:
        return await self._persistence.reject_proposal(
            principal=principal,
            proposal_id=proposal_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def list_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
        include_superseded: bool = False,
    ) -> list[Memory]:
        return await self._retrieval.list_memories(
            principal=principal,
            scope=scope,
            contact_id=contact_id,
            memory_type=memory_type,
            include_revoked=include_revoked,
            include_superseded=include_superseded,
        )

    async def update_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int,
        text: str | None = None,
        memory_type: MemoryType | None = None,
        consent_status: ConsentStatus | None = None,
    ) -> Memory:
        return await self._persistence.update_memory(
            principal=principal,
            memory_id=memory_id,
            expected_version=expected_version,
            text=text,
            memory_type=memory_type,
            consent_status=consent_status,
        )

    async def delete_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int | None = None,
    ) -> None:
        await self._persistence.delete_memory(
            principal=principal,
            memory_id=memory_id,
            expected_version=expected_version,
        )
