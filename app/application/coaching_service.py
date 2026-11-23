"""Least-privilege application service powering Brew's ADK ``conversation_coach`` tools.

Enforces caller ownership, minimal data projection, PII redaction, untrusted-note
prompt-injection sanitization, and human-in-the-loop staging separation without
importing ADK, FastAPI, or Firestore SDKs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import ValidationError

from app.application.memory_persistence_service import translate_pydantic_error
from app.application.memory_retrieval_service import (
    _meeting_relevance_key,
    _memory_relevance_key,
    _tokenize_keywords,
)
from app.application.untrusted_data import (
    contains_prompt_injection,
    sanitize_untrusted_text,
    split_safe_note_segments,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
)
from app.domain.health import ClockPort
from app.domain.models import (
    AuthenticatedPrincipal,
    Contact,
    Meeting,
    Memory,
    MemoryProposal,
    MemorySource,
    UserPreferences,
)
from app.domain.ports import (
    ApprovedMemoryReaderPort,
    ContactReaderPort,
    IdGeneratorPort,
    MeetingReaderPort,
    MemoryProposalAgentPort,
    PendingMemoryProposalStagerPort,
    UserPreferencesReaderPort,
)
from app.domain.types import (
    ConsentStatus,
    MeetingPurpose,
    MeetingStatus,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)


@dataclass(frozen=True, slots=True)
class ProjectedMemorySummary:
    """Minimal, PII-scrubbed approved memory projection safe for LLM context."""

    memory_id: str
    memory_type: str
    text: str


@dataclass(frozen=True, slots=True)
class UserPreferencesProjection:
    """Minimal projection of a user's coaching preferences and preference memories."""

    has_saved_preferences: bool
    default_tone: str | None
    default_duration_minutes: int | None
    preferred_question_count: int | None
    communication_style_notes: str | None
    focus_areas: list[str]
    approved_preference_memories: list[ProjectedMemorySummary]
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class ContactContextProjection:
    """Minimal projection of an owned contact profile and approved contact memories."""

    contact_id: str
    name: str
    title: str | None
    role: str | None
    organization: str | None
    context_notes: str | None
    approved_memories: list[ProjectedMemorySummary]
    has_prior_context: bool
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class ProjectedMeetingHistoryItem:
    """Minimal projection of a past or planned meeting with sanitized notes excerpt."""

    meeting_id: str
    contact_id: str
    purpose: str
    tone: str
    objective: str
    duration_minutes: int
    status: str
    scheduled_at_utc: str | None
    notes_excerpt: str | None


@dataclass(frozen=True, slots=True)
class MeetingHistoryProjection:
    """Bounded list of relevant meetings belonging to the authenticated caller."""

    meetings: list[ProjectedMeetingHistoryItem]
    total_returned: int
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class StagedMemoryCandidateProjection:
    """Minimal summary of a staged ``pending`` memory proposal awaiting human review."""

    proposal_id: str
    scope: str
    contact_id: str | None
    memory_type: str
    text: str
    rationale: str


