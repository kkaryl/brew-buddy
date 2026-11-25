"""Memory maintenance: update or delete approved memories and upsert user preferences."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.safety.untrusted_text import sanitize_untrusted_text
from app.application.shared.validation import translate_pydantic_error
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.types import MeetingTone
from app.domain.memory.models import Memory, UserPreferences
from app.domain.memory.ports import MemoryRepository, UserPreferencesRepository
from app.domain.memory.sensitivity import detect_sensitive_or_third_party_assumption
from app.domain.memory.types import ConsentStatus, MemoryType
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import (
    AuthorizationError,
    DomainValidationError,
    EntityNotFoundError,
    VersionConflictError,
)

logger = logging.getLogger(__name__)


def _validate_custom_display_name(raw_name: str) -> str:
    normalized = raw_name.replace("\u2014", "-").strip()
    if not normalized:
        raise DomainValidationError("Display name must not be empty.")
    if len(normalized) > 120:
        raise DomainValidationError("Display name must be 120 characters or fewer.")
    sanitized = sanitize_untrusted_text(normalized, max_chars=120)
    if sanitized.injection_detected:
        raise DomainValidationError(
            "Display name contains disallowed instruction-override directives."
        )
    if sanitized.pii_redacted:
        raise DomainValidationError(
            "Display name cannot contain email addresses, phone numbers, or sensitive IDs."
        )
    return sanitized.text


class MemoryMaintenance:
    """Upserts user preferences and updates or deletes approved memories."""

    def __init__(
        self,
        *,
        preferences_repo: UserPreferencesRepository,
        memory_repo: MemoryRepository,
        clock: ClockPort,
    ) -> None:
        self._preferences_repo = preferences_repo
        self._memory_repo = memory_repo
        self._clock = clock

    async def upsert_user_preferences(
        self,
        *,
        principal: AuthenticatedPrincipal,
        preferred_display_name: str | None = None,
        clear_preferred_display_name: bool = False,
        default_tone: MeetingTone | None = None,
        default_duration_minutes: int | None = None,
        preferred_question_count: int | None = None,
        communication_style_notes: str | None = None,
        focus_areas: list[str] | None = None,
    ) -> UserPreferences:
        """Create or update ``users/{uid}/preferences/default`` with version control."""
        uid = principal.user_id
        now = self._clock.now_utc()
        stored = await self._preferences_repo.get_by_owner(uid)

        cleaned_display_name: str | None = None
        if not clear_preferred_display_name and preferred_display_name is not None:
            cleaned_display_name = _validate_custom_display_name(preferred_display_name)

        try:
            if stored is None:
                prefs = UserPreferences(
                    id="default",
                    owner_user_id=uid,
                    preferred_display_name=(
                        None if clear_preferred_display_name else cleaned_display_name
                    ),
                    default_tone=default_tone or MeetingTone.WARM_CASUAL,
                    default_duration_minutes=default_duration_minutes or 30,
                    preferred_question_count=(
                        preferred_question_count if preferred_question_count is not None else 6
                    ),
                    communication_style_notes=communication_style_notes,
                    focus_areas=focus_areas or [],
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                return await self._preferences_repo.save(prefs)

            resolved_display_name = (
                None
                if clear_preferred_display_name
                else (
                    cleaned_display_name
                    if cleaned_display_name is not None
                    else stored.preferred_display_name
                )
            )
            updated = UserPreferences(
                id=stored.id,
                owner_user_id=uid,
                preferred_display_name=resolved_display_name,
                default_tone=(default_tone if default_tone is not None else stored.default_tone),
                default_duration_minutes=(
                    default_duration_minutes
                    if default_duration_minutes is not None
                    else stored.default_duration_minutes
                ),
                preferred_question_count=(
                    preferred_question_count
                    if preferred_question_count is not None
                    else stored.preferred_question_count
                ),
                communication_style_notes=(
                    communication_style_notes
                    if communication_style_notes is not None
                    else stored.communication_style_notes
                ),
                focus_areas=(focus_areas if focus_areas is not None else list(stored.focus_areas)),
                created_at=stored.created_at,
                updated_at=max(now, stored.created_at),
                version=stored.version + 1,
            )
        except ValidationError as exc:
            raise translate_pydantic_error(exc) from exc

        return await self._preferences_repo.save(updated, expected_version=stored.version)

    async def update_preferred_display_name(
        self,
        *,
        principal: AuthenticatedPrincipal,
        display_name: str | None,
    ) -> UserPreferences | None:
        """Set or clear the caller's custom display name override."""
        uid = principal.user_id
        if display_name is None:
            stored = await self._preferences_repo.get_by_owner(uid)
            if stored is None or stored.preferred_display_name is None:
                return stored
            saved = await self.upsert_user_preferences(
                principal=principal,
                clear_preferred_display_name=True,
            )
            logger.info(
                "Cleared custom user display name",
                extra={"event_type": "user.display_name.cleared"},
            )
            return saved

        saved = await self.upsert_user_preferences(
            principal=principal,
            preferred_display_name=display_name,
        )
        logger.info(
            "Updated custom user display name",
            extra={"event_type": "user.display_name.updated"},
        )
        return saved

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
        """Update an approved memory enforcing ownership and optimistic version control."""
        uid = principal.user_id
        memory = await self._memory_repo.get_for_owner(uid, memory_id)
        if memory is None:
            if await self._memory_repo.exists_for_any_owner(memory_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)

        if memory.version != expected_version:
            raise VersionConflictError(
                entity_name="Memory",
                entity_id=memory_id,
                expected_version=expected_version,
                actual_version=memory.version,
            )

        cleaned_text = text
        if cleaned_text is not None:
            sanitized = sanitize_untrusted_text(cleaned_text, max_chars=1000)
            if sanitized.injection_detected:
                raise DomainValidationError(
                    "Updated memory text contains disallowed instruction-override directives."
                )
            sensitive_reason = detect_sensitive_or_third_party_assumption(sanitized.text)
            if sensitive_reason is not None:
                raise DomainValidationError(
                    f"Cannot persist memory containing {sensitive_reason}.",
                    code="SENSITIVE_MEMORY_REJECTED",
                )
            cleaned_text = sanitized.text

        now = max(self._clock.now_utc(), memory.created_at)
        try:
            updated = memory.apply_update(
                text=cleaned_text,
                memory_type=memory_type,
                consent_status=consent_status,
                updated_at=now,
            )
        except ValidationError as exc:
            raise translate_pydantic_error(exc) from exc

        saved = await self._memory_repo.save(updated, expected_version=expected_version)
        logger.info(
            "Approved memory updated",
            extra={"event_type": "memory.updated"},
        )
        return saved

    async def delete_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int | None = None,
    ) -> None:
        """Delete an approved memory and archive its DELETED tombstone with provenance."""
        uid = principal.user_id
        memory = await self._memory_repo.get_for_owner(uid, memory_id)
        if memory is None:
            if await self._memory_repo.exists_for_any_owner(memory_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)

        if expected_version is not None and memory.version != expected_version:
            raise VersionConflictError(
                entity_name="Memory",
                entity_id=memory_id,
                expected_version=expected_version,
                actual_version=memory.version,
            )

        now = max(self._clock.now_utc(), memory.created_at)
        deleted_snapshot = memory.mark_deleted(deleted_at=now)
        await self._memory_repo.delete(
            uid,
            memory_id,
            expected_version=expected_version,
            deleted_snapshot=deleted_snapshot,
        )
        logger.info(
            "Approved memory deleted and removed from active retrieval",
            extra={"event_type": "memory.deleted"},
        )
