"""Application service assembling bounded, provenance-aware memory context for brief generation."""

from __future__ import annotations

import asyncio
import logging
import re

from app.domain.errors import (
    AuthorizationError,
    DomainValidationError,
    EntityNotFoundError,
)
from app.domain.models import (
    AuthenticatedPrincipal,
    BriefPreparationContext,
    Contact,
    ContextBudget,
    Meeting,
    Memory,
    ProvenanceMemoryItem,
    RecentMeetingSummary,
    UserPreferences,
)
from app.domain.ports import (
    ContactRepository,
    MeetingRepository,
    MemoryRepository,
    UserPreferencesRepository,
)
from app.domain.types import (
    MeetingPurpose,
    MeetingStatus,
    MemoryScope,
    MemoryType,
)

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def _tokenize_keywords(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_WORD_RE.findall(text.lower()))


def _meeting_relevance_key(
    meeting: Meeting,
    *,
    target_purpose: MeetingPurpose | None,
    objective_tokens: set[str],
) -> tuple[int, int, float, str]:
    purpose_match = 1 if target_purpose is not None and meeting.purpose is target_purpose else 0
    haystack = _tokenize_keywords(f"{meeting.objective} {meeting.notes or ''}")
    overlap = len(objective_tokens & haystack) if objective_tokens else 0
    recency_anchor = meeting.scheduled_at or meeting.updated_at
    return (purpose_match, overlap, recency_anchor.timestamp(), meeting.id)


def _memory_relevance_key(
    memory: Memory,
    *,
    objective_tokens: set[str],
) -> tuple[int, int, float, str]:
    follow_up_boost = 1 if memory.memory_type is MemoryType.FOLLOW_UP_COMMITMENT else 0
    haystack = _tokenize_keywords(memory.text)
    overlap = len(objective_tokens & haystack) if objective_tokens else 0
    return (overlap, follow_up_boost, memory.updated_at.timestamp(), memory.id)


