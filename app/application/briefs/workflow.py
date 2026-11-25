"""End-to-end 9-step Meeting Preparation & Refinement Workflow with orchestration safeguards."""

from __future__ import annotations

from datetime import datetime

from app.application.briefs.context_assembly import ResilientBriefContextAssembler
from app.application.briefs.generate import BriefGenerationFlow
from app.application.briefs.idempotency import WorkflowIdempotencyGuard
from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.briefs.refine import BriefRefinementFlow
from app.application.briefs.synthesis import BriefSynthesisLoop
from app.application.memory.persistence import MemoryPersistenceService
from app.domain.briefs.context import ContextBudget
from app.domain.briefs.models import BriefWorkflowResult
from app.domain.briefs.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    WorkflowIdempotencyRepository,
)
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingPurpose, MeetingTone
from app.domain.memory.ports import MemoryRepository, UserPreferencesRepository
from app.domain.shared.clock import ClockPort
from app.domain.shared.ports import IdGeneratorPort


class MeetingPreparationWorkflow:
    """Orchestrates Brew's 9-step Meeting Preparation & Refinement Workflow.

    Steps:
    1. Receive and validate meeting context (and deduplicate via idempotency key).
    2. Resolve the contact (and existing brief on refinement) under authenticated user.
    3. Retrieve relevant preferences, meeting history, and approved memories.
    4. Generate or refine the preparation brief via the configured coach port (ADK Gemini).
    5. Validate the output against strict Pydantic & domain schemas.
    6. Apply deterministic quality, grounding, tone, agenda, and redundancy checks.
    7. Perform at most one corrective regeneration if validation or quality checks fail.
    8. Persist the versioned brief (and archive prior revisions without silent overwrite).
    9. Return a structured ``BriefWorkflowResult`` with correlation & safeguard diagnostics.
    """

    def __init__(
        self,
        *,
        preferences_repo: UserPreferencesRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        memory_repo: MemoryRepository,
        memory_persistence: MemoryPersistenceService,
        brief_agent: BriefCoachAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        idempotency_repo: WorkflowIdempotencyRepository | None = None,
        safeguards: BriefWorkflowSafeguardConfig | None = None,
        context_budget: ContextBudget | None = None,
    ) -> None:
        self._preferences_repo = preferences_repo
        self._contact_repo = contact_repo
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._memory_repo = memory_repo
        self._memory_persistence = memory_persistence
        self._brief_agent = brief_agent
        self._clock = clock
        self._id_generator = id_generator
        self._idempotency_repo = idempotency_repo
        self._safeguards = safeguards or BriefWorkflowSafeguardConfig()
        self._context_budget = context_budget or ContextBudget()
        self._idempotency = WorkflowIdempotencyGuard(
            idempotency_repo=idempotency_repo,
            brief_repo=brief_repo,
            meeting_repo=meeting_repo,
        )
        self._synthesis = BriefSynthesisLoop(safeguards=self._safeguards)
        self._context_assembler = ResilientBriefContextAssembler(
            preferences_repo=preferences_repo,
            contact_repo=contact_repo,
            meeting_repo=meeting_repo,
            memory_repo=memory_repo,
            safeguards=self._safeguards,
            context_budget=self._context_budget,
        )
        self._generation = BriefGenerationFlow(
            context_assembler=self._context_assembler,
            idempotency=self._idempotency,
            synthesis=self._synthesis,
            memory_persistence=memory_persistence,
            brief_agent=brief_agent,
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            idempotency_repo=idempotency_repo,
            clock=clock,
            id_generator=id_generator,
        )
        self._refinement = BriefRefinementFlow(
            context_assembler=self._context_assembler,
            idempotency=self._idempotency,
            synthesis=self._synthesis,
            brief_agent=brief_agent,
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            idempotency_repo=idempotency_repo,
            clock=clock,
        )

    async def execute_generation(
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
        """Execute Brew's end-to-end 9-step initial brief generation workflow."""
        return await self._generation.execute_generation(
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

    async def execute_refinement(
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
        """Execute Brew's end-to-end 9-step brief refinement workflow."""
        return await self._refinement.execute_refinement(
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