@dataclass(frozen=True, slots=True)
class SuggestedMemoryCandidatesProjection:
    """Result of extracting and staging candidate memories from untrusted notes."""

    candidates: list[StagedMemoryCandidateProjection]
    total_suggested: int
    filtered_untrusted_directives: int


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
        self._proposal_stager = proposal_stager
        self._proposal_agent = proposal_agent
        self._clock = clock
        self._id_generator = id_generator

    async def _require_owned_contact(self, uid: str, contact_id: str) -> Contact:
        contact = await self._contact_reader.get_for_owner(uid, contact_id)
        if contact is None:
            if await self._contact_reader.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        if contact.owner_user_id != uid:
            raise AuthorizationError()
        return contact

    async def _require_owned_meeting(self, uid: str, meeting_id: str) -> Meeting:
        meeting = await self._meeting_reader.get_for_owner(uid, meeting_id)
        if meeting is None:
            if await self._meeting_reader.exists_for_any_owner(meeting_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting_id)
        if meeting.owner_user_id != uid:
            raise AuthorizationError()
        return meeting

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
            and mem.consent_status is ConsentStatus.APPROVED
            and mem.scope is MemoryScope.USER_PREFERENCE
        ]
        ranked = sorted(
            eligible_memories,
            key=lambda mem: _memory_relevance_key(mem, objective_tokens=set()),
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
        contact = await self._require_owned_contact(uid, contact_id)

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
            and mem.consent_status is ConsentStatus.APPROVED
            and mem.scope is MemoryScope.CONTACT
            and mem.contact_id == contact.id
        ]

        objective_tokens = _tokenize_keywords(meeting_objective)
        ranked = sorted(
            eligible_memories,
            key=lambda mem: _memory_relevance_key(mem, objective_tokens=objective_tokens),
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
            contact = await self._require_owned_contact(uid, contact_id)
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

        objective_tokens = _tokenize_keywords(objective_hint)
        ranked = sorted(
            eligible,
            key=lambda mtg: _meeting_relevance_key(
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
        """Extract PII-scrubbed, injection-filtered memory candidates as pending proposals."""
        uid = principal.user_id

        meeting: Meeting | None = None
        if meeting_id is not None:
            meeting = await self._require_owned_meeting(uid, meeting_id)
            if contact_id is not None and contact_id != meeting.contact_id:
                raise DomainValidationError(
                    "Provided contact_id does not match the specified meeting's contact_id."
                )
            contact_id = meeting.contact_id

        contact: Contact | None = None
        if contact_id is not None:
            contact = await self._require_owned_contact(uid, contact_id)

        safe_segments, dropped_directives = split_safe_note_segments(notes)
        if not safe_segments:
            return SuggestedMemoryCandidatesProjection(
                candidates=[],
                total_suggested=0,
                filtered_untrusted_directives=dropped_directives,
            )

        existing_memories = [
            mem
            for mem in await self._memory_reader.list_by_owner(uid, include_revoked=False)
            if mem.owner_user_id == uid
        ]
        existing_texts = {mem.text.strip().lower() for mem in existing_memories}

        safe_joined_notes = ". ".join(safe_segments)
        proposed = await self._proposal_agent.propose_memories(
            notes=safe_joined_notes,
            meeting=meeting,
            contact=contact,
            existing_memories=existing_memories,
        )

        now = self._clock.now_utc()
        staged_items: list[StagedMemoryCandidateProjection] = []
        for candidate in proposed:
            if len(staged_items) >= max_candidates:
                break
            if contains_prompt_injection(candidate.text):
                dropped_directives += 1
                continue
            sanitized_text = sanitize_untrusted_text(candidate.text, max_chars=1000)
            if sanitized_text.injection_detected or len(sanitized_text.text) < 3:
                dropped_directives += 1
                continue
            if sanitized_text.text.lower() in existing_texts:
                continue

            sanitized_rationale = sanitize_untrusted_text(candidate.rationale, max_chars=500)
            sanitized_excerpt = (
                sanitize_untrusted_text(candidate.excerpt, max_chars=500).text
                if candidate.excerpt
                else None
            )

            resolved_contact_id = (
                contact.id
                if candidate.scope is MemoryScope.CONTACT and contact is not None
                else candidate.contact_id
            )
            try:
                source = MemorySource(
                    source_type=source_type,
                    meeting_id=meeting.id if meeting is not None else None,
                    brief_id=None,
                    proposal_id=None,
                    excerpt=sanitized_excerpt,
                    recorded_at=now,
                )
                proposal = MemoryProposal(
                    id=self._id_generator.new_id("prop"),
                    owner_user_id=uid,
                    scope=candidate.scope,
                    contact_id=resolved_contact_id,
                    memory_type=candidate.memory_type,
                    text=sanitized_text.text,
                    rationale=sanitized_rationale.text,
                    source=source,
                    status=ProposalStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            except ValidationError as exc:
                raise translate_pydantic_error(exc) from exc

            saved = await self._proposal_stager.save(proposal)
            existing_texts.add(saved.text.strip().lower())
            staged_items.append(
                StagedMemoryCandidateProjection(
                    proposal_id=saved.id,
                    scope=saved.scope.value,
                    contact_id=saved.contact_id,
                    memory_type=saved.memory_type.value,
                    text=saved.text,
                    rationale=saved.rationale,
                )
            )

        return SuggestedMemoryCandidatesProjection(
            candidates=staged_items,
            total_suggested=len(staged_items),
            filtered_untrusted_directives=dropped_directives,
        )


class ReadOnlyPreferencesFacade:
    """Capability-restricted proxy exposing only ``get_by_owner``."""

    def __init__(self, reader: UserPreferencesReaderPort) -> None:
        self._reader = reader

    async def get_by_owner(self, owner_user_id: str) -> UserPreferences | None:
        return await self._reader.get_by_owner(owner_user_id)


class ReadOnlyContactFacade:
    """Capability-restricted proxy exposing only owner-scoped contact reads."""

    def __init__(self, reader: ContactReaderPort) -> None:
        self._reader = reader

    async def get_for_owner(self, owner_user_id: str, contact_id: str) -> Contact | None:
        return await self._reader.get_for_owner(owner_user_id, contact_id)

    async def exists_for_any_owner(self, contact_id: str) -> bool:
        return await self._reader.exists_for_any_owner(contact_id)


class ReadOnlyMeetingFacade:
    """Capability-restricted proxy exposing only owner-scoped meeting reads."""

    def __init__(self, reader: MeetingReaderPort) -> None:
        self._reader = reader

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Meeting | None:
        return await self._reader.get_for_owner(owner_user_id, meeting_id)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        return await self._reader.exists_for_any_owner(meeting_id)

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        return await self._reader.list_by_owner(owner_user_id, contact_id=contact_id)


class ReadOnlyApprovedMemoryFacade:
    """Capability-restricted proxy exposing only consented memory listing (no writes/deletes)."""

    def __init__(self, reader: ApprovedMemoryReaderPort) -> None:
        self._reader = reader

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        del include_revoked  # Agent tools may never request revoked memories.
        return await self._reader.list_by_owner(
            owner_user_id,
            scope=scope,
            contact_id=contact_id,
            memory_type=memory_type,
            include_revoked=False,
        )


class PendingProposalOnlyFacade:
    """Capability-restricted proxy allowing only new ``PENDING`` proposal creation."""

    def __init__(self, stager: PendingMemoryProposalStagerPort) -> None:
        self._stager = stager

    async def save(
        self,
        proposal: MemoryProposal,
        *,
        expected_version: int | None = None,
    ) -> MemoryProposal:
        if expected_version is not None or proposal.status is not ProposalStatus.PENDING:
            raise ConflictError(
                "Agent tools may only stage new pending memory proposals.",
                code="AGENT_WRITE_RESTRICTED",
            )
        return await self._stager.save(proposal, expected_version=None)
