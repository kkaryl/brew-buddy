"""Initial brief generation: the 9-step workflow from validated input to persisted brief."""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import ValidationError

from app.application.briefs.context_assembly import ResilientBriefContextAssembler
from app.application.briefs.diagnostics import (
    WorkflowRunCounters,
    attach_failure_diagnostics,
    classify_domain_failure_state,
)
from app.application.briefs.idempotency import WorkflowIdempotencyGuard
from app.application.briefs.inputs import (
    GenerateWorkflowInput,
    compute_payload_fingerprint,
)
from app.application.briefs.synthesis import BriefSynthesisLoop
from app.application.memory.persistence import MemoryPersistenceService
from app.application.shared.correlation import bind_workflow_correlation
from app.application.shared.telemetry import (
    ATTR_INPUT_TOKENS,
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    ATTR_OUTPUT_TOKENS,
    ATTR_REGENERATION_COUNT,
    ATTR_TOTAL_TOKENS,
    brew_span,
)
from app.application.shared.validation import translate_pydantic_error
from app.domain.briefs.diagnostics import BriefWorkflowDiagnostics
from app.domain.briefs.models import (
    BriefWorkflowResult,
    PreparationBrief,
    WorkflowIdempotencyRecord,
)
from app.domain.briefs.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    GeneratedBriefContent,
    WorkflowIdempotencyRepository,
)
from app.domain.briefs.quality.policy import BriefQualityPolicy
from app.domain.briefs.types import (
    BRIEF_SYNTHESIZER_AGENT_NAME,
    BriefWorkflowOperation,
    BriefWorkflowTerminalState,
)
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingPurpose, MeetingStatus, MeetingTone
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import BrewDomainError
from app.domain.shared.ports import IdGeneratorPort

logger = logging.getLogger(__name__)


