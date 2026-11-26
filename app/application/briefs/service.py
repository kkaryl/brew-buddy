"""Async application use cases generating, retrieving, and revising preparation briefs."""

from __future__ import annotations

import logging
from datetime import datetime

from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.briefs.workflow import MeetingPreparationWorkflow
from app.application.memory.persistence import MemoryPersistenceService
from app.application.memory.retrieval import MemoryRetrievalService
from app.application.shared.telemetry import brew_span
from app.domain.briefs.models import BriefWorkflowResult, PreparationBrief
from app.domain.briefs.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    WorkflowIdempotencyRepository,
)
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingPurpose, MeetingTone
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthorizationError, EntityNotFoundError, VersionConflictError
from app.domain.shared.ports import IdGeneratorPort

logger = logging.getLogger(__name__)


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

    async def delete_brief(
        self,
        *,
        principal: AuthenticatedPrincipal,
        brief_id: str,
        expected_version: int | None = None,
    ) -> None:
        """Delete an owned preparation brief, its revisions, and unlink or prune its meeting."""
        uid = principal.user_id
        with brew_span(
            "brew.brief.delete",
            operation_name="brief.delete",
            tracer_name=__name__,
        ) as tracker:
            brief = await self.get_brief(principal=principal, brief_id=brief_id)
            if expected_version is not None and brief.version != expected_version:
                raise VersionConflictError(
                    entity_name="PreparationBrief",
                    entity_id=brief_id,
                    expected_version=expected_version,
                    actual_version=brief.version,
                )

            await self._brief_repo.delete(uid, brief.id, expected_version=expected_version)

            meeting = await self._meeting_repo.get_for_owner(uid, brief.meeting_id)
            if meeting is not None and meeting.owner_user_id == uid:
                remaining = await self._brief_repo.list_by_meeting(uid, meeting.id)
                if not remaining and meeting.notes is None:
                    await self._meeting_repo.delete(uid, meeting.id)
                elif meeting.latest_brief_id == brief.id:
                    next_latest = remaining[-1].id if remaining else None
                    updated_meeting = meeting.model_copy(
                        update={
                            "latest_brief_id": next_latest,
                            "updated_at": max(self._clock.now_utc(), meeting.created_at),
                            "version": meeting.version + 1,
                        }
                    )
                    await self._meeting_repo.save(
                        updated_meeting,
                        expected_version=meeting.version,
                    )

            logger.info(
                "Preparation brief deleted",
                extra={
                    "event_type": "brief.deleted",
                    "operation_name": "brief.delete",
                    "result_status": tracker.status,
                },
            )
