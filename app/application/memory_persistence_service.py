"""Application service governing persistent user preferences, proposals, and approved memories."""

from __future__ import annotations

import logging

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
    MeetingTone,
    MemoryScope,
    MemorySourceType,
    MemoryType,
)

logger = logging.getLogger(__name__)


def translate_pydantic_error(exc: ValidationError) -> DomainValidationError:
    """Convert a Pydantic ``ValidationError`` into a structured ``DomainValidationError``."""
    first = exc.errors()[0] if exc.errors() else None
    if first is not None:
        loc = ".".join(str(part) for part in first.get("loc", ()))
        msg = str(first.get("msg", "Invalid domain value."))
        summary = f"{loc}: {msg}" if loc else msg
    else:
        summary = "Domain validation failed."
    return DomainValidationError(summary)


class MemoryPersistenceService:
    """Persists user preferences, separate memory proposals, and consented durable memories."""

    def __init__(
        self,
        *,
        preferences_repo: UserPreferencesRepository,
        proposal_repo: MemoryProposalRepository,
        memory_repo: MemoryRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        proposal_agent: MemoryProposalAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._preferences_repo = preferences_repo
        self._proposal_repo = proposal_repo
        self._memory_repo = memory_repo
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._proposal_agent = proposal_agent
        self._clock = clock
        self._id_generator = id_generator

    async def upsert_user_preferences(
        self,
        *,
        principal: AuthenticatedPrincipal,
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

        try:
            if stored is None:
                prefs = UserPreferences(
                    id="default",
                    owner_user_id=uid,
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

            updated = UserPreferences(
                id=stored.id,
                owner_user_id=uid,
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
        """Extract candidate memories from notes and store them in ``memoryProposals``."""
        uid = principal.user_id

        meeting: Meeting | None = None
        if meeting_id is not None:
            meeting = await self._meeting_repo.get_for_owner(uid, meeting_id)
            if meeting is None:
                if await self._meeting_repo.exists_for_any_owner(meeting_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(entity_name="Meeting", entity_id=meeting_id)
            if contact_id is not None and contact_id != meeting.contact_id:
                raise DomainValidationError(
                    "Provided contact_id does not match the specified meeting's contact_id."
                )
            contact_id = meeting.contact_id

        brief: PreparationBrief | None = None
        if brief_id is not None:
            brief = await self._brief_repo.get_for_owner(uid, brief_id)
            if brief is None:
                if await self._brief_repo.exists_for_any_owner(brief_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(
                    entity_name="PreparationBrief",
                    entity_id=brief_id,
                )
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
            contact = await self._contact_repo.get_for_owner(uid, contact_id)
            if contact is None:
                if await self._contact_repo.exists_for_any_owner(contact_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)

        existing_memories = await self._memory_repo.list_by_owner(
            uid,
            include_revoked=False,
        )
        candidates = await self._proposal_agent.propose_memories(
            notes=notes,
            meeting=meeting,
            contact=contact,
            existing_memories=existing_memories,
        )
        if not candidates:
            raise DomainValidationError("No candidate memories could be extracted from notes.")

        now = self._clock.now_utc()
        resolved_meeting_id = (
            meeting.id if meeting is not None else (brief.meeting_id if brief is not None else None)
        )
        saved_proposals: list[MemoryProposal] = []
        for candidate in candidates:
            resolved_contact_id = (
                contact.id
                if candidate.scope is MemoryScope.CONTACT and contact is not None
                else candidate.contact_id
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
                    owner_user_id=uid,
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
                raise translate_pydantic_error(exc) from exc

            saved_proposals.append(await self._proposal_repo.save(proposal))

        logger.info(
            "Memory proposals staged for human review",
            extra={"event_type": "memory.proposals_created"},
        )
        return saved_proposals

    async def approve_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None = None,
        memory_type: MemoryType | None = None,
    ) -> Memory:
        """Promote a pending proposal into durable approved ``memories`` storage."""
        uid = principal.user_id
        proposal = await self._proposal_repo.get_for_owner(uid, proposal_id)
        if proposal is None:
            if await self._proposal_repo.exists_for_any_owner(proposal_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="MemoryProposal", entity_id=proposal_id)

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
                owner_user_id=uid,
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
            raise translate_pydantic_error(exc) from exc

        await self._proposal_repo.save(reviewed_proposal, expected_version=expected_version)
        saved_memory = await self._memory_repo.save(memory)
        logger.info(
            "Memory proposal approved and persisted",
            extra={"event_type": "memory.approved"},
        )
        return saved_memory

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

        now = max(self._clock.now_utc(), memory.created_at)
        try:
            updated = memory.apply_update(
                text=text,
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
        """Delete an approved memory enforcing ownership and optional version check."""
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

        await self._memory_repo.delete(
            uid,
            memory_id,
            expected_version=expected_version,
        )
        logger.info(
            "Approved memory deleted",
            extra={"event_type": "memory.deleted"},
        )
