"""In-memory approved memory repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.memory.models import Memory
from app.domain.memory.types import ConsentStatus, MemoryLifecycleState, MemoryScope, MemoryType
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryMemoryRepository:
    """Async fake repository mirroring ``users/{uid}/memories/{memoryId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Memory]] = {}
        self._deleted_by_owner: dict[str, dict[str, Memory]] = {}

    async def get_for_owner(self, owner_user_id: str, memory_id: str) -> Memory | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(memory_id)

    async def exists_for_any_owner(self, memory_id: str) -> bool:
        async with self._lock:
            return any(memory_id in user_memories for user_memories in self._by_owner.values())

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
        async with self._lock:
            items = [
                memory
                for memory in self._by_owner.get(owner_user_id, {}).values()
                if (include_revoked or memory.consent_status is ConsentStatus.APPROVED)
                and (include_superseded or memory.lifecycle_state is MemoryLifecycleState.APPROVED)
                and (scope is None or memory.scope is scope)
                and (contact_id is None or memory.contact_id == contact_id)
                and (memory_type is None or memory.memory_type is memory_type)
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, memory: Memory, *, expected_version: int | None = None) -> Memory:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(memory.owner_user_id, {})
            existing = user_bucket.get(memory.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Memory '{memory.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Memory", entity_id=memory.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Memory",
                        entity_id=memory.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[memory.id] = memory
            return memory

    async def delete(
        self,
        owner_user_id: str,
        memory_id: str,
        *,
        expected_version: int | None = None,
        deleted_snapshot: Memory | None = None,
    ) -> None:
        async with self._lock:
            user_bucket = self._by_owner.get(owner_user_id, {})
            existing = user_bucket.get(memory_id)
            if existing is None:
                raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
            if expected_version is not None and existing.version != expected_version:
                raise VersionConflictError(
                    entity_name="Memory",
                    entity_id=memory_id,
                    expected_version=expected_version,
                    actual_version=existing.version,
                )
            tombstone = deleted_snapshot or existing.mark_deleted(deleted_at=existing.updated_at)
            self._deleted_by_owner.setdefault(owner_user_id, {})[memory_id] = tombstone
            del user_bucket[memory_id]

    async def get_deleted_for_owner(
        self,
        owner_user_id: str,
        memory_id: str,
    ) -> Memory | None:
        async with self._lock:
            return self._deleted_by_owner.get(owner_user_id, {}).get(memory_id)
