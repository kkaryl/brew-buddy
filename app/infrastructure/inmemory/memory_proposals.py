"""In-memory memory proposal repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.memory.models import MemoryProposal
from app.domain.memory.types import ProposalStatus
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryMemoryProposalRepository:
    """Async fake repository mirroring ``users/{uid}/memoryProposals/{proposalId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, MemoryProposal]] = {}

    async def get_for_owner(
        self,
        owner_user_id: str,
        proposal_id: str,
    ) -> MemoryProposal | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(proposal_id)

    async def exists_for_any_owner(self, proposal_id: str) -> bool:
        async with self._lock:
            return any(proposal_id in user_proposals for user_proposals in self._by_owner.values())

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        status: ProposalStatus | None = None,
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        async with self._lock:
            items = [
                proposal
                for proposal in self._by_owner.get(owner_user_id, {}).values()
                if (status is None or proposal.status is status)
                and (contact_id is None or proposal.contact_id == contact_id)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(proposal.owner_user_id, {})
            existing = user_bucket.get(proposal.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"MemoryProposal '{proposal.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="MemoryProposal",
                        entity_id=proposal.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="MemoryProposal",
                        entity_id=proposal.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[proposal.id] = proposal
            return proposal

    async def delete(self, owner_user_id: str, proposal_id: str) -> None:
        async with self._lock:
            self._by_owner.get(owner_user_id, {}).pop(proposal_id, None)
