"""Least-privilege application service powering Brew's ADK ``conversation_coach`` tools.

Enforces caller ownership, minimal data projection, PII redaction, untrusted-note
prompt-injection sanitization, and human-in-the-loop staging separation without
importing ADK, FastAPI, or Firestore SDKs.
"""

from __future__ import annotations

import asyncio

from app.application.coaching.projections import (
    ContactContextProjection,
    MeetingHistoryProjection,
    ProjectedMeetingHistoryItem,
    ProjectedMemorySummary,
    StagedMemoryCandidateProjection,
    SuggestedMemoryCandidatesProjection,
    UserPreferencesProjection,
)
from app.application.memory.candidate_staging import (
    STAGING_OPERATION_NAME,
    STAGING_SPAN_NAME,
    MemoryCandidateStagingPipeline,
    record_staging_outcome,
    resolve_proposal_references,
)
from app.application.memory.retrieval import (
    meeting_relevance_key,
    memory_relevance_key,
    tokenize_keywords,
)
from app.application.safety.untrusted_text import sanitize_untrusted_text
from app.application.shared.ownership import require_owned_contact
from app.application.shared.telemetry import brew_span
from app.domain.contacts.ports import ContactReaderPort
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingReaderPort
from app.domain.meetings.types import MeetingPurpose, MeetingStatus
from app.domain.memory.ports import (
    ApprovedMemoryReaderPort,
    MemoryProposalAgentPort,
    PendingMemoryProposalStagerPort,
    UserPreferencesReaderPort,
)
from app.domain.memory.types import MemoryScope, MemorySourceType
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthorizationError
from app.domain.shared.ports import IdGeneratorPort


