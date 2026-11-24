"""Application service governing user preferences, staged proposals, and durable memories."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.application.telemetry import (
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    SpanOutcomeTracker,
    brew_span,
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
    VersionConflictError,
)
from app.domain.health import ClockPort
from app.domain.memory_lifecycle import (
    MemoryRelationKind,
    classify_candidate_against_existing,
    default_epistemic_status_for_scope,
    detect_sensitive_or_third_party_assumption,
    ensure_attributed_epistemic_text,
)
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
    MemoryLifecycleState,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryProposalBatchResult:
    """Structured result of extracting and staging candidate memory proposals for review."""

    proposals: list[MemoryProposal]
    skipped_duplicates: int = 0
    filtered_sensitive_count: int = 0


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
        with brew_span(
            "brew.memory.propose",
            operation_name="memory.propose",
            tracer_name=__name__,
        ) as tracker:
            result = await self._propose_memories_batch_impl(
                principal=principal,
                notes=notes,
                source_type=source_type,
                meeting_id=meeting_id,
                contact_id=contact_id,
                brief_id=brief_id,
                tracker=tracker,
            )
            return result

    async def _propose_memories_batch_impl(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType,
        meeting_id: str | None,
        contact_id: str | None,
        brief_id: str | None,
        tracker: SpanOutcomeTracker,
    ) -> MemoryProposalBatchResult:
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

        raw_segments, _ = split_safe_note_segments(notes)
        filtered_sensitive = 0
        safe_segments: list[str] = []
        for seg in raw_segments:
            if detect_sensitive_or_third_party_assumption(seg) is not None:
                filtered_sensitive += 1
                continue
            safe_segments.append(seg)

        if not safe_segments:
            if filtered_sensitive > 0:
                tracker.set_attributes(
                    {
                        ATTR_MEMORY_RETRIEVED_COUNT: 0,
                        ATTR_MEMORY_SAVED_COUNT: 0,
                        "brew.memory.filtered_sensitive_count": filtered_sensitive,
                    }
                )
                logger.info(
                    "All note segments filtered as sensitive or speculative assumptions",
                    extra={
                        "event_type": "memory.proposals_filtered_sensitive",
                        "operation_name": "memory.propose",
                        "memory_saved_count": 0,
                    },
                )
                return MemoryProposalBatchResult(
                    proposals=[],
                    skipped_duplicates=0,
                    filtered_sensitive_count=filtered_sensitive,
                )
            raise DomainValidationError("No candidate memories could be extracted from notes.")

        existing_memories = [
            mem
            for mem in await self._memory_repo.list_by_owner(
                uid,
                include_revoked=False,
                include_superseded=False,
            )
            if mem.owner_user_id == uid and mem.is_active
        ]

        safe_notes_for_extractor = ". ".join(safe_segments)
        candidates = await self._proposal_agent.propose_memories(
            notes=safe_notes_for_extractor,
            meeting=meeting,
            contact=contact,
            existing_memories=existing_memories,
        )
        if not candidates and filtered_sensitive == 0:
            raise DomainValidationError("No candidate memories could be extracted from notes.")

        now = self._clock.now_utc()
        resolved_meeting_id = (
            meeting.id if meeting is not None else (brief.meeting_id if brief is not None else None)
        )
        contact_name = contact.name if contact is not None else None

        saved_proposals: list[MemoryProposal] = []
        synthetic_staged_as_memories: list[Memory] = list(existing_memories)
        skipped_duplicates = 0

        for candidate in candidates:
            if contains_prompt_injection(candidate.text):
                continue
            sanitized_text_res = sanitize_untrusted_text(candidate.text, max_chars=1000)
            if sanitized_text_res.injection_detected or len(sanitized_text_res.text) < 3:
                continue
            if detect_sensitive_or_third_party_assumption(sanitized_text_res.text) is not None:
                filtered_sensitive += 1
                continue

            resolved_contact_id = (
                contact.id
                if candidate.scope is MemoryScope.CONTACT and contact is not None
                else candidate.contact_id
            )
            attributed_text = ensure_attributed_epistemic_text(
                sanitized_text_res.text,
                scope=candidate.scope,
                contact_name=contact_name,
            )

            relation = classify_candidate_against_existing(
                scope=candidate.scope,
                contact_id=resolved_contact_id,
                memory_type=candidate.memory_type,
                text=attributed_text,
                existing_memories=synthetic_staged_as_memories,
                explicit_supersedes_memory_id=candidate.supersedes_memory_id,
                contact_name=contact_name,
            )
            if relation.kind is MemoryRelationKind.DUPLICATE:
                skipped_duplicates += 1
                continue

            supersedes_id: str | None = None
            conflict_summary: str | None = None
            # Only supersede persisted durable memories (not earlier items in the same batch)
            if (
                relation.kind is MemoryRelationKind.SUPERSEDES
                and relation.matched_memory is not None
                and any(m.id == relation.matched_memory.id for m in existing_memories)
            ):
                supersedes_id = relation.matched_memory.id
                conflict_summary = (relation.reason or "")[:500] or None

            sanitized_rationale = sanitize_untrusted_text(candidate.rationale, max_chars=500).text
            raw_excerpt = candidate.excerpt or sanitized_text_res.text[:500]
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

            saved = await self._proposal_repo.save(proposal)
            saved_proposals.append(saved)
            # Track within-batch items so duplicate clauses in the same note aren't staged twice
            synthetic_staged_as_memories.append(
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

        tracker.set_attributes(
            {
                ATTR_MEMORY_RETRIEVED_COUNT: len(existing_memories),
                ATTR_MEMORY_SAVED_COUNT: len(saved_proposals),
                "brew.memory.skipped_duplicates": skipped_duplicates,
                "brew.memory.filtered_sensitive_count": filtered_sensitive,
            }
        )
        logger.info(
            "Memory proposals staged for human review",
            extra={
                "event_type": "memory.proposals_created",
                "operation_name": "memory.propose",
                "memory_retrieved_count": len(existing_memories),
                "memory_saved_count": len(saved_proposals),
                "result_status": "ok",
            },
        )
        return MemoryProposalBatchResult(
            proposals=saved_proposals,
            skipped_duplicates=skipped_duplicates,
            filtered_sensitive_count=filtered_sensitive,
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
        uid = principal.user_id
        if contact_id is not None:
            contact = await self._contact_repo.get_for_owner(uid, contact_id)
            if contact is None:
                if await self._contact_repo.exists_for_any_owner(contact_id):
                    raise AuthorizationError()
                raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)

        records = await self._proposal_repo.list_by_owner(
            uid,
            status=status,
            contact_id=contact_id,
        )
        return [item for item in records if item.owner_user_id == uid]

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
        with brew_span(
            "brew.memory.approve",
            operation_name="memory.approve",
            tracer_name=__name__,
        ) as tracker:
            return await self._approve_proposal_impl(
                principal=principal,
                proposal_id=proposal_id,
                expected_version=expected_version,
                edited_text=edited_text,
                memory_type=memory_type,
                supersedes_memory_id=supersedes_memory_id,
                tracker=tracker,
            )

    async def _approve_proposal_impl(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int,
        edited_text: str | None,
        memory_type: MemoryType | None,
        supersedes_memory_id: str | None,
        tracker: SpanOutcomeTracker,
    ) -> Memory:
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

        if proposal.status is not ProposalStatus.PENDING:
            raise ConflictError(
                f"Memory proposal '{proposal.id}' cannot be approved because its status is "
                f"'{proposal.status.value}'.",
                code="PROPOSAL_NOT_PENDING",
            )

        resolved_text = proposal.text
        if edited_text is not None:
            sanitized_edit = sanitize_untrusted_text(edited_text, max_chars=1000)
            if sanitized_edit.injection_detected:
                raise DomainValidationError(
                    "Edited memory text contains disallowed instruction-override directives."
                )
            resolved_text = sanitized_edit.text

        sensitive_reason = detect_sensitive_or_third_party_assumption(resolved_text)
        if sensitive_reason is not None:
            raise DomainValidationError(
                f"Cannot persist memory containing {sensitive_reason}.",
                code="SENSITIVE_MEMORY_REJECTED",
            )

        resolved_type = memory_type if memory_type is not None else proposal.memory_type
        contact: Contact | None = None
        if proposal.contact_id is not None:
            contact = await self._contact_repo.get_for_owner(uid, proposal.contact_id)

        resolved_text = ensure_attributed_epistemic_text(
            resolved_text,
            scope=proposal.scope,
            contact_name=contact.name if contact is not None else None,
        )

        # Validate explicit supersedes_memory_id if supplied by caller
        target_supersede_memory: Memory | None = None
        explicit_or_staged_supersede_id = (
            supersedes_memory_id
            if supersedes_memory_id is not None
            else proposal.supersedes_memory_id
        )
        if explicit_or_staged_supersede_id is not None:
            candidate_old = await self._memory_repo.get_for_owner(
                uid,
                explicit_or_staged_supersede_id,
            )
            if candidate_old is None:
                if await self._memory_repo.exists_for_any_owner(explicit_or_staged_supersede_id):
                    raise AuthorizationError()
                if supersedes_memory_id is not None:
                    raise EntityNotFoundError(
                        entity_name="Memory",
                        entity_id=explicit_or_staged_supersede_id,
                    )
            else:
                if candidate_old.scope is not proposal.scope or (
                    candidate_old.contact_id != proposal.contact_id
                ):
                    raise DomainValidationError(
                        "Cannot supersede a memory from a different scope or contact."
                    )
                if candidate_old.is_active:
                    target_supersede_memory = candidate_old
                elif supersedes_memory_id is not None:
                    raise ConflictError(
                        f"Memory '{candidate_old.id}' is already inactive "
                        f"('{candidate_old.lifecycle_state.value}').",
                        code="MEMORY_NOT_ACTIVE",
                    )

        active_existing = [
            mem
            for mem in await self._memory_repo.list_by_owner(
                uid,
                scope=proposal.scope,
                contact_id=proposal.contact_id,
                include_revoked=False,
                include_superseded=False,
            )
            if mem.owner_user_id == uid and mem.is_active
        ]

        relation = classify_candidate_against_existing(
            scope=proposal.scope,
            contact_id=proposal.contact_id,
            memory_type=resolved_type,
            text=resolved_text,
            existing_memories=active_existing,
            explicit_supersedes_memory_id=(
                target_supersede_memory.id if target_supersede_memory is not None else None
            ),
            contact_name=contact.name if contact is not None else None,
        )

        now = max(self._clock.now_utc(), proposal.created_at)

        # Deduplicate at approval time if an identical/semantic-duplicate active memory exists
        if (
            relation.kind is MemoryRelationKind.DUPLICATE
            and relation.matched_memory is not None
            and target_supersede_memory is None
        ):
            existing_active_mem = relation.matched_memory
            reviewed_dup = proposal.mark_approved(
                approved_memory_id=existing_active_mem.id,
                reviewed_at=now,
            )
            await self._proposal_repo.save(reviewed_dup, expected_version=expected_version)
            tracker.set_attributes(
                {
                    ATTR_MEMORY_RETRIEVED_COUNT: len(active_existing),
                    ATTR_MEMORY_SAVED_COUNT: 0,
                    "brew.memory.deduplicated": True,
                }
            )
            logger.info(
                "Memory proposal deduplicated into existing active memory",
                extra={
                    "event_type": "memory.deduplicated",
                    "operation_name": "memory.approve",
                    "memory_retrieved_count": len(active_existing),
                    "memory_saved_count": 0,
                    "result_status": "deduplicated",
                },
            )
            return existing_active_mem

        if (
            target_supersede_memory is None
            and relation.kind is MemoryRelationKind.SUPERSEDES
            and relation.matched_memory is not None
        ):
            target_supersede_memory = relation.matched_memory

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
                memory_type=resolved_type,
                text=resolved_text,
                source=approved_source,
                consent_status=ConsentStatus.APPROVED,
                lifecycle_state=MemoryLifecycleState.APPROVED,
                epistemic_status=proposal.epistemic_status,
                supersedes_memory_id=(
                    target_supersede_memory.id if target_supersede_memory is not None else None
                ),
                created_at=now,
                updated_at=now,
                version=1,
            )
            reviewed_proposal = proposal.mark_approved(
                approved_memory_id=memory.id,
                reviewed_at=now,
                supersedes_memory_id=(
                    target_supersede_memory.id if target_supersede_memory is not None else None
                ),
            )
        except ValidationError as exc:
            raise translate_pydantic_error(exc) from exc

        await self._proposal_repo.save(reviewed_proposal, expected_version=expected_version)
        if target_supersede_memory is not None:
            superseded_old = target_supersede_memory.mark_superseded(
                superseded_by_memory_id=memory.id,
                superseded_at=now,
            )
            await self._memory_repo.save(
                superseded_old,
                expected_version=target_supersede_memory.version,
            )
            logger.info(
                "Prior memory marked superseded due to updated approved memory",
                extra={"event_type": "memory.superseded"},
            )

        saved_memory = await self._memory_repo.save(memory)
        tracker.set_attributes(
            {
                ATTR_MEMORY_RETRIEVED_COUNT: len(active_existing),
                ATTR_MEMORY_SAVED_COUNT: 1,
                "brew.memory.superseded": target_supersede_memory is not None,
                "brew.memory.scope": saved_memory.scope.value,
                "brew.memory.type": saved_memory.memory_type.value,
            }
        )
        logger.info(
            "Memory proposal approved and persisted",
            extra={
                "event_type": "memory.approved",
                "operation_name": "memory.approve",
                "memory_retrieved_count": len(active_existing),
                "memory_saved_count": 1,
                "result_status": "ok",
            },
        )
        return saved_memory

    async def reject_proposal(
        self,
        *,
        principal: AuthenticatedPrincipal,
        proposal_id: str,
        expected_version: int = 1,
        reason: str | None = None,
    ) -> MemoryProposal:
        """Reject a pending proposal so it is never persisted as an active memory."""
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

        sanitized_reason: str | None = None
        if reason is not None and reason.strip():
            sanitized_reason = sanitize_untrusted_text(reason, max_chars=500).text or None

        now = max(self._clock.now_utc(), proposal.created_at)
        try:
            rejected_proposal = proposal.mark_rejected(
                reviewed_at=now,
                rejection_reason=sanitized_reason,
            )
        except ValidationError as exc:
            raise translate_pydantic_error(exc) from exc

        saved = await self._proposal_repo.save(rejected_proposal, expected_version=expected_version)
        logger.info(
            "Memory proposal rejected by user",
            extra={"event_type": "memory.proposal_rejected"},
        )
        return saved

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

        cleaned_text = text
        if cleaned_text is not None:
            sanitized = sanitize_untrusted_text(cleaned_text, max_chars=1000)
            if sanitized.injection_detected:
                raise DomainValidationError(
                    "Updated memory text contains disallowed instruction-override directives."
                )
            sensitive_reason = detect_sensitive_or_third_party_assumption(sanitized.text)
            if sensitive_reason is not None:
                raise DomainValidationError(
                    f"Cannot persist memory containing {sensitive_reason}.",
                    code="SENSITIVE_MEMORY_REJECTED",
                )
            cleaned_text = sanitized.text

        now = max(self._clock.now_utc(), memory.created_at)
        try:
            updated = memory.apply_update(
                text=cleaned_text,
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
        """Delete an approved memory and archive its DELETED tombstone with provenance."""
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

        now = max(self._clock.now_utc(), memory.created_at)
        deleted_snapshot = memory.mark_deleted(deleted_at=now)
        await self._memory_repo.delete(
            uid,
            memory_id,
            expected_version=expected_version,
            deleted_snapshot=deleted_snapshot,
        )
        logger.info(
            "Approved memory deleted and removed from active retrieval",
            extra={"event_type": "memory.deleted"},
        )