def _estimate_contact_and_prefs_chars(
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


def _estimate_memory_item_chars(item: ProvenanceMemoryItem) -> int:
    excerpt_len = len(item.source.excerpt) if item.source.excerpt else 0
    return len(item.text) + excerpt_len + len(item.memory_type.value)


def _estimate_meeting_summary_chars(summary: RecentMeetingSummary) -> int:
    notes_len = len(summary.notes_excerpt) if summary.notes_excerpt else 0
    return len(summary.objective) + notes_len + len(summary.purpose.value)


class MemoryRetrievalService:
    """Retrieves user-scoped preferences, contact profile, recent meetings, and approved memories.

    Enforces Brew's 5-step pre-brief retrieval sequence:
    1. Load approved user preferences.
    2. Load the selected contact profile.
    3. Retrieve the contact's recent relevant meetings.
    4. Retrieve approved memories for that contact.
    5. Build a bounded, provenance-aware context object.
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

    async def build_brief_context(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
        purpose: MeetingPurpose | None = None,
        objective: str | None = None,
        exclude_meeting_id: str | None = None,
        budget: ContextBudget | None = None,
    ) -> BriefPreparationContext:
        """Execute the 5-step retrieval workflow strictly scoped to ``principal.user_id``."""
        active_budget = budget or self._default_budget
        uid = principal.user_id

        # 1. Load approved user preferences (structured profile + consented preference memories)
        user_preferences, raw_preference_memories = await asyncio.gather(
            self._preferences_repo.get_by_owner(uid),
            self._memory_repo.list_by_owner(
                uid,
                scope=MemoryScope.USER_PREFERENCE,
                include_revoked=False,
            ),
        )
        if user_preferences is not None and user_preferences.owner_user_id != uid:
            user_preferences = None

        # 2. Load the selected contact profile (strictly enforcing caller ownership)
        contact = await self._contact_repo.get_for_owner(uid, contact_id)
        if contact is None:
            if await self._contact_repo.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)

        # 3 & 4. Retrieve contact's recent relevant meetings and approved contact memories
        raw_meetings, raw_contact_memories = await asyncio.gather(
            self._meeting_repo.list_by_owner(uid, contact_id=contact.id),
            self._memory_repo.list_by_owner(
                uid,
                scope=MemoryScope.CONTACT,
                contact_id=contact.id,
                include_revoked=False,
            ),
        )

        objective_tokens = _tokenize_keywords(objective)

        eligible_meetings = [
            mtg
            for mtg in raw_meetings
            if mtg.owner_user_id == uid
            and mtg.contact_id == contact.id
            and mtg.status is not MeetingStatus.CANCELLED
            and (exclude_meeting_id is None or mtg.id != exclude_meeting_id)
        ]
        ranked_meetings = sorted(
            eligible_meetings,
            key=lambda mtg: _meeting_relevance_key(
                mtg,
                target_purpose=purpose,
                objective_tokens=objective_tokens,
            ),
            reverse=True,
        )

        eligible_pref_memories = [
            mem
            for mem in raw_preference_memories
            if mem.owner_user_id == uid
            and mem.is_active
            and mem.scope is MemoryScope.USER_PREFERENCE
        ]
        ranked_pref_memories = sorted(
            eligible_pref_memories,
            key=lambda mem: _memory_relevance_key(mem, objective_tokens=objective_tokens),
            reverse=True,
        )

        eligible_contact_memories = [
            mem
            for mem in raw_contact_memories
            if mem.owner_user_id == uid
            and mem.is_active
            and mem.scope is MemoryScope.CONTACT
            and mem.contact_id == contact.id
        ]
        ranked_contact_memories = sorted(
            eligible_contact_memories,
            key=lambda mem: _memory_relevance_key(mem, objective_tokens=objective_tokens),
            reverse=True,
        )

        # 5. Build a bounded, provenance-aware context object
        base_chars = min(
            _estimate_contact_and_prefs_chars(contact, user_preferences),
            active_budget.max_total_chars,
        )
        running_chars = base_chars
        was_truncated = False

        selected_pref_items: list[ProvenanceMemoryItem] = []
        for mem in ranked_pref_memories:
            if len(selected_pref_items) >= active_budget.max_preference_memories:
                was_truncated = True
                break
            candidate_item = ProvenanceMemoryItem.from_memory(mem)
            cost = _estimate_memory_item_chars(candidate_item)
            if running_chars + cost > active_budget.max_total_chars:
                was_truncated = True
                continue
            selected_pref_items.append(candidate_item)
            running_chars += cost

        selected_contact_items: list[ProvenanceMemoryItem] = []
        for mem in ranked_contact_memories:
            if len(selected_contact_items) >= active_budget.max_contact_memories:
                was_truncated = True
                break
            candidate_item = ProvenanceMemoryItem.from_memory(mem)
            cost = _estimate_memory_item_chars(candidate_item)
            if running_chars + cost > active_budget.max_total_chars:
                was_truncated = True
                continue
            selected_contact_items.append(candidate_item)
            running_chars += cost

        selected_meetings: list[RecentMeetingSummary] = []
        for mtg in ranked_meetings:
            if len(selected_meetings) >= active_budget.max_recent_meetings:
                was_truncated = True
                break
            excerpt = mtg.notes[:280] if mtg.notes else None
            summary = RecentMeetingSummary(
                meeting_id=mtg.id,
                purpose=mtg.purpose,
                tone=mtg.tone,
                objective=mtg.objective,
                duration_minutes=mtg.duration_minutes,
                scheduled_at=mtg.scheduled_at,
                status=mtg.status,
                notes_excerpt=excerpt,
                updated_at=mtg.updated_at,
            )
            cost = _estimate_meeting_summary_chars(summary)
            if running_chars + cost > active_budget.max_total_chars:
                was_truncated = True
                continue
            selected_meetings.append(summary)
            running_chars += cost

        context = BriefPreparationContext(
            owner_user_id=uid,
            contact=contact,
            user_preferences=user_preferences,
            preference_memories=selected_pref_items,
            contact_memories=selected_contact_items,
            recent_meetings=selected_meetings,
            budget=active_budget,
            total_context_chars=running_chars,
            was_truncated=was_truncated,
        )
        logger.info(
            "Assembled bounded brief preparation context",
            extra={"event_type": "memory.context_assembled"},
        )
        return context

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
        return [mem for mem in records if mem.owner_user_id == principal.user_id]
