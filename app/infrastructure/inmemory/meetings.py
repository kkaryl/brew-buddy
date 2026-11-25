"""In-memory meeting repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.meetings.models import Meeting
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryMeetingRepository:
    """Async fake repository mirroring ``users/{uid}/meetings/{meetingId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, dict[str, Meeting]] = {}

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id, {}).get(meeting_id)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        async with self._lock:
            return any(meeting_id in user_meetings for user_meetings in self._by_owner.values())

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        async with self._lock:
            items = [
                meeting
                for meeting in self._by_owner.get(owner_user_id, {}).values()
                if contact_id is None or meeting.contact_id == contact_id
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    async def save(self, meeting: Meeting, *, expected_version: int | None = None) -> Meeting:
        async with self._lock:
            user_bucket = self._by_owner.setdefault(meeting.owner_user_id, {})
            existing = user_bucket.get(meeting.id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"Meeting '{meeting.id}' already exists.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting.id)
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="Meeting",
                        entity_id=meeting.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            user_bucket[meeting.id] = meeting
            return meeting
