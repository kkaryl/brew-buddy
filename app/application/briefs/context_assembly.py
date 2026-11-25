"""Step 2 and 3 of the brief workflow: resolve the contact and assemble bounded context."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.memory.retrieval import (
    estimate_contact_and_prefs_chars,
    estimate_meeting_summary_chars,
    estimate_memory_item_chars,
    meeting_relevance_key,
    memory_relevance_key,
    tokenize_keywords,
)
from app.application.safety.untrusted_text import sanitize_untrusted_text
from app.application.shared.telemetry import (
    ATTR_MEMORY_RETRIEVED_COUNT,
    brew_span,
)
from app.domain.briefs.context import (
    BriefPreparationContext,
    ContextBudget,
    ProvenanceMemoryItem,
    RecentMeetingSummary,
)
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingPurpose, MeetingStatus
from app.domain.memory.models import Memory
from app.domain.memory.ports import MemoryRepository, UserPreferencesRepository
from app.domain.memory.types import MemoryScope
from app.domain.shared.errors import (
    AuthorizationError,
    EntityNotFoundError,
    PersistenceOperationError,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _sanitize_contact_for_context(contact: Contact) -> Contact:
    if not contact.context_notes:
        return contact
    cleaned = sanitize_untrusted_text(contact.context_notes, max_chars=2000).text
    if len(cleaned) < 3 or cleaned == contact.context_notes:
        return contact
    return contact.model_copy(update={"context_notes": cleaned})


def _sanitize_memory_for_context(memory: Memory) -> Memory:
    cleaned_text = sanitize_untrusted_text(memory.text, max_chars=1000).text
    safe_text = cleaned_text if len(cleaned_text) >= 3 else memory.text
    safe_source = memory.source
    if memory.source.excerpt:
        cleaned_excerpt = sanitize_untrusted_text(memory.source.excerpt, max_chars=500).text
        if cleaned_excerpt:
            safe_source = memory.source.model_copy(update={"excerpt": cleaned_excerpt})
    if safe_text == memory.text and safe_source == memory.source:
        return memory
    return memory.model_copy(update={"text": safe_text, "source": safe_source})


class ResilientBriefContextAssembler:
    """Resolves the owned contact and assembles bounded, sanitized pre-brief context."""

    def __init__(
        self,
        *,
        preferences_repo: UserPreferencesRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        memory_repo: MemoryRepository,
        safeguards: BriefWorkflowSafeguardConfig,
        context_budget: ContextBudget,
    ) -> None:
        self._preferences_repo = preferences_repo
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._memory_repo = memory_repo
        self._safeguards = safeguards
        self._context_budget = context_budget

    async def _call_optional_context_source(
        self,
        source_label: str,
        operation: Callable[[], Awaitable[_T]],
        *,
        fallback: _T,
        degraded_sources: list[str],
    ) -> _T:
        """Execute an optional context read with bounded retries and graceful degradation."""
        max_attempts = 1 + self._safeguards.max_tool_retries
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    operation(),
                    timeout=self._safeguards.context_io_timeout_seconds,
                )
            except (TimeoutError, PersistenceOperationError):
                if attempt >= max_attempts:
                    if source_label not in degraded_sources:
                        degraded_sources.append(source_label)
                    logger.warning(
                        f"Optional context source '{source_label}' unavailable after "
                        f"{attempt} attempt(s); continuing with grounded baseline context",
                        extra={"event_type": "workflow.context.degraded"},
                    )
                    return fallback
        return fallback

    async def resolve_owned_contact(
        self,
        *,
        owner_user_id: str,
        contact_id: str,
    ) -> Contact:
        contact = await self._contact_repo.get_for_owner(owner_user_id, contact_id)
        if contact is None:
            if await self._contact_repo.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return contact

    async def assemble_resilient_context(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact: Contact,
        purpose: MeetingPurpose,
        objective: str,
        degraded_sources: list[str],
        exclude_meeting_id: str | None = None,
    ) -> BriefPreparationContext:
        """Step 3: Retrieve preferences, history, and approved memories with bounded budget."""
        with brew_span(
            "brew.context.retrieve",
            operation_name="context.retrieve",
            tracer_name=__name__,
        ) as ctx_tracker:
            uid = principal.user_id
            safe_contact = _sanitize_contact_for_context(contact)

            empty_pref_memories: list[Memory] = []
            empty_meetings: list[Meeting] = []
            empty_contact_memories: list[Memory] = []
            (
                user_preferences,
                raw_pref_memories,
                raw_meetings,
                raw_contact_memories,
            ) = await asyncio.gather(
                self._call_optional_context_source(
                    "user_preferences",
                    lambda: self._preferences_repo.get_by_owner(uid),
                    fallback=None,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "preference_memories",
                    lambda: self._memory_repo.list_by_owner(
                        uid,
                        scope=MemoryScope.USER_PREFERENCE,
                        include_revoked=False,
                    ),
                    fallback=empty_pref_memories,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "meeting_history",
                    lambda: self._meeting_repo.list_by_owner(uid, contact_id=contact.id),
                    fallback=empty_meetings,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "contact_memories",
                    lambda: self._memory_repo.list_by_owner(
                        uid,
                        scope=MemoryScope.CONTACT,
                        contact_id=contact.id,
                        include_revoked=False,
                    ),
                    fallback=empty_contact_memories,
                    degraded_sources=degraded_sources,
                ),
            )

            if user_preferences is not None and user_preferences.owner_user_id != uid:
                user_preferences = None

            objective_tokens = tokenize_keywords(objective)

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
                key=lambda mtg: meeting_relevance_key(
                    mtg,
                    target_purpose=purpose,
                    objective_tokens=objective_tokens,
                ),
                reverse=True,
            )

            eligible_pref_memories = [
                _sanitize_memory_for_context(mem)
                for mem in raw_pref_memories
                if mem.owner_user_id == uid
                and mem.is_active
                and mem.scope is MemoryScope.USER_PREFERENCE
            ]
            ranked_pref_memories = sorted(
                eligible_pref_memories,
                key=lambda mem: memory_relevance_key(mem, objective_tokens=objective_tokens),
                reverse=True,
            )

            eligible_contact_memories = [
                _sanitize_memory_for_context(mem)
                for mem in raw_contact_memories
                if mem.owner_user_id == uid
                and mem.is_active
                and mem.scope is MemoryScope.CONTACT
                and mem.contact_id == contact.id
            ]
            ranked_contact_memories = sorted(
                eligible_contact_memories,
                key=lambda mem: memory_relevance_key(mem, objective_tokens=objective_tokens),
                reverse=True,
            )

            budget = self._context_budget
            running_chars = min(
                estimate_contact_and_prefs_chars(safe_contact, user_preferences),
                budget.max_total_chars,
            )
            was_truncated = False

            selected_pref_items: list[ProvenanceMemoryItem] = []
            for mem in ranked_pref_memories:
                if len(selected_pref_items) >= budget.max_preference_memories:
                    was_truncated = True
                    break
                item = ProvenanceMemoryItem.from_memory(mem)
                cost = estimate_memory_item_chars(item)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_pref_items.append(item)
                running_chars += cost

            selected_contact_items: list[ProvenanceMemoryItem] = []
            for mem in ranked_contact_memories:
                if len(selected_contact_items) >= budget.max_contact_memories:
                    was_truncated = True
                    break
                item = ProvenanceMemoryItem.from_memory(mem)
                cost = estimate_memory_item_chars(item)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_contact_items.append(item)
                running_chars += cost

            selected_meetings: list[RecentMeetingSummary] = []
            for mtg in ranked_meetings:
                if len(selected_meetings) >= budget.max_recent_meetings:
                    was_truncated = True
                    break
                raw_excerpt = mtg.notes[:280] if mtg.notes else None
                safe_excerpt: str | None = None
                if raw_excerpt:
                    cleaned_notes = sanitize_untrusted_text(raw_excerpt, max_chars=280).text
                    safe_excerpt = cleaned_notes or None
                summary = RecentMeetingSummary(
                    meeting_id=mtg.id,
                    purpose=mtg.purpose,
                    tone=mtg.tone,
                    objective=mtg.objective,
                    duration_minutes=mtg.duration_minutes,
                    scheduled_at=mtg.scheduled_at,
                    status=mtg.status,
                    notes_excerpt=safe_excerpt,
                    updated_at=mtg.updated_at,
                )
                cost = estimate_meeting_summary_chars(summary)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_meetings.append(summary)
                running_chars += cost

            retrieved_memories = len(selected_pref_items) + len(selected_contact_items)
            ctx_tracker.set_attributes(
                {
                    ATTR_MEMORY_RETRIEVED_COUNT: retrieved_memories,
                    "brew.context.preference_memories_count": len(selected_pref_items),
                    "brew.context.contact_memories_count": len(selected_contact_items),
                    "brew.context.recent_meetings_count": len(selected_meetings),
                    "brew.context.truncated": was_truncated,
                    "brew.context.degraded_sources_count": len(degraded_sources),
                }
            )
            if degraded_sources:
                ctx_tracker.mark_degraded("CONTEXT_SOURCE_DEGRADED")

            logger.info(
                "Retrieved pre-brief context and memories",
                extra={
                    "event_type": "workflow.context.retrieved",
                    "operation_name": "context.retrieve",
                    "memory_retrieved_count": retrieved_memories,
                    "result_status": ctx_tracker.status,
                },
            )
            return BriefPreparationContext(
                owner_user_id=uid,
                contact=safe_contact,
                user_preferences=user_preferences,
                preference_memories=selected_pref_items,
                contact_memories=selected_contact_items,
                recent_meetings=selected_meetings,
                budget=budget,
                total_context_chars=running_chars,
                was_truncated=was_truncated,
            )
