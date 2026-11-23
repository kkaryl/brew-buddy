"""Async application services orchestrating contacts, meetings, briefs, and memory facade."""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from app.application.brief_workflow import (
    BriefWorkflowSafeguardConfig,
    MeetingPreparationWorkflow,
)
from app.application.memory_persistence_service import (
    MemoryPersistenceService,
    translate_pydantic_error,
)
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.domain.errors import (
    AuthorizationError,
    EntityNotFoundError,
)
from app.domain.health import ClockPort
from app.domain.models import (
    AuthenticatedPrincipal,
    BriefWorkflowResult,
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
    WorkflowIdempotencyRepository,
)
from app.domain.types import (
    ConsentStatus,
    MeetingPurpose,
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
        idempotency_repo: WorkflowIdempotencyRepository | None = None,
        safeguards: BriefWorkflowSafeguardConfig | None = None,
    ) -> None:
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._memory_retrieval = memory_retrieval
        self._memory_persistence = memory_persistence
        self._brief_agent = brief_agent
        self._clock = clock
        self._id_generator = id_generator
        self._workflow = MeetingPreparationWorkflow(
            preferences_repo=memory_retrieval.preferences_repo,
            contact_repo=memory_retrieval.contact_repo,
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            memory_repo=memory_retrieval.memory_repo,
            memory_persistence=memory_persistence,
            brief_agent=brief_agent,
            clock=clock,
            id_generator=id_generator,
            idempotency_repo=idempotency_repo,
            safeguards=safeguards,
            context_budget=memory_retrieval.default_budget,
        )

    @property
    def workflow(self) -> MeetingPreparationWorkflow:
        """Return the underlying 9-step ``MeetingPreparationWorkflow`` orchestrator."""
        return self._workflow

    async def generate_brief_workflow(
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
        idempotency_key: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> BriefWorkflowResult:
        """Execute the full 9-step generation workflow and return structured diagnostics."""
        return await self._workflow.execute_generation(
            principal=principal,
            contact_id=contact_id,
            purpose=purpose,
            tone=tone,
            meeting_objective=meeting_objective,
            duration_minutes=duration_minutes,
            scheduled_at=scheduled_at,
            meeting_notes=meeting_notes,
            preferred_question_count=preferred_question_count,
            communication_style_notes=communication_style_notes,
            focus_areas=focus_areas,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
        )

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
        idempotency_key: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> PreparationBrief:
        """Assemble bounded user-scoped context, create a meeting, and synthesize a brief."""
        result = await self.generate_brief_workflow(
            principal=principal,
            contact_id=contact_id,
            purpose=purpose,
            tone=tone,
            meeting_objective=meeting_objective,
            duration_minutes=duration_minutes,
            scheduled_at=scheduled_at,
            meeting_notes=meeting_notes,
            preferred_question_count=preferred_question_count,
            communication_style_notes=communication_style_notes,
            focus_areas=focus_areas,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
        )
        return result.brief

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

    async def list_brief_revisions(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
    ) -> list[PreparationBrief]:
        """List all immutable historical revisions for an owned preparation brief."""
        await self.get_brief(principal=principal, brief_id=brief_id)
        return await self._brief_repo.list_revisions(principal.user_id, brief_id)

    async def revise_brief_workflow(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
        instructions: str,
        expected_version: int,
        duration_minutes: int | None = None,
        tone: MeetingTone | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> BriefWorkflowResult:
        """Execute the full 9-step refinement workflow and return structured diagnostics."""
        return await self._workflow.execute_refinement(
            principal=principal,
            brief_id=brief_id,
            instructions=instructions,
            expected_version=expected_version,
            duration_minutes=duration_minutes,
            tone=tone,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
        )

    async def revise_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
        instructions: str,
        expected_version: int,
        duration_minutes: int | None = None,
        tone: MeetingTone | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> PreparationBrief:
        """Revise an existing preparation brief enforcing optimistic version control."""
        result = await self.revise_brief_workflow(
            principal=principal,
            brief_id=brief_id,
            instructions=instructions,
            expected_version=expected_version,
            duration_minutes=duration_minutes,
            tone=tone,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
        )
        return result.brief


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