class BriefGenerationFlow:
    """Runs the 9-step initial brief generation workflow for one request."""

    def __init__(
        self,
        *,
        context_assembler: ResilientBriefContextAssembler,
        idempotency: WorkflowIdempotencyGuard,
        synthesis: BriefSynthesisLoop,
        memory_persistence: MemoryPersistenceService,
        brief_agent: BriefCoachAgentPort,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        idempotency_repo: WorkflowIdempotencyRepository | None,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._context_assembler = context_assembler
        self._idempotency = idempotency
        self._synthesis = synthesis
        self._memory_persistence = memory_persistence
        self._brief_agent = brief_agent
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._idempotency_repo = idempotency_repo
        self._clock = clock
        self._id_generator = id_generator

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
        with (
            bind_workflow_correlation(request_id=request_id, trace_id=trace_id) as corr,
            brew_span(
                "brew.workflow.generate_brief",
                operation_name="workflow.generate_brief",
                tracer_name=__name__,
                agent_name=BRIEF_SYNTHESIZER_AGENT_NAME,
                agent_version="1.0.0",
            ) as wf_tracker,
        ):
            counters = WorkflowRunCounters()
            degraded_sources: list[str] = []

            try:
                # Step 1: Receive and validate meeting context
                try:
                    validated_in = GenerateWorkflowInput(
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
                    )
                except ValidationError as exc:
                    raise translate_pydantic_error(exc) from exc

                dedup_key = idempotency_key.strip() if idempotency_key else None
                fingerprint = compute_payload_fingerprint(
                    {
                        "owner_user_id": principal.user_id,
                        "operation": BriefWorkflowOperation.GENERATE.value,
                        **validated_in.model_dump(mode="json"),
                    }
                )

                if dedup_key:
                    lock = self._idempotency.lock_for_idempotency_key(
                        principal.user_id,
                        BriefWorkflowOperation.GENERATE,
                        dedup_key,
                    )
                    await lock.acquire()
                else:
                    lock = None

                try:
                    if dedup_key:
                        replayed = await self._idempotency.try_replay_idempotent_result(
                            owner_user_id=principal.user_id,
                            operation=BriefWorkflowOperation.GENERATE,
                            idempotency_key=dedup_key,
                            payload_fingerprint=fingerprint,
                            request_id=corr.request_id,
                            trace_id=corr.trace_id,
                        )
                        if replayed is not None:
                            return replayed

                    # Step 2: Resolve contact and authenticated user before any writes
                    contact = await self._context_assembler.resolve_owned_contact(
                        owner_user_id=principal.user_id,
                        contact_id=validated_in.contact_id,
                    )

                    has_pref_overrides = (
                        validated_in.preferred_question_count is not None
                        or validated_in.communication_style_notes is not None
                        or validated_in.focus_areas is not None
                    )
                    if has_pref_overrides:
                        await self._memory_persistence.upsert_user_preferences(
                            principal=principal,
                            preferred_question_count=validated_in.preferred_question_count,
                            communication_style_notes=validated_in.communication_style_notes,
                            focus_areas=validated_in.focus_areas,
                        )

                    # Step 3: Retrieve relevant preferences, meeting history, and approved memories
                    context = await self._context_assembler.assemble_resilient_context(
                        principal=principal,
                        contact=contact,
                        purpose=validated_in.purpose,
                        objective=validated_in.meeting_objective,
                        degraded_sources=degraded_sources,
                    )
                    counters.memories_retrieved = len(context.preference_memories) + len(
                        context.contact_memories
                    )

                    now = self._clock.now_utc()
                    meeting_id = self._id_generator.new_id("mtg")
                    brief_id = self._id_generator.new_id("brf")

                    meeting = Meeting(
                        id=meeting_id,
                        owner_user_id=principal.user_id,
                        contact_id=contact.id,
                        purpose=validated_in.purpose,
                        tone=validated_in.tone,
                        objective=validated_in.meeting_objective,
                        duration_minutes=validated_in.duration_minutes,
                        scheduled_at=validated_in.scheduled_at,
                        notes=validated_in.meeting_notes,
                        status=MeetingStatus.PREPARING,
                        latest_brief_id=brief_id,
                        created_at=now,
                        updated_at=now,
                        version=1,
                    )

                    explicit_q_count = (
                        validated_in.preferred_question_count
                        if validated_in.preferred_question_count is not None
                        else (
                            context.user_preferences.preferred_question_count
                            if context.user_preferences is not None
                            else None
                        )
                    )
                    quality_policy = BriefQualityPolicy(explicit_question_count=explicit_q_count)

                    def _build_initial_brief(content: GeneratedBriefContent) -> PreparationBrief:
                        return PreparationBrief(
                            id=brief_id,
                            owner_user_id=principal.user_id,
                            meeting_id=meeting.id,
                            contact_id=contact.id,
                            duration_minutes=meeting.duration_minutes,
                            tone=meeting.tone,
                            contact_context=content.contact_context,
                            meeting_objective=content.meeting_objective,
                            conversation_openers=content.conversation_openers,
                            time_boxed_agenda=content.time_boxed_agenda,
                            suggested_questions=content.suggested_questions,
                            suggested_follow_up_topics=content.suggested_follow_up_topics,
                            referenced_memory_ids=content.referenced_memory_ids,
                            revision_summary=content.revision_summary,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        )

                    # Steps 4-7: Generate, validate schema, check quality, single repair if needed
                    validated_brief = (
                        await self._synthesis.synthesize_and_validate_with_single_repair(
                            operation=BriefWorkflowOperation.GENERATE,
                            invoke_attempt=lambda feedback, metrics: (
                                self._brief_agent.generate_brief(
                                    meeting=meeting,
                                    context=context,
                                    corrective_feedback=feedback,
                                    attempt_metrics=metrics,
                                )
                            ),
                            build_candidate_brief=_build_initial_brief,
                            meeting=meeting,
                            context=context,
                            target_duration_minutes=meeting.duration_minutes,
                            target_tone=meeting.tone,
                            quality_policy=quality_policy,
                            counters=counters,
                            degraded_sources=degraded_sources,
                        )
                    )

                    # Step 8: Persist versioned meeting and preparation brief (with snapshot)
                    with brew_span(
                        "brew.persistence.save_brief_artifacts",
                        operation_name="persistence.save_brief_artifacts",
                        tracer_name=__name__,
                        is_persistence=True,
                    ):
                        saved_meeting = await self._meeting_repo.save(meeting)
                        saved_brief = await self._brief_repo.save(validated_brief)

                        if dedup_key and self._idempotency_repo is not None:
                            await self._idempotency_repo.save(
                                WorkflowIdempotencyRecord(
                                    owner_user_id=principal.user_id,
                                    operation=BriefWorkflowOperation.GENERATE,
                                    idempotency_key=dedup_key,
                                    payload_fingerprint=fingerprint,
                                    brief_id=saved_brief.id,
                                    brief_version=saved_brief.version,
                                    meeting_id=saved_meeting.id,
                                    created_at=now,
                                )
                            )

                    terminal_state = (
                        BriefWorkflowTerminalState.COMPLETED_REPAIRED
                        if counters.regeneration_count > 0
                        else BriefWorkflowTerminalState.COMPLETED
                    )
                    wf_tracker.status = terminal_state.value
                    wf_tracker.set_attributes(
                        {
                            ATTR_MEMORY_RETRIEVED_COUNT: counters.memories_retrieved,
                            ATTR_MEMORY_SAVED_COUNT: 0,
                            ATTR_REGENERATION_COUNT: counters.regeneration_count,
                            ATTR_INPUT_TOKENS: (
                                counters.input_tokens if counters.input_tokens > 0 else None
                            ),
                            ATTR_OUTPUT_TOKENS: (
                                counters.output_tokens if counters.output_tokens > 0 else None
                            ),
                            ATTR_TOTAL_TOKENS: (
                                counters.total_tokens if counters.total_tokens > 0 else None
                            ),
                        }
                    )
                    diagnostics = BriefWorkflowDiagnostics(
                        request_id=corr.request_id,
                        trace_id=corr.trace_id,
                        operation=BriefWorkflowOperation.GENERATE,
                        terminal_state=terminal_state,
                        attempt_count=counters.attempt_count,
                        regeneration_count=counters.regeneration_count,
                        model_invocations=counters.model_invocations,
                        tool_invocations=counters.tool_invocations,
                        replayed=False,
                        quality_passed=True,
                        degraded_sources=degraded_sources,
                        previous_version=None,
                    )
                    logger.info(
                        f"Preparation brief generated (state={terminal_state.value})",
                        extra={
                            "event_type": "brief.generated",
                            "operation_name": "workflow.generate_brief",
                            "request_id": corr.request_id,
                            "trace_id": corr.trace_id,
                            "agent_name": BRIEF_SYNTHESIZER_AGENT_NAME,
                            "agent_version": "1.0.0",
                            "result_status": terminal_state.value,
                            "memory_retrieved_count": counters.memories_retrieved,
                            "memory_saved_count": 0,
                            "attempt_count": counters.attempt_count,
                            "regeneration_count": counters.regeneration_count,
                            "input_tokens": (
                                counters.input_tokens if counters.input_tokens > 0 else None
                            ),
                            "output_tokens": (
                                counters.output_tokens if counters.output_tokens > 0 else None
                            ),
                            "total_tokens": (
                                counters.total_tokens if counters.total_tokens > 0 else None
                            ),
                        },
                    )
                    # Step 9: Return structured workflow result
                    return BriefWorkflowResult(
                        brief=saved_brief,
                        meeting=saved_meeting,
                        diagnostics=diagnostics,
                    )
                finally:
                    if lock is not None and lock.locked():
                        lock.release()
            except BrewDomainError as exc:
                raise attach_failure_diagnostics(
                    exc,
                    request_id=corr.request_id,
                    trace_id=corr.trace_id,
                    operation=BriefWorkflowOperation.GENERATE,
                    terminal_state=classify_domain_failure_state(exc),
                    attempt_count=counters.attempt_count,
                    regeneration_count=counters.regeneration_count,
                    model_invocations=counters.model_invocations,
                    tool_invocations=counters.tool_invocations,
                    degraded_sources=degraded_sources,
                ) from exc
