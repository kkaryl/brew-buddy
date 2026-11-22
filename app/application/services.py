"""Application services orchestrating Brew domain workflows through injected ports."""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from app.domain.errors import (
    AuthorizationError,
    DomainValidationError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.health import ClockPort
from app.domain.models import (
    AuthenticatedPrincipal,
    Contact,
    Meeting,
    Memory,
    MemoryProposal,
    MemorySource,
    PreparationBrief,
    UserPreferences,
)
from app.domain.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    ContactRepository,
    IdGeneratorPort,
    MeetingRepository,
    MemoryProposalAgentPort,
    MemoryProposalRepository,
    MemoryRepository,
    UserPreferencesRepository,
)
from app.domain.types import (
    ConsentStatus,
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryScope,
    MemorySourceType,
    MemoryType,
)

logger = logging.getLogger(__name__)


def _translate_pydantic_error(exc: ValidationError) -> DomainValidationError:
    first = exc.errors()[0] if exc.errors() else None
    if first is not None:
        loc = ".".join(str(part) for part in first.get("loc", ()))
        msg = str(first.get("msg", "Invalid domain value."))
        summary = f"{loc}: {msg}" if loc else msg
    else:
        summary = "Domain validation failed."
    return DomainValidationError(summary)


class ContactService:
    """Application use cases for counterpart contact management."""

    def __init__(
        self,
        *,
        contact_repo: ContactRepository,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._contact_repo = contact_repo
        self._clock = clock
        self._id_generator = id_generator

    def create_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        name: str,
        title: str | None = None,
        role: str | None = None,
        organization: str | None = None,
        context_notes: str | None = None,
    ) -> Contact:
        """Create and persist a new contact owned by ``principal``."""
        now = self._clock.now_utc()
        try:
            contact = Contact(
                id=self._id_generator.new_id("cnt"),
                owner_user_id=principal.user_id,
                name=name,
                title=title,
                role=role,
                organization=organization,
                context_notes=context_notes,
                created_at=now,
                updated_at=now,
                version=1,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        saved = self._contact_repo.save(contact)
        logger.info(
            "Contact created",
            extra={"event_type": "contact.created"},
        )
        return saved

    def list_contacts(self, *, principal: AuthenticatedPrincipal) -> list[Contact]:
        """List contacts belonging to ``principal``."""
        return self._contact_repo.list_by_owner(principal.user_id)

    def get_owned_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
    ) -> Contact:
        """Fetch a contact and enforce caller ownership."""
        contact = self._contact_repo.get_by_id(contact_id)
        if contact is None:
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        if contact.owner_user_id != principal.user_id:
            raise AuthorizationError()
        return contact


