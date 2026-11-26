"""In-memory contact repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.contacts.models import Contact
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryContactRepository:
    """Async fake repository mirroring ``users/{uid}/contacts/{contactId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Contact]] = {}

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(contact_id)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        async with self._lock:
            return any(contact_id in user_contacts for user_contacts in self._by_owner.values())

    async def list_by_owner(self, owner_user_id: str) -> list[Contact]:
        async with self._lock:
            items = list(self._by_owner.get(owner_user_id, {}).values())
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, contact: Contact, *, expected_version: int | None = None) -> Contact:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(contact.owner_user_id, {})
            existing = user_bucket.get(contact.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Contact '{contact.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Contact", entity_id=contact.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Contact",
                        entity_id=contact.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[contact.id] = contact
            return contact

    async def delete(
        self,
        owner_user_id: str,
        contact_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        async with self._lock:
            user_bucket = self._by_owner.get(owner_user_id, {})
            existing = user_bucket.get(contact_id)
            if existing is None:
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
            if expected_version is not None and existing.version != expected_version:
                raise VersionConflictError(
                    entity_name="Contact",
                    entity_id=contact_id,
                    expected_version=expected_version,
                    actual_version=existing.version,
                )
            del user_bucket[contact_id]
