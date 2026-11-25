"""In-memory preparation brief repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.briefs.models import PreparationBrief
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryBriefRepository:
    """Async fake repository mirroring ``users/{uid}/briefs/{briefId}`` and immutable revisions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, PreparationBrief]] = {}
        self._revisions_by_owner: dict[str, dict[str, dict[int, PreparationBrief]]] = {}

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(brief_id)

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        async with self._lock:
            return any(brief_id in user_briefs for user_briefs in self._by_owner.values())

    async def list_by_meeting(
        self,
        owner_user_id: str,
        meeting_id: str,
    ) -> list[PreparationBrief]:
        async with self._lock:
            items = [
                brief
                for brief in self._by_owner.get(owner_user_id, {}).values()
                if brief.meeting_id == meeting_id
            ]
        return sorted(items, key=lambda item: (item.version, item.id))

    async def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(brief.owner_user_id, {})
            existing = user_bucket.get(brief.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"PreparationBrief '{brief.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="PreparationBrief",
                        entity_id=brief.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="PreparationBrief",
                        entity_id=brief.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[brief.id] = brief
            rev_bucket = self._revisions_by_owner.setdefault(brief.owner_user_id, {}).setdefault(
                brief.id, {}
            )
            rev_bucket[brief.version] = brief
            return brief

    async def list_revisions(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> list[PreparationBrief]:
        async with self._lock:
            rev_map = self._revisions_by_owner.get(owner_user_id, {}).get(brief_id, {})
            items = list(rev_map.values())
        return sorted(items, key=lambda item: item.version)

    async def get_revision(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> PreparationBrief | None:
        async with self._lock:
            return self._revisions_by_owner.get(owner_user_id, {}).get(brief_id, {}).get(version)