class MeetingService:
    """Application use cases for inspecting user meetings."""

    def __init__(
        self,
        *,
        meeting_repo: MeetingRepository,
        contact_repo: ContactRepository,
    ) -> None:
        self._meeting_repo = meeting_repo
        self._contact_repo = contact_repo

    def list_meetings(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings owned by ``principal``, validating optional ``contact_id`` ownership."""
        if contact_id is not None:
            contact = self._contact_repo.get_by_id(contact_id)
            if contact is None:
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
            if contact.owner_user_id != principal.user_id:
                raise AuthorizationError()
        return self._meeting_repo.list_by_owner(principal.user_id, contact_id=contact_id)


class BriefService:
    """Application use cases for generating, retrieving, and revising preparation briefs."""

    def __init__(
        self,
        *,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        memory_repo: MemoryRepository,
        preferences_repo: UserPreferencesRepository,
        brief_agent: BriefCoachAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._memory_repo = memory_repo
        self._preferences_repo = preferences_repo
        self._brief_agent = brief_agent
        self._clock = clock
        self._id_generator = id_generator

    def generate_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
        purpose: MeetingPurpose,
        tone: MeetingTone,
        meeting_objective: str,
        duration_minutes: int,
        scheduled_at: datetime | None = None,
        meeting_notes: str | None = None,
        preferred_question_count: int | None = None,
        communication_style_notes: str | None = None,
        focus_areas: list[str] | None = None,
    ) -> PreparationBrief:
        """Create a meeting record and synthesize a grounded preparation brief."""
        contact = self._contact_repo.get_by_id(contact_id)
        if contact is None:
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        if contact.owner_user_id != principal.user_id:
            raise AuthorizationError()

        now = self._clock.now_utc()
        effective_preferences = self._resolve_user_preferences(
            principal=principal,
            now=now,
            preferred_question_count=preferred_question_count,
            communication_style_notes=communication_style_notes,
            focus_areas=focus_areas,
        )

        meeting_id = self._id_generator.new_id("mtg")
        brief_id = self._id_generator.new_id("brf")

        try:
            meeting = Meeting(
                id=meeting_id,
                owner_user_id=principal.user_id,
                contact_id=contact.id,
                purpose=purpose,
                tone=tone,
                objective=meeting_objective,
                duration_minutes=duration_minutes,
                scheduled_at=scheduled_at,
                notes=meeting_notes,
                status=MeetingStatus.PREPARING,
                latest_brief_id=brief_id,
                created_at=now,
                updated_at=now,
                version=1,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        approved_memories = self._collect_grounding_memories(
            owner_user_id=principal.user_id,
            contact_id=contact.id,
        )

        generated = self._brief_agent.generate_brief(
            meeting=meeting,
            contact=contact,
            user_preferences=effective_preferences,
            approved_memories=approved_memories,
        )

        try:
            brief = PreparationBrief(
                id=brief_id,
                owner_user_id=principal.user_id,
                meeting_id=meeting.id,
                contact_id=contact.id,
                duration_minutes=meeting.duration_minutes,
                tone=meeting.tone,
                contact_context=generated.contact_context,
                meeting_objective=generated.meeting_objective,
                conversation_openers=generated.conversation_openers,
                time_boxed_agenda=generated.time_boxed_agenda,
                suggested_questions=generated.suggested_questions,
                suggested_follow_up_topics=generated.suggested_follow_up_topics,
                referenced_memory_ids=generated.referenced_memory_ids,
                revision_summary=generated.revision_summary,
                version=1,
                created_at=now,
                updated_at=now,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        self._meeting_repo.save(meeting)
        saved_brief = self._brief_repo.save(brief)
        logger.info(
            "Preparation brief generated",
            extra={"event_type": "brief.generated"},
        )
        return saved_brief

    def get_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
    ) -> PreparationBrief:
        """Fetch a preparation brief and verify caller ownership."""
        brief = self._brief_repo.get_by_id(brief_id)
        if brief is None:
            raise EntityNotFoundError(entity_name="PreparationBrief", entity_id=brief_id)
        if brief.owner_user_id != principal.user_id:
            raise AuthorizationError()
        return brief

    def revise_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
        instructions: str,
        expected_version: int,
        duration_minutes: int | None = None,
        tone: MeetingTone | None = None,
    ) -> PreparationBrief:
        """Revise an existing preparation brief enforcing optimistic version control."""
        current_brief = self.get_brief(principal=principal, brief_id=brief_id)
        if current_brief.version != expected_version:
            raise VersionConflictError(
                entity_name="PreparationBrief",
                entity_id=brief_id,
                expected_version=expected_version,
                actual_version=current_brief.version,
            )

        meeting = self._meeting_repo.get_by_id(current_brief.meeting_id)
        if meeting is None:
            raise EntityNotFoundError(
                entity_name="Meeting",
                entity_id=current_brief.meeting_id,
            )
        contact = self._contact_repo.get_by_id(current_brief.contact_id)
        if contact is None:
            raise EntityNotFoundError(
                entity_name="Contact",
                entity_id=current_brief.contact_id,
            )

        target_duration = (
            duration_minutes if duration_minutes is not None else current_brief.duration_minutes
        )
        target_tone = tone if tone is not None else current_brief.tone
        preferences = self._preferences_repo.get_by_owner(principal.user_id)
        approved_memories = self._collect_grounding_memories(
            owner_user_id=principal.user_id,
            contact_id=contact.id,
        )

        revised_content = self._brief_agent.revise_brief(
            current_brief=current_brief,
            meeting=meeting,
            contact=contact,
            instructions=instructions,
            target_duration_minutes=target_duration,
            target_tone=target_tone,
            user_preferences=preferences,
            approved_memories=approved_memories,
        )

        now = max(self._clock.now_utc(), current_brief.created_at)
        try:
            revised_brief = PreparationBrief(
                id=current_brief.id,
                owner_user_id=current_brief.owner_user_id,
                meeting_id=current_brief.meeting_id,
                contact_id=current_brief.contact_id,
                duration_minutes=target_duration,
                tone=target_tone,
                contact_context=revised_content.contact_context,
                meeting_objective=revised_content.meeting_objective,
                conversation_openers=revised_content.conversation_openers,
                time_boxed_agenda=revised_content.time_boxed_agenda,
                suggested_questions=revised_content.suggested_questions,
                suggested_follow_up_topics=revised_content.suggested_follow_up_topics,
                referenced_memory_ids=revised_content.referenced_memory_ids,
                revision_summary=revised_content.revision_summary or instructions,
                version=current_brief.version + 1,
                created_at=current_brief.created_at,
                updated_at=now,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        saved_brief = self._brief_repo.save(revised_brief, expected_version=expected_version)

        if target_duration != meeting.duration_minutes or target_tone != meeting.tone:
            updated_meeting = Meeting(
                id=meeting.id,
                owner_user_id=meeting.owner_user_id,
                contact_id=meeting.contact_id,
                purpose=meeting.purpose,
                tone=target_tone,
                objective=revised_brief.meeting_objective,
                duration_minutes=target_duration,
                scheduled_at=meeting.scheduled_at,
                notes=meeting.notes,
                status=meeting.status,
                latest_brief_id=saved_brief.id,
                created_at=meeting.created_at,
                updated_at=max(now, meeting.created_at),
                version=meeting.version + 1,
            )
            self._meeting_repo.save(updated_meeting, expected_version=meeting.version)

        logger.info(
            "Preparation brief revised",
            extra={"event_type": "brief.revised"},
        )
        return saved_brief

    def _collect_grounding_memories(
        self,
        *,
        owner_user_id: str,
        contact_id: str,
    ) -> list[Memory]:
        preference_memories = self._memory_repo.list_by_owner(
            owner_user_id,
            scope=MemoryScope.USER_PREFERENCE,
            include_revoked=False,
        )
        contact_memories = self._memory_repo.list_by_owner(
            owner_user_id,
            scope=MemoryScope.CONTACT,
            contact_id=contact_id,
            include_revoked=False,
        )
        return [*preference_memories, *contact_memories]

    def _resolve_user_preferences(
        self,
        *,
        principal: AuthenticatedPrincipal,
        now: datetime,
        preferred_question_count: int | None,
        communication_style_notes: str | None,
        focus_areas: list[str] | None,
    ) -> UserPreferences | None:
        stored = self._preferences_repo.get_by_owner(principal.user_id)
        has_overrides = (
            preferred_question_count is not None
            or communication_style_notes is not None
            or focus_areas is not None
        )
        if not has_overrides:
            return stored

        try:
            if stored is None:
                prefs = UserPreferences(
                    id=self._id_generator.new_id("pref"),
                    owner_user_id=principal.user_id,
                    preferred_question_count=preferred_question_count or 4,
                    communication_style_notes=communication_style_notes,
                    focus_areas=focus_areas or [],
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                return self._preferences_repo.save(prefs)

            updated_prefs = UserPreferences(
                id=stored.id,
                owner_user_id=stored.owner_user_id,
                default_tone=stored.default_tone,
                default_duration_minutes=stored.default_duration_minutes,
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
                focus_areas=(focus_areas if focus_areas is not None else stored.focus_areas),
                created_at=stored.created_at,
                updated_at=max(now, stored.created_at),
                version=stored.version + 1,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        return self._preferences_repo.save(updated_prefs, expected_version=stored.version)


class MemoryService:
    """Application use cases governing separated memory proposals and approved memories."""

    def __init__(
        self,
        *,
        proposal_repo: MemoryProposalRepository,
        memory_repo: MemoryRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        proposal_agent: MemoryProposalAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._proposal_repo = proposal_repo
        self._memory_repo = memory_repo
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._proposal_agent = proposal_agent
        self._clock = clock
        self._id_generator = id_generator

    def propose_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> list[MemoryProposal]:
        """Extract candidate memories from notes and store them strictly as proposals."""
        meeting: Meeting | None = None
        if meeting_id is not None:
            meeting = self._meeting_repo.get_by_id(meeting_id)
            if meeting is None:
                raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting_id)
            if meeting.owner_user_id != principal.user_id:
                raise AuthorizationError()
            if contact_id is not None and contact_id != meeting.contact_id:
                raise DomainValidationError(
                    "Provided contact_id does not match the specified meeting's contact_id."
                )
            contact_id = meeting.contact_id

        brief: PreparationBrief | None = None
        if brief_id is not None:
            brief = self._brief_repo.get_by_id(brief_id)
            if brief is None:
                raise EntityNotFoundError(
                    entity_name="PreparationBrief",
                    entity_id=brief_id,
                )
            if brief.owner_user_id != principal.user_id:
                raise AuthorizationError()
            if meeting is not None and brief.meeting_id != meeting.id:
                raise DomainValidationError(
                    "Provided brief_id does not belong to the specified meeting."
                )
            if contact_id is not None and contact_id != brief.contact_id:
                raise DomainValidationError(
                    "Provided contact_id does not match the specified brief's contact_id."
                )
            contact_id = brief.contact_id

        contact: Contact | None = None
        if contact_id is not None:
            contact = self._contact_repo.get_by_id(contact_id)
            if contact is None:
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
            if contact.owner_user_id != principal.user_id:
                raise AuthorizationError()

        existing_memories = self._memory_repo.list_by_owner(
            principal.user_id,
            include_revoked=False,
        )
        candidates = self._proposal_agent.propose_memories(
            notes=notes,
            meeting=meeting,
            contact=contact,
            existing_memories=existing_memories,
        )
        if not candidates:
            raise DomainValidationError("No candidate memories could be extracted from notes.")

        now = self._clock.now_utc()
        saved_proposals: list[MemoryProposal] = []
        for candidate in candidates:
            resolved_contact_id = (
                contact.id
                if candidate.scope is MemoryScope.CONTACT and contact is not None
                else candidate.contact_id
            )
            resolved_meeting_id = (
                meeting.id
                if meeting is not None
                else (brief.meeting_id if brief is not None else None)
            )
            try:
                source = MemorySource(
                    source_type=source_type,
                    meeting_id=resolved_meeting_id,
                    brief_id=brief.id if brief is not None else None,
                    proposal_id=None,
                    excerpt=candidate.excerpt,
                    recorded_at=now,
                )
                proposal = MemoryProposal(
                    id=self._id_generator.new_id("prop"),
                    owner_user_id=principal.user_id,
                    scope=candidate.scope,
                    contact_id=resolved_contact_id,
                    memory_type=candidate.memory_type,
                    text=candidate.text,
                    rationale=candidate.rationale,
                    source=source,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            except ValidationError as exc:
                raise _translate_pydantic_error(exc) from exc

            saved_proposals.append(self._proposal_repo.save(proposal))

        logger.info(
            "Memory proposals staged for human review",
            extra={"event_type": "memory.proposals_created"},
        )
        return saved_proposals

    def approve_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None = None,
        memory_type: MemoryType | None = None,
    ) -> Memory:
        """Promote a pending proposal into durable approved memory storage."""
        proposal = self._proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            raise EntityNotFoundError(entity_name="MemoryProposal", entity_id=proposal_id)
        if proposal.owner_user_id != principal.user_id:
            raise AuthorizationError()
        if proposal.version != expected_version:
            raise VersionConflictError(
                entity_name="MemoryProposal",
                entity_id=proposal_id,
                expected_version=expected_version,
                actual_version=proposal.version,
            )

        now = max(self._clock.now_utc(), proposal.created_at)
        memory_id = self._id_generator.new_id("mem")

        try:
            approved_source = MemorySource(
                source_type=proposal.source.source_type,
                meeting_id=proposal.source.meeting_id,
                brief_id=proposal.source.brief_id,
                proposal_id=proposal.id,
                excerpt=proposal.source.excerpt,
                recorded_at=proposal.source.recorded_at,
            )
            memory = Memory(
                id=memory_id,
                owner_user_id=principal.user_id,
                scope=proposal.scope,
                contact_id=proposal.contact_id,
                memory_type=(memory_type if memory_type is not None else proposal.memory_type),
                text=edited_text if edited_text is not None else proposal.text,
                source=approved_source,
                consent_status=ConsentStatus.APPROVED,
                created_at=now,
                updated_at=now,
                version=1,
            )
            reviewed_proposal = proposal.mark_approved(
                approved_memory_id=memory.id,
                reviewed_at=now,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        self._proposal_repo.save(reviewed_proposal, expected_version=expected_version)
        saved_memory = self._memory_repo.save(memory)
        logger.info(
            "Memory proposal approved and persisted",
            extra={"event_type": "memory.approved"},
        )
        return saved_memory

    def list_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        """List approved memories owned by ``principal`` (never returns unapproved proposals)."""
        if scope is MemoryScope.USER_PREFERENCE and contact_id is not None:
            raise DomainValidationError(
                "contact_id filter cannot be combined with scope='user_preference'."
            )
        if contact_id is not None:
            contact = self._contact_repo.get_by_id(contact_id)
            if contact is None:
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
            if contact.owner_user_id != principal.user_id:
                raise AuthorizationError()

        return self._memory_repo.list_by_owner(
            principal.user_id,
            scope=scope,
            contact_id=contact_id,
            memory_type=memory_type,
            include_revoked=include_revoked,
        )

    def update_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int,
        text: str | None = None,
        memory_type: MemoryType | None = None,
        consent_status: ConsentStatus | None = None,
    ) -> Memory:
        """Update an approved memory enforcing optimistic concurrency control."""
        memory = self._memory_repo.get_by_id(memory_id)
        if memory is None:
            raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
        if memory.owner_user_id != principal.user_id:
            raise AuthorizationError()
        if memory.version != expected_version:
            raise VersionConflictError(
                entity_name="Memory",
                entity_id=memory_id,
                expected_version=expected_version,
                actual_version=memory.version,
            )

        now = max(self._clock.now_utc(), memory.created_at)
        try:
            updated = memory.apply_update(
                text=text,
                memory_type=memory_type,
                consent_status=consent_status,
                updated_at=now,
            )
        except ValidationError as exc:
            raise _translate_pydantic_error(exc) from exc

        saved = self._memory_repo.save(updated, expected_version=expected_version)
        logger.info(
            "Approved memory updated",
            extra={"event_type": "memory.updated"},
        )
        return saved

    def delete_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int | None = None,
    ) -> None:
        """Delete an approved memory enforcing ownership and optional version check."""
        memory = self._memory_repo.get_by_id(memory_id)
        if memory is None:
            raise EntityNotFoundError(entity_name="Memory", entity_id=memory_id)
        if memory.owner_user_id != principal.user_id:
            raise AuthorizationError()
        if expected_version is not None and memory.version != expected_version:
            raise VersionConflictError(
                entity_name="Memory",
                entity_id=memory_id,
                expected_version=expected_version,
                actual_version=memory.version,
            )

        self._memory_repo.delete(memory_id, expected_version=expected_version)
        logger.info(
            "Approved memory deleted",
            extra={"event_type": "memory.deleted"},
        )
