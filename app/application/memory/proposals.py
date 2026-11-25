"""Proposal staging for the HTTP API and background jobs.

The staging rules themselves live in ``app.application.memory.candidate_staging``, shared
with the agent tool. This module adds what only the API path needs: brief references and
the rule that notes with nothing to remember are a validation error.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.memory.candidate_staging import (
    STAGING_OPERATION_NAME,
    STAGING_SPAN_NAME,
    MemoryCandidateStagingPipeline,
    record_staging_outcome,
    resolve_proposal_references,
)
from app.application.shared.telemetry import brew_span
from app.domain.briefs.ports import BriefRepository
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingRepository
from app.domain.memory.models import MemoryProposal
from app.domain.memory.ports import (
    MemoryProposalAgentPort,
    MemoryProposalRepository,
    MemoryRepository,
)
from app.domain.memory.types import MemorySourceType
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import DomainValidationError
from app.domain.shared.ports import IdGeneratorPort


@dataclass(frozen=True, slots=True)
class MemoryProposalBatchResult:
    """Structured result of extracting and staging candidate memory proposals for review."""

    proposals: list[MemoryProposal]
    skipped_duplicates: int = 0
    filtered_sensitive_count: int = 0


class MemoryProposalStager:
    """Extracts candidate memories from notes and stages them as pending proposals."""

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
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._pipeline = MemoryCandidateStagingPipeline(
            memory_reader=memory_repo,
            proposal_stager=proposal_repo,
            proposal_agent=proposal_agent,
            clock=clock,
            id_generator=id_generator,
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
        """Extract PII-scrubbed, attributed candidate memories and stage for human review.

        Raises ``DomainValidationError`` when the notes yield no candidate and nothing was
        withheld as sensitive, so the caller can tell the user there was nothing to keep.
        """
        with brew_span(
            STAGING_SPAN_NAME,
            operation_name=STAGING_OPERATION_NAME,
            tracer_name=__name__,
        ) as tracker:
            meeting, brief, contact = await resolve_proposal_references(
                owner_user_id=principal.user_id,
                meeting_id=meeting_id,
                contact_id=contact_id,
                brief_id=brief_id,
                meeting_reader=self._meeting_repo,
                contact_reader=self._contact_repo,
                brief_repo=self._brief_repo,
            )
            outcome = await self._pipeline.stage(
                owner_user_id=principal.user_id,
                notes=notes,
                source_type=source_type,
                meeting=meeting,
                contact=contact,
                brief=brief,
            )
            if outcome.nothing_extractable:
                raise DomainValidationError("No candidate memories could be extracted from notes.")
            record_staging_outcome(tracker, outcome)
            return MemoryProposalBatchResult(
                proposals=outcome.proposals,
                skipped_duplicates=outcome.skipped_duplicates,
                filtered_sensitive_count=outcome.filtered_sensitive_count,
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
        await resolve_proposal_references(
            owner_user_id=principal.user_id,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
            meeting_reader=self._meeting_repo,
            contact_reader=self._contact_repo,
            brief_repo=self._brief_repo,
        )
