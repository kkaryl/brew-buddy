"""Meeting repository and least-privilege reader ports."""

from __future__ import annotations

from typing import Protocol

from app.domain.meetings.models import Meeting


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

    async def delete(self, owner_user_id: str, meeting_id: str) -> None:
        """Delete ``meeting_id`` strictly under ``owner_user_id``."""


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
