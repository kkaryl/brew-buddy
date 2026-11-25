"""Application service governing user preferences, staged proposals, and durable memories."""

from __future__ import annotations

from app.application.memory.maintenance import MemoryMaintenance
from app.application.memory.proposals import MemoryProposalBatchResult, MemoryProposalStager
from app.application.memory.review import MemoryProposalReviewer
from app.domain.briefs.ports import BriefRepository
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingTone
from app.domain.memory.models import Memory, MemoryProposal, UserPreferences
from app.domain.memory.ports import (
    MemoryProposalAgentPort,
    MemoryProposalRepository,
    MemoryRepository,
    UserPreferencesRepository,
)
from app.domain.memory.types import ConsentStatus, MemorySourceType, MemoryType, ProposalStatus
from app.domain.shared.clock import ClockPort
from app.domain.shared.ports import IdGeneratorPort


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
        self._proposals = MemoryProposalStager(
            proposal_repo=proposal_repo,
            memory_repo=memory_repo,
            contact_repo=contact_repo,
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            proposal_agent=proposal_agent,
            clock=clock,
            id_generator=id_generator,
        )
        self._review = MemoryProposalReviewer(
            proposal_repo=proposal_repo,
            memory_repo=memory_repo,
            contact_repo=contact_repo,
            clock=clock,
            id_generator=id_generator,
        )
        self._maintenance = MemoryMaintenance(
            preferences_repo=preferences_repo,
            memory_repo=memory_repo,
            clock=clock,
        )

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
        return await self._maintenance.upsert_user_preferences(
            principal=principal,
            preferred_display_name=preferred_display_name,
            clear_preferred_display_name=clear_preferred_display_name,
            default_tone=default_tone,
            default_duration_minutes=default_duration_minutes,
            preferred_question_count=preferred_question_count,
            communication_style_notes=communication_style_notes,
            focus_areas=focus_areas,
        )

    async def update_preferred_display_name(
        self,
        *,
        principal: AuthenticatedPrincipal,
        display_name: str | None,
    ) -> UserPreferences | None:
        """Set or clear the caller's custom display name override."""
        return await self._maintenance.update_preferred_display_name(
            principal=principal,
            display_name=display_name,
        )

    async def propose_memories_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> MemoryProposalBatchResult:
        """Extract PII-scrubbed, attributed candidate memories and stage for human review."""
        return await self._proposals.propose_memories_batch(
            principal=principal,
            notes=notes,
            source_type=source_type,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

    async def validate_proposal_references(
        self,
        *,
        principal: AuthenticatedPrincipal,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> None:
        """Check a proposal request's references without running extraction.

        Lets a caller reject a wrong or foreign id immediately, before any model call is
        scheduled.
        """
        await self._proposals.validate_proposal_references(
            principal=principal,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

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
        batch = await self.propose_memories_batch(
            principal=principal,
            notes=notes,
            source_type=source_type,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )
        return batch.proposals

    async def list_proposals(
        self,
        *,
        principal: AuthenticatedPrincipal,
        status: ProposalStatus | None = None,
        contact_id: str | None = None,
    ) -> list[MemoryProposal]:
        """List staged memory proposals strictly owned by ``principal`` for human review."""
        return await self._review.list_proposals(
            principal=principal,
            status=status,
            contact_id=contact_id,
        )

    async def approve_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None = None,
        memory_type: MemoryType | None = None,
        supersedes_memory_id: str | None = None,
    ) -> Memory:
        """Promote a pending proposal into durable approved ``memories`` storage."""
        return await self._review.approve_proposal(
            principal=principal,
            proposal_id=proposal_id,
            expected_version=expected_version,
            edited_text=edited_text,
            memory_type=memory_type,
            supersedes_memory_id=supersedes_memory_id,
        )

    async def reject_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int = 1,
        reason: str | None = None,
    ) -> MemoryProposal:
        """Reject a pending proposal so it is never persisted as an active memory."""
        return await self._review.reject_proposal(
            principal=principal,
            proposal_id=proposal_id,
            expected_version=expected_version,
            reason=reason,
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
        """Update an approved memory enforcing ownership and optimistic version control."""
        return await self._maintenance.update_memory(
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
        """Delete an approved memory and archive its DELETED tombstone with provenance."""
        await self._maintenance.delete_memory(
            principal=principal,
            memory_id=memory_id,
            expected_version=expected_version,
        )
