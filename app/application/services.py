"""Async application services orchestrating contacts, meetings, briefs, and memory facade."""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from app.application.memory_persistence_service import (
    MemoryPersistenceService,
    translate_pydantic_error,
)
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.domain.errors import (
    AuthorizationError,
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
    PreparationBrief,
)
from app.domain.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    ContactRepository,
    IdGeneratorPort,
    MeetingRepository,
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


class ContactService:
    """Async application use cases for counterpart contact management."""

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

    async def create_contact(
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
            raise translate_pydantic_error(exc) from exc

        saved = await self._contact_repo.save(contact)
        logger.info("Contact created", extra={"event_type": "contact.created"})
        return saved

    async def list_contacts(self, *, principal: AuthenticatedPrincipal) -> list[Contact]:
        """List contacts belonging to ``principal``."""
        return await self._contact_repo.list_by_owner(principal.user_id)

    async def get_owned_contact(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str,
    ) -> Contact:
        """Fetch a contact and enforce caller ownership."""
        contact = await self._contact_repo.get_for_owner(principal.user_id, contact_id)
        if contact is None:
            if await self._contact_repo.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return contact


class MeetingService:
    """Async application use cases for inspecting user meetings."""

    def __init__(
        self,
        *,
        meeting_repo: MeetingRepository,
        contact_repo: ContactRepository,
    ) -> None:
        self._meeting_repo = meeting_repo
        self._contact_repo = contact_repo

    async def list_meetings(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact_id: str | None = None,
    ) -> list[Meeting]:
        """List meetings owned by ``principal``, validating optional ``contact_id`` ownership."""
        if contact_id is not None:
            contact = await self._contact_repo.get_for_owner(principal.user_id, contact_id)
            if contact is None:
                if await self._contact_repo.exists_for_any_owner(contact_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return await self._meeting_repo.list_by_owner(
            principal.user_id,
            contact_id=contact_id,
        )


class BriefService:
    """Async application use cases generating, retrieving, and revising preparation briefs."""

    def __init__(
        self,
        *,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        memory_retrieval: MemoryRetrievalService,
        memory_persistence: MemoryPersistenceService,
        brief_agent: BriefCoachAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._memory_retrieval = memory_retrieval
        self._memory_persistence = memory_persistence
        self._brief_agent = brief_agent
        self._clock = clock
        self._id_generator = id_generator

    async def generate_brief(
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
        """Assemble bounded user-scoped context, create a meeting, and synthesize a brief."""
        has_preference_overrides = (
            preferred_question_count is not None
            or communication_style_notes is not None
            or focus_areas is not None
        )
        if has_preference_overrides:
            # Verify contact ownership first so unauthorized contact probes fail before writes.
            await self._memory_retrieval.build_brief_context(
                principal=principal,
                contact_id=contact_id,
                purpose=purpose,
                objective=meeting_objective,
            )
            await self._memory_persistence.upsert_user_preferences(
                principal=principal,
                preferred_question_count=preferred_question_count,
                communication_style_notes=communication_style_notes,
                focus_areas=focus_areas,
            )

        context = await self._memory_retrieval.build_brief_context(
            principal=principal,
            contact_id=contact_id,
            purpose=purpose,
            objective=meeting_objective,
        )

        now = self._clock.now_utc()
        meeting_id = self._id_generator.new_id("mtg")
        brief_id = self._id_generator.new_id("brf")

        try:
            meeting = Meeting(
                id=meeting_id,
                owner_user_id=principal.user_id,
                contact_id=context.contact.id,
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
            raise translate_pydantic_error(exc) from exc

        generated = await self._brief_agent.generate_brief(
            meeting=meeting,
            context=context,
        )

        try:
            brief = PreparationBrief(
                id=brief_id,
                owner_user_id=principal.user_id,
                meeting_id=meeting.id,
                contact_id=context.contact.id,
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
            raise translate_pydantic_error(exc) from exc

        await self._meeting_repo.save(meeting)
        saved_brief = await self._brief_repo.save(brief)
        logger.info("Preparation brief generated", extra={"event_type": "brief.generated"})
        return saved_brief

    async def get_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
    ) -> PreparationBrief:
        """Fetch a preparation brief and verify caller ownership."""
        brief = await self._brief_repo.get_for_owner(principal.user_id, brief_id)
        if brief is None:
            if await self._brief_repo.exists_for_any_owner(brief_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="PreparationBrief", entity_id=brief_id)
        return brief

    async def revise_brief(
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
        current_brief = await self.get_brief(principal=principal, brief_id=brief_id)
        if current_brief.version != expected_version:
            raise VersionConflictError(
                entity_name="PreparationBrief",
                entity_id=brief_id,
                expected_version=expected_version,
                actual_version=current_brief.version,
            )

        meeting = await self._meeting_repo.get_for_owner(
            principal.user_id,
            current_brief.meeting_id,
        )
        if meeting is None:
            raise EntityNotFoundError(
                entity_name="Meeting",
                entity_id=current_brief.meeting_id,
            )

        target_duration = (
            duration_minutes if duration_minutes is not None else current_brief.duration_minutes
        )
        target_tone = tone if tone is not None else current_brief.tone

        context = await self._memory_retrieval.build_brief_context(
            principal=principal,
            contact_id=current_brief.contact_id,
            purpose=meeting.purpose,
            objective=current_brief.meeting_objective,
            exclude_meeting_id=meeting.id,
        )

        revised_content = await self._brief_agent.revise_brief(
            current_brief=current_brief,
            meeting=meeting,
            context=context,
            instructions=instructions,
            target_duration_minutes=target_duration,
            target_tone=target_tone,
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
            raise translate_pydantic_error(exc) from exc

        saved_brief = await self._brief_repo.save(
            revised_brief,
            expected_version=expected_version,
        )

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
            await self._meeting_repo.save(updated_meeting, expected_version=meeting.version)

        logger.info("Preparation brief revised", extra={"event_type": "brief.revised"})
        return saved_brief


class MemoryService:
    """Cohesive facade combining ``MemoryRetrievalService`` and ``MemoryPersistenceService``."""

    def __init__(
        self,
        *,
        retrieval: MemoryRetrievalService,
        persistence: MemoryPersistenceService,
    ) -> None:
        self._retrieval = retrieval
        self._persistence = persistence

    @property
    def retrieval(self) -> MemoryRetrievalService:
        return self._retrieval

    @property
    def persistence(self) -> MemoryPersistenceService:
        return self._persistence

    async def propose_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> list[MemoryProposal]:
        return await self._persistence.propose_memories(
            principal=principal,
            notes=notes,
            source_type=source_type,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

    async def approve_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None = None,
        memory_type: MemoryType | None = None,
    ) -> Memory:
        return await self._persistence.approve_proposal(
            principal=principal,
            proposal_id=proposal_id,
            expected_version=expected_version,
            edited_text=edited_text,
            memory_type=memory_type,
        )

    async def list_memories(
        self,
        *,
        principal: AuthenticatedPrincipal,
        scope: MemoryScope | None = None,
        contact_id: str | None = None,
        memory_type: MemoryType | None = None,
        include_revoked: bool = False,
    ) -> list[Memory]:
        return await self._retrieval.list_memories(
            principal=principal,
            scope=scope,
            contact_id=contact_id,
            memory_type=memory_type,
            include_revoked=include_revoked,
        )

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
        return await self._persistence.update_memory(
            principal=principal,
            memory_id=memory_id,
            expected_version=expected_version,
            text=text,
            memory_type=memory_type,
            consent_status=consent_status,
        )

    async def delete_memory(
        self,
        *,
        principal: AuthenticatedPrincipal,
        memory_id: str,
        expected_version: int | None = None,
    ) -> None:
        await self._persistence.delete_memory(
            principal=principal,
            memory_id=memory_id,
            expected_version=expected_version,
        )
