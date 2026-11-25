"""Proposal review: list staged proposals, approve one into a memory, or reject it."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.safety.untrusted_text import sanitize_untrusted_text
from app.application.shared.telemetry import (
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    SpanOutcomeTracker,
    brew_span,
)
from app.application.shared.validation import translate_pydantic_error
from app.domain.contacts.models import Contact
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.memory.attribution import ensure_attributed_epistemic_text
from app.domain.memory.models import Memory, MemoryProposal, MemorySource
from app.domain.memory.ports import MemoryProposalRepository, MemoryRepository
from app.domain.memory.relations import MemoryRelationKind, classify_candidate_against_existing
from app.domain.memory.sensitivity import detect_sensitive_or_third_party_assumption
from app.domain.memory.types import ConsentStatus, MemoryLifecycleState, MemoryType, ProposalStatus
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import (
    AuthorizationError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.shared.ports import IdGeneratorPort

logger = logging.getLogger(__name__)


class MemoryProposalReviewer:
    """Lists staged proposals and applies the user's approve or reject decision."""

    def __init__(
        self,
        *,
        proposal_repo: MemoryProposalRepository,
        memory_repo: MemoryRepository,
        contact_repo: ContactRepository,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._proposal_repo = proposal_repo
        self._memory_repo = memory_repo
        self._contact_repo = contact_repo
        self._clock = clock
        self._id_generator = id_generator

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

        # A heuristic SUPERSEDES verdict computed here is deliberately not applied. The only
        # memory an approval may deactivate is one the user was shown as the target: staged
        # on the proposal at review time, or named in this approval request. Anything the
        # classifier notices only now stays active alongside the new memory.

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
