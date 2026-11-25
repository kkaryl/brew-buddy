"""In-memory user preferences repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.memory.models import UserPreferences
from app.domain.shared.errors import ConflictError, EntityNotFoundError, VersionConflictError


class InMemoryUserPreferencesRepository:
    """Async fake repository mirroring ``users/{uid}/preferences/default``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_owner: dict[str, UserPreferences] = {}

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        async with self._lock:
            return self._by_owner.get(owner_user_id)

    async def save(
        self,
        preferences: UserPreferences,
        *,
        expected_version: int | None = None,
    ) -> UserPreferences:
        async with self._lock:
            existing = self._by_owner.get(preferences.owner_user_id)
            if expected_version is None:
                if existing is not None:
                    raise ConflictError(
                        f"UserPreferences for '{preferences.owner_user_id}' already exist.",
                        code="ALREADY_EXISTS",
                    )
            else:
                if existing is None:
                    raise EntityNotFoundError(
                        entity_name="UserPreferences",
                        entity_id=preferences.id,
                    )
                if existing.version != expected_version:
                    raise VersionConflictError(
                        entity_name="UserPreferences",
                        entity_id=existing.id,
                        expected_version=expected_version,
                        actual_version=existing.version,
                    )
            self._by_owner[preferences.owner_user_id] = preferences
            return preferences
