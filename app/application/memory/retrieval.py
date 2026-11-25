"""Approved-memory listing plus the ranking and size helpers shared by context assembly."""

from __future__ import annotations

import logging
import re

from app.application.shared.telemetry import ATTR_MEMORY_RETRIEVED_COUNT, brew_span
from app.domain.briefs.context import ContextBudget, ProvenanceMemoryItem, RecentMeetingSummary
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingPurpose
from app.domain.memory.models import Memory, UserPreferences
from app.domain.memory.ports import MemoryRepository, UserPreferencesRepository
from app.domain.memory.types import MemoryScope, MemoryType
from app.domain.shared.errors import AuthorizationError, DomainValidationError, EntityNotFoundError

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def tokenize_keywords(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_WORD_RE.findall(text.lower()))


def meeting_relevance_key(
    meeting: Meeting,
    *,
    target_purpose: MeetingPurpose | None,
    objective_tokens: set[str],
) -> tuple[int, int, float, str]:
    purpose_match = 1 if target_purpose is not None and meeting.purpose is target_purpose else 0
    haystack = tokenize_keywords(f"{meeting.objective} {meeting.notes or ''}")
    overlap = len(objective_tokens & haystack) if objective_tokens else 0
    recency_anchor = meeting.scheduled_at or meeting.updated_at
    return (purpose_match, overlap, recency_anchor.timestamp(), meeting.id)


def memory_relevance_key(
    memory: Memory,
    *,
    objective_tokens: set[str],
) -> tuple[int, int, float, str]:
    follow_up_boost = 1 if memory.memory_type is MemoryType.FOLLOW_UP_COMMITMENT else 0
    haystack = tokenize_keywords(memory.text)
    overlap = len(objective_tokens & haystack) if objective_tokens else 0
    return (overlap, follow_up_boost, memory.updated_at.timestamp(), memory.id)


def estimate_contact_and_prefs_chars(
    contact: Contact,
    preferences: UserPreferences | None,
) -> int:
    total = len(contact.name)
    for optional_field in (
        contact.title,
        contact.role,
        contact.organization,
        contact.context_notes,
    ):
        if optional_field:
            total += len(optional_field)
    if preferences is not None:
        if preferences.communication_style_notes:
            total += len(preferences.communication_style_notes)
        total += sum(len(area) for area in preferences.focus_areas)
    return total


def estimate_memory_item_chars(item: ProvenanceMemoryItem) -> int:
    excerpt_len = len(item.source.excerpt) if item.source.excerpt else 0
    return len(item.text) + excerpt_len + len(item.memory_type.value)


def estimate_meeting_summary_chars(summary: RecentMeetingSummary) -> int:
    notes_len = len(summary.notes_excerpt) if summary.notes_excerpt else 0
    return len(summary.objective) + notes_len + len(summary.purpose.value)


class MemoryRetrievalService:
    """Lists the caller's approved memories and holds the repositories brief context reads.

    Pre-brief context is assembled in one place only,
    ``app.application.briefs.context_assembly.ResilientBriefContextAssembler``, which ranks
    and sizes items with the helper functions in this module.
    """

    def __init__(
        self,
        *,
        preferences_repo: UserPreferencesRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        memory_repo: MemoryRepository,
        default_budget: ContextBudget | None = None,
    ) -> None:
        self._preferences_repo = preferences_repo
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._memory_repo = memory_repo
        self._default_budget = default_budget or ContextBudget()

    @property
    def preferences_repo(self) -> UserPreferencesRepository:
        return self._preferences_repo

    @property
    def contact_repo(self) -> ContactRepository:
        return self._contact_repo

    @property
    def meeting_repo(self) -> MeetingRepository:
        return self._meeting_repo

    @property
    def memory_repo(self) -> MemoryRepository:
        return self._memory_repo

    @property
    def default_budget(self) -> ContextBudget:
        return self._default_budget

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
        """List approved memories strictly owned by ``principal``."""
        with brew_span(
            "brew.memory.retrieve",
            operation_name="memory.retrieve",
            tracer_name=__name__,
        ) as tracker:
            if scope is MemoryScope.USER_PREFERENCE and contact_id is not None:
                raise DomainValidationError(
                    "contact_id filter cannot be combined with scope='user_preference'."
                )
            if contact_id is not None:
                contact = await self._contact_repo.get_for_owner(principal.user_id, contact_id)
                if contact is None:
                    if await self._contact_repo.exists_for_any_owner(contact_id):
                        raise AuthorizationError()
                    raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)

            records = await self._memory_repo.list_by_owner(
                principal.user_id,
                scope=scope,
                contact_id=contact_id,
                memory_type=memory_type,
                include_revoked=include_revoked,
                include_superseded=include_superseded,
            )
            results = [mem for mem in records if mem.owner_user_id == principal.user_id]
            tracker.status = "empty" if not results else "ok"
            tracker.set_attribute(ATTR_MEMORY_RETRIEVED_COUNT, len(results))
            logger.info(
                f"Retrieved {len(results)} approved memories",
                extra={
                    "event_type": "memory.retrieved",
                    "operation_name": "memory.retrieve",
                    "memory_retrieved_count": len(results),
                    "result_status": tracker.status,
                },
            )
            return results
