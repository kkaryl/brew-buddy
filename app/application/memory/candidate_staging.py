"""The one pipeline that turns notes into pending memory proposals for human review.

Two callers use it: ``MemoryProposalStager`` (HTTP API and background jobs) and
``ConversationCoachService.suggest_memory_candidates`` (the agent tool). Each caller owns
its own reporting policy, for example whether an empty outcome is an error. Everything
that decides *what gets staged* lives here, so the two paths cannot drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.application.safety.untrusted_text import (
    contains_prompt_injection,
    sanitize_untrusted_text,
    split_safe_note_segments,
)
from app.application.shared.ownership import require_owned_contact, require_owned_meeting
from app.application.shared.telemetry import (
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    SpanOutcomeTracker,
)
from app.application.shared.validation import translate_pydantic_error
from app.domain.briefs.models import PreparationBrief
from app.domain.briefs.ports import BriefRepository
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactReaderPort
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingReaderPort
from app.domain.memory.attribution import (
    default_epistemic_status_for_scope,
    ensure_attributed_epistemic_text,
)
from app.domain.memory.models import Memory, MemoryProposal, MemorySource
from app.domain.memory.ports import (
    ApprovedMemoryReaderPort,
    MemoryProposalAgentPort,
    PendingMemoryProposalStagerPort,
)
from app.domain.memory.relations import MemoryRelationKind, classify_candidate_against_existing
from app.domain.memory.sensitivity import detect_sensitive_or_third_party_assumption
from app.domain.memory.types import MemoryScope, MemorySourceType, ProposalStatus
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthorizationError, DomainValidationError, EntityNotFoundError
from app.domain.shared.ports import IdGeneratorPort

logger = logging.getLogger(__name__)

STAGING_SPAN_NAME = "brew.memory.propose"
STAGING_OPERATION_NAME = "memory.propose"


async def resolve_proposal_references(
    *,
    owner_user_id: str,
    meeting_id: str | None,
    contact_id: str | None,
    meeting_reader: MeetingReaderPort,
    contact_reader: ContactReaderPort,
    brief_id: str | None = None,
    brief_repo: BriefRepository | None = None,
) -> tuple[Meeting | None, PreparationBrief | None, Contact | None]:
    """Load the meeting, brief and contact a staging request names, enforcing ownership.

    Raises ``AuthorizationError`` for another user's record, ``EntityNotFoundError`` for
    an unknown one, and ``DomainValidationError`` when the three do not belong together.
    A caller with no access to briefs (the agent tool) passes neither ``brief_id`` nor
    ``brief_repo``.
    """
    meeting: Meeting | None = None
    if meeting_id is not None:
        meeting = await require_owned_meeting(meeting_reader, owner_user_id, meeting_id)
        if contact_id is not None and contact_id != meeting.contact_id:
            raise DomainValidationError(
                "Provided contact_id does not match the specified meeting's contact_id."
            )
        contact_id = meeting.contact_id

    brief: PreparationBrief | None = None
    if brief_id is not None:
        if brief_repo is None:
            raise DomainValidationError("brief_id is not supported on this path.")
        brief = await brief_repo.get_for_owner(owner_user_id, brief_id)
        if brief is None:
            if await brief_repo.exists_for_any_owner(brief_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="PreparationBrief", entity_id=brief_id)
        if brief.owner_user_id != owner_user_id:
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
        contact = await require_owned_contact(contact_reader, owner_user_id, contact_id)

    return meeting, brief, contact


@dataclass(frozen=True, slots=True)
class CandidateStagingOutcome:
    """What one staging run saved and what it withheld, with one counter per reason."""

    proposals: list[MemoryProposal]
    extractor_invoked: bool
    extracted_candidate_count: int
    existing_memory_count: int
    skipped_duplicates: int
    filtered_sensitive_count: int
    filtered_directive_count: int

    @property
    def nothing_extractable(self) -> bool:
        """True when no candidate was extracted and nothing was withheld as sensitive.

        A caller that treats "these notes contain nothing to remember" as an error checks
        this. Notes that were withheld only because they were sensitive are not an error.
        """
        return self.extracted_candidate_count == 0 and self.filtered_sensitive_count == 0


class MemoryCandidateStagingPipeline:
    """Filters notes, asks the extractor for candidates, and stages the ones that survive.

    Holds a read-only view of approved memories and a write port that can only create
    pending proposals, so no caller of this pipeline can create a durable memory.
    """

    def __init__(
        self,
        *,
        memory_reader: ApprovedMemoryReaderPort,
        proposal_stager: PendingMemoryProposalStagerPort,
        proposal_agent: MemoryProposalAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._memory_reader = memory_reader
        self._proposal_stager = proposal_stager
        self._proposal_agent = proposal_agent
        self._clock = clock
        self._id_generator = id_generator

    async def stage(
        self,
        *,
        owner_user_id: str,
        notes: str,
        source_type: MemorySourceType,
        meeting: Meeting | None,
        contact: Contact | None,
        brief: PreparationBrief | None = None,
        max_candidates: int | None = None,
    ) -> CandidateStagingOutcome:
        """Stage pending proposals from ``notes``.

        ``meeting``, ``contact`` and ``brief`` must already be resolved and authorized for
        ``owner_user_id`` (see ``resolve_proposal_references``). ``max_candidates`` stops
        staging once that many proposals are saved; ``None`` stages every survivor.
        """
        uid = owner_user_id
        raw_segments, filtered_directives = split_safe_note_segments(notes)
        filtered_sensitive = 0
        safe_segments: list[str] = []
        for segment in raw_segments:
            if detect_sensitive_or_third_party_assumption(segment) is not None:
                filtered_sensitive += 1
                continue
            safe_segments.append(segment)

        if not safe_segments:
            return CandidateStagingOutcome(
                proposals=[],
                extractor_invoked=False,
                extracted_candidate_count=0,
                existing_memory_count=0,
                skipped_duplicates=0,
                filtered_sensitive_count=filtered_sensitive,
                filtered_directive_count=filtered_directives,
            )

        existing_memories = [
            mem
            for mem in await self._memory_reader.list_by_owner(uid, include_revoked=False)
            if mem.owner_user_id == uid and mem.is_active
        ]

        candidates = await self._proposal_agent.propose_memories(
            notes=". ".join(safe_segments),
            meeting=meeting,
            contact=contact,
            existing_memories=existing_memories,
        )

        now = self._clock.now_utc()
        resolved_meeting_id = (
            meeting.id if meeting is not None else (brief.meeting_id if brief is not None else None)
        )
        contact_name = contact.name if contact is not None else None

        saved_proposals: list[MemoryProposal] = []
        # Approved memories plus what this run has staged, so a clause repeated within one
        # set of notes is not staged twice.
        known_memories: list[Memory] = list(existing_memories)
        skipped_duplicates = 0

        for candidate in candidates:
            if max_candidates is not None and len(saved_proposals) >= max_candidates:
                break
            if contains_prompt_injection(candidate.text):
                filtered_directives += 1
                continue
            sanitized_text = sanitize_untrusted_text(candidate.text, max_chars=1000)
            if sanitized_text.injection_detected or len(sanitized_text.text) < 3:
                filtered_directives += 1
                continue
            if detect_sensitive_or_third_party_assumption(sanitized_text.text) is not None:
                filtered_sensitive += 1
                continue

            resolved_contact_id = (
                contact.id
                if candidate.scope is MemoryScope.CONTACT and contact is not None
                else candidate.contact_id
            )
            attributed_text = ensure_attributed_epistemic_text(
                sanitized_text.text,
                scope=candidate.scope,
                contact_name=contact_name,
            )

            relation = classify_candidate_against_existing(
                scope=candidate.scope,
                contact_id=resolved_contact_id,
                memory_type=candidate.memory_type,
                text=attributed_text,
                existing_memories=known_memories,
                explicit_supersedes_memory_id=candidate.supersedes_memory_id,
                contact_name=contact_name,
            )
            if relation.kind is MemoryRelationKind.DUPLICATE:
                skipped_duplicates += 1
                continue

            supersedes_id: str | None = None
            conflict_summary: str | None = None
            # Only a persisted durable memory may be superseded, never an earlier item
            # from the same run.
            if (
                relation.kind is MemoryRelationKind.SUPERSEDES
                and relation.matched_memory is not None
                and any(m.id == relation.matched_memory.id for m in existing_memories)
            ):
                supersedes_id = relation.matched_memory.id
                conflict_summary = (relation.reason or "")[:500] or None

            sanitized_rationale = sanitize_untrusted_text(candidate.rationale, max_chars=500).text
            raw_excerpt = candidate.excerpt or sanitized_text.text[:500]
            sanitized_excerpt = sanitize_untrusted_text(raw_excerpt, max_chars=500).text or None

            try:
                source = MemorySource(
                    source_type=source_type,
                    meeting_id=resolved_meeting_id,
                    brief_id=brief.id if brief is not None else None,
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
                    text=attributed_text,
                    rationale=sanitized_rationale,
                    source=source,
                    status=ProposalStatus.PENDING,
                    epistemic_status=default_epistemic_status_for_scope(candidate.scope),
                    supersedes_memory_id=supersedes_id,
                    conflict_summary=conflict_summary,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            except ValidationError as exc:
                raise translate_pydantic_error(exc) from exc

            saved = await self._proposal_stager.save(proposal)
            saved_proposals.append(saved)
            known_memories.append(
                Memory(
                    id=f"staged_{saved.id}",
                    owner_user_id=uid,
                    scope=saved.scope,
                    contact_id=saved.contact_id,
                    memory_type=saved.memory_type,
                    text=saved.text,
                    source=saved.source,
                    created_at=now,
                    updated_at=now,
                )
            )

        return CandidateStagingOutcome(
            proposals=saved_proposals,
            extractor_invoked=True,
            extracted_candidate_count=len(candidates),
            existing_memory_count=len(existing_memories),
            skipped_duplicates=skipped_duplicates,
            filtered_sensitive_count=filtered_sensitive,
            filtered_directive_count=filtered_directives,
        )


def record_staging_outcome(tracker: SpanOutcomeTracker, outcome: CandidateStagingOutcome) -> None:
    """Put the outcome counts on the caller's span and emit the outcome log event."""
    tracker.set_attributes(
        {
            ATTR_MEMORY_RETRIEVED_COUNT: outcome.existing_memory_count,
            ATTR_MEMORY_SAVED_COUNT: len(outcome.proposals),
            "brew.memory.skipped_duplicates": outcome.skipped_duplicates,
            "brew.memory.filtered_sensitive_count": outcome.filtered_sensitive_count,
            "brew.memory.filtered_directive_count": outcome.filtered_directive_count,
        }
    )
    if not outcome.extractor_invoked:
        logger.info(
            "Every note segment was withheld before extraction",
            extra={
                "event_type": (
                    "memory.proposals_filtered_sensitive"
                    if outcome.filtered_sensitive_count > 0
                    else "memory.proposals_filtered_directives"
                ),
                "operation_name": STAGING_OPERATION_NAME,
                "memory_saved_count": 0,
            },
        )
        return
    logger.info(
        "Memory proposals staged for human review",
        extra={
            "event_type": "memory.proposals_created",
            "operation_name": STAGING_OPERATION_NAME,
            "memory_retrieved_count": outcome.existing_memory_count,
            "memory_saved_count": len(outcome.proposals),
            "result_status": "ok",
        },
    )