class ConversationCoachService:
    """Orchestrates least-privilege reads and pending-proposal staging for coaching tools."""

    def __init__(
        self,
        *,
        preferences_reader: UserPreferencesReaderPort,
        contact_reader: ContactReaderPort,
        meeting_reader: MeetingReaderPort,
        memory_reader: ApprovedMemoryReaderPort,
        proposal_stager: PendingMemoryProposalStagerPort,
        proposal_agent: MemoryProposalAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._preferences_reader = preferences_reader
        self._contact_reader = contact_reader
        self._meeting_reader = meeting_reader
        self._memory_reader = memory_reader
        self._staging = MemoryCandidateStagingPipeline(
            memory_reader=memory_reader,
            proposal_stager=proposal_stager,
            proposal_agent=proposal_agent,
            clock=clock,
            id_generator=id_generator,
        )

    async def get_user_preferences(
        self,
        *,
        principal: AuthenticatedPrincipal,
        max_preference_memories: int = 5,
    ) -> UserPreferencesProjection:
        """Load caller-owned coaching defaults and approved user-preference memories."""
        uid = principal.user_id
        prefs, raw_memories = await asyncio.gather(
            self._preferences_reader.get_by_owner(uid),
            self._memory_reader.list_by_owner(
                uid,
                scope=MemoryScope.USER_PREFERENCE,
                include_revoked=False,
            ),
        )
        if prefs is not None and prefs.owner_user_id != uid:
            raise AuthorizationError()

        eligible_memories = [
            mem
            for mem in raw_memories
            if mem.owner_user_id == uid
            and mem.is_active
            and mem.scope is MemoryScope.USER_PREFERENCE
        ]
        ranked = sorted(
            eligible_memories,
            key=lambda mem: memory_relevance_key(mem, objective_tokens=set()),
            reverse=True,
        )
        was_truncated = len(ranked) > max_preference_memories

        injection_detected = False
        style_notes: str | None = None
        focus_areas: list[str] = []

        if prefs is not None:
            if prefs.communication_style_notes:
                sanitized_style = sanitize_untrusted_text(
                    prefs.communication_style_notes,
                    max_chars=500,
                )
                style_notes = sanitized_style.text
                injection_detected = injection_detected or sanitized_style.injection_detected
            for area in prefs.focus_areas:
                sanitized_area = sanitize_untrusted_text(area, max_chars=80)
                injection_detected = injection_detected or sanitized_area.injection_detected
                if sanitized_area.text:
                    focus_areas.append(sanitized_area.text)

        projected_memories: list[ProjectedMemorySummary] = []
        for mem in ranked[:max_preference_memories]:
            sanitized_mem = sanitize_untrusted_text(mem.text, max_chars=400)
            injection_detected = injection_detected or sanitized_mem.injection_detected
            projected_memories.append(
                ProjectedMemorySummary(
                    memory_id=mem.id,
                    memory_type=mem.memory_type.value,
                    text=sanitized_mem.text,
                )
            )

        return UserPreferencesProjection(
            has_saved_preferences=prefs is not None,
            default_tone=prefs.default_tone.value if prefs is not None else None,
            default_duration_minutes=(
                prefs.default_duration_minutes if prefs is not None else None
            ),
            preferred_question_count=(
                prefs.preferred_question_count if prefs is not None else None
            ),
            communication_style_notes=style_notes,
            focus_areas=focus_areas,
            approved_preference_memories=projected_memories,
            was_truncated=was_truncated,
            injection_detected=injection_detected,
        )

    async def get_contact_context(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
        meeting_objective: str | None = None,
        max_memories: int = 5,
    ) -> ContactContextProjection:
        """Load an owned contact profile and ranked approved contact memories."""
        uid = principal.user_id
        contact = await require_owned_contact(self._contact_reader, uid, contact_id)

        raw_memories = await self._memory_reader.list_by_owner(
            uid,
            scope=MemoryScope.CONTACT,
            contact_id=contact.id,
            include_revoked=False,
        )
        eligible_memories = [
            mem
            for mem in raw_memories
            if mem.owner_user_id == uid
            and mem.is_active
            and mem.scope is MemoryScope.CONTACT
            and mem.contact_id == contact.id
        ]

        objective_tokens = tokenize_keywords(meeting_objective)
        ranked = sorted(
            eligible_memories,
            key=lambda mem: memory_relevance_key(mem, objective_tokens=objective_tokens),
            reverse=True,
        )
        was_truncated = len(ranked) > max_memories

        injection_detected = False
        sanitized_notes: str | None = None
        if contact.context_notes:
            notes_res = sanitize_untrusted_text(contact.context_notes, max_chars=600)
            sanitized_notes = notes_res.text
            injection_detected = injection_detected or notes_res.injection_detected

        projected_memories: list[ProjectedMemorySummary] = []
        for mem in ranked[:max_memories]:
            mem_res = sanitize_untrusted_text(mem.text, max_chars=400)
            injection_detected = injection_detected or mem_res.injection_detected
            projected_memories.append(
                ProjectedMemorySummary(
                    memory_id=mem.id,
                    memory_type=mem.memory_type.value,
                    text=mem_res.text,
                )
            )

        has_prior_context = bool(
            contact.title
            or contact.role
            or contact.organization
            or sanitized_notes
            or projected_memories
        )

        return ContactContextProjection(
            contact_id=contact.id,
            name=contact.name,
            title=contact.title,
            role=contact.role,
            organization=contact.organization,
            context_notes=sanitized_notes,
            approved_memories=projected_memories,
            has_prior_context=has_prior_context,
            was_truncated=was_truncated,
            injection_detected=injection_detected,
        )

    async def get_meeting_history(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str | None = None,
        purpose: MeetingPurpose | None = None,
        objective_hint: str | None = None,
        limit: int = 5,
    ) -> MeetingHistoryProjection:
        """Load bounded non-cancelled meeting history strictly owned by ``principal``."""
        uid = principal.user_id
        resolved_contact_id: str | None = None
        if contact_id is not None:
            contact = await require_owned_contact(self._contact_reader, uid, contact_id)
            resolved_contact_id = contact.id

        raw_meetings = await self._meeting_reader.list_by_owner(
            uid,
            contact_id=resolved_contact_id,
        )
        eligible = [
            mtg
            for mtg in raw_meetings
            if mtg.owner_user_id == uid
            and mtg.status is not MeetingStatus.CANCELLED
            and (resolved_contact_id is None or mtg.contact_id == resolved_contact_id)
        ]

        objective_tokens = tokenize_keywords(objective_hint)
        ranked = sorted(
            eligible,
            key=lambda mtg: meeting_relevance_key(
                mtg,
                target_purpose=purpose,
                objective_tokens=objective_tokens,
            ),
            reverse=True,
        )
        was_truncated = len(ranked) > limit

        injection_detected = False
        projected_items: list[ProjectedMeetingHistoryItem] = []
        for mtg in ranked[:limit]:
            obj_res = sanitize_untrusted_text(mtg.objective, max_chars=240)
            injection_detected = injection_detected or obj_res.injection_detected

            excerpt: str | None = None
            if mtg.notes:
                notes_res = sanitize_untrusted_text(mtg.notes, max_chars=280)
                excerpt = notes_res.text
                injection_detected = injection_detected or notes_res.injection_detected

            projected_items.append(
                ProjectedMeetingHistoryItem(
                    meeting_id=mtg.id,
                    contact_id=mtg.contact_id,
                    purpose=mtg.purpose.value,
                    tone=mtg.tone.value,
                    objective=obj_res.text,
                    duration_minutes=mtg.duration_minutes,
                    status=mtg.status.value,
                    scheduled_at_utc=(
                        mtg.scheduled_at.isoformat() if mtg.scheduled_at is not None else None
                    ),
                    notes_excerpt=excerpt,
                )
            )

        return MeetingHistoryProjection(
            meetings=projected_items,
            total_returned=len(projected_items),
            was_truncated=was_truncated,
            injection_detected=injection_detected,
        )

    async def suggest_memory_candidates(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        contact_id: str | None = None,
        meeting_id: str | None = None,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        max_candidates: int = 5,
    ) -> SuggestedMemoryCandidatesProjection:
        """Extract PII-scrubbed, injection-filtered memory candidates as pending proposals.

        Runs the same staging pipeline as the HTTP API. Unlike the API, notes with nothing
        to remember are not an error here: the tool returns an empty result so the model
        can carry on, and at most ``max_candidates`` proposals are staged per call.
        """
        uid = principal.user_id
        with brew_span(
            STAGING_SPAN_NAME,
            operation_name=STAGING_OPERATION_NAME,
            tracer_name=__name__,
        ) as tracker:
            meeting, _brief, contact = await resolve_proposal_references(
                owner_user_id=uid,
                meeting_id=meeting_id,
                contact_id=contact_id,
                meeting_reader=self._meeting_reader,
                contact_reader=self._contact_reader,
            )
            outcome = await self._staging.stage(
                owner_user_id=uid,
                notes=notes,
                source_type=source_type,
                meeting=meeting,
                contact=contact,
                max_candidates=max_candidates,
            )
            record_staging_outcome(tracker, outcome)

        staged_items = [
            StagedMemoryCandidateProjection(
                proposal_id=saved.id,
                scope=saved.scope.value,
                contact_id=saved.contact_id,
                memory_type=saved.memory_type.value,
                text=saved.text,
                rationale=saved.rationale,
            )
            for saved in outcome.proposals
        ]
        return SuggestedMemoryCandidatesProjection(
            candidates=staged_items,
            total_suggested=len(staged_items),
            # The tool contract reports one number for everything withheld as unsafe.
            filtered_untrusted_directives=(
                outcome.filtered_directive_count + outcome.filtered_sensitive_count
            ),
        )
