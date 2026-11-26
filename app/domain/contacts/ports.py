"""Contact repository and least-privilege reader ports."""

from __future__ import annotations

from typing import Protocol

from app.domain.contacts.models import Contact


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

    async def delete(
        self,
        owner_user_id: str,
        contact_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        """Delete ``contact_id`` under ``owner_user_id`` enforcing optional version checks."""


class ContactReaderPort(Protocol):
    """Least-privilege read-only port exposing only caller-owned contact lookups."""

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        """Fetch ``contact_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        """Return ``True`` if ``contact_id`` exists under any user partition."""
