"""Brief refinement: the 9-step workflow from a revision request to a new brief version."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.briefs.context_assembly import ResilientBriefContextAssembler
from app.application.briefs.diagnostics import (
    WorkflowRunCounters,
    attach_failure_diagnostics,
    classify_domain_failure_state,
)
from app.application.briefs.idempotency import WorkflowIdempotencyGuard
from app.application.briefs.inputs import (
    ReviseWorkflowInput,
    compute_payload_fingerprint,
)
from app.application.briefs.synthesis import BriefSynthesisLoop
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
from app.domain.briefs.quality.refinement import parse_refinement_overrides
from app.domain.briefs.types import (
    BRIEF_REFINER_AGENT_NAME,
    BriefWorkflowOperation,
    BriefWorkflowTerminalState,
)
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.ports import MeetingRepository
from app.domain.meetings.types import MeetingTone
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import (
    AuthorizationError,
    BrewDomainError,
    EntityNotFoundError,
    VersionConflictError,
)

logger = logging.getLogger(__name__)


class BriefRefinementFlow:
    """Runs the 9-step brief refinement workflow for one request."""

    def __init__(
        self,
        *,
        context_assembler: ResilientBriefContextAssembler,
        idempotency: WorkflowIdempotencyGuard,
        synthesis: BriefSynthesisLoop,
        brief_agent: BriefCoachAgentPort,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        idempotency_repo: WorkflowIdempotencyRepository | None,
        clock: ClockPort,
    ) -> None:
        self._context_assembler = context_assembler
        self._idempotency = idempotency
        self._synthesis = synthesis
        self._brief_agent = brief_agent
        self._meeting_repo = meeting_repo
        self._brief_repo = brief_repo
        self._idempotency_repo = idempotency_repo
        self._clock = clock

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
        with (
            bind_workflow_correlation(request_id=request_id, trace_id=trace_id) as corr,
            brew_span(
                "brew.workflow.revise_brief",
                operation_name="workflow.revise_brief",
                tracer_name=__name__,
                agent_name=BRIEF_REFINER_AGENT_NAME,
                agent_version="1.0.0",
            ) as wf_tracker,
        ):
            counters = WorkflowRunCounters()
            degraded_sources: list[str] = []
            previous_version: int | None = None

            try:
                # Step 1: Receive and validate refinement request
                try:
                    validated_in = ReviseWorkflowInput(
                        brief_id=brief_id,
                        instructions=instructions,
                        expected_version=expected_version,
                        duration_minutes=duration_minutes,
                        tone=tone,
                    )
                except ValidationError as exc:
                    raise translate_pydantic_error(exc) from exc

                dedup_key = idempotency_key.strip() if idempotency_key else None
                fingerprint = compute_payload_fingerprint(
                    {
                        "owner_user_id": principal.user_id,
                        "operation": BriefWorkflowOperation.REVISE.value,
                        **validated_in.model_dump(mode="json"),
                    }
                )

                if dedup_key:
                    lock = self._idempotency.lock_for_idempotency_key(
                        principal.user_id,
                        BriefWorkflowOperation.REVISE,
                        dedup_key,
                    )
                    await lock.acquire()
                else:
                    lock = None

                try:
                    if dedup_key:
                        replayed = await self._idempotency.try_replay_idempotent_result(
                            owner_user_id=principal.user_id,
                            operation=BriefWorkflowOperation.REVISE,
                            idempotency_key=dedup_key,
                            payload_fingerprint=fingerprint,
                            request_id=corr.request_id,
                            trace_id=corr.trace_id,
                        )
                        if replayed is not None:
                            return replayed

                    # Step 2: Retrieve existing brief, enforce ownership & optimistic version
                    current_brief = await self._brief_repo.get_for_owner(
                        principal.user_id,
                        validated_in.brief_id,
                    )
                    if current_brief is None:
                        if await self._brief_repo.exists_for_any_owner(validated_in.brief_id):
                            raise AuthorizationError()
                        raise EntityNotFoundError(
                            entity_name="PreparationBrief",
                            entity_id=validated_in.brief_id,
                        )

                    previous_version = current_brief.version
                    if current_brief.version != validated_in.expected_version:
                        raise VersionConflictError(
                            entity_name="PreparationBrief",
                            entity_id=validated_in.brief_id,
                            expected_version=validated_in.expected_version,
                            actual_version=current_brief.version,
                        )

                    meeting = await self._meeting_repo.get_for_owner(
                        principal.user_id,
                        current_brief.meeting_id,
                    )
                    if meeting is None:
                        raise EntityNotFoundError(
                            entity_name="Meeting",
                            entity_id=current_brief.meeting_id,
                        )

                    contact = await self._context_assembler.resolve_owned_contact(
                        owner_user_id=principal.user_id,
                        contact_id=current_brief.contact_id,
                    )

                    resolution = parse_refinement_overrides(
                        validated_in.instructions,
                        explicit_duration_minutes=validated_in.duration_minutes,
                        explicit_tone=validated_in.tone,
                        fallback_duration_minutes=current_brief.duration_minutes,
                        fallback_tone=current_brief.tone,
                    )
                    target_duration = resolution.target_duration_minutes
                    target_tone = resolution.target_tone

                    # Step 3: Retrieve relevant preferences and approved memories
                    context = await self._context_assembler.assemble_resilient_context(
                        principal=principal,
                        contact=contact,
                        purpose=meeting.purpose,
                        objective=current_brief.meeting_objective,
                        degraded_sources=degraded_sources,
                        exclude_meeting_id=meeting.id,
                    )
                    counters.memories_retrieved = len(context.preference_memories) + len(
                        context.contact_memories
                    )

                    explicit_q_count = (
                        context.user_preferences.preferred_question_count
                        if context.user_preferences is not None
                        else len(current_brief.suggested_questions)
                    )
                    quality_policy = BriefQualityPolicy(explicit_question_count=explicit_q_count)
                    now = max(self._clock.now_utc(), current_brief.created_at)

                    def _build_revised_brief(content: GeneratedBriefContent) -> PreparationBrief:
                        return PreparationBrief(
                            id=current_brief.id,
                            owner_user_id=current_brief.owner_user_id,
                            meeting_id=current_brief.meeting_id,
                            contact_id=current_brief.contact_id,
                            duration_minutes=target_duration,
                            tone=target_tone,
                            contact_context=content.contact_context,
                            meeting_objective=content.meeting_objective,
                            conversation_openers=content.conversation_openers,
                            time_boxed_agenda=content.time_boxed_agenda,
                            suggested_questions=content.suggested_questions,
                            suggested_follow_up_topics=content.suggested_follow_up_topics,
                            referenced_memory_ids=content.referenced_memory_ids,
                            revision_summary=(
                                content.revision_summary or validated_in.instructions
                            ),
                            version=current_brief.version + 1,
                            created_at=current_brief.created_at,
                            updated_at=now,
                        )

                    # Steps 4-7: Refine, validate schema, check quality, single repair if needed
                    revised_brief = (
                        await self._synthesis.synthesize_and_validate_with_single_repair(
                            operation=BriefWorkflowOperation.REVISE,
                            invoke_attempt=lambda feedback, metrics: self._brief_agent.revise_brief(
                                current_brief=current_brief,
                                meeting=meeting,
                                context=context,
                                instructions=validated_in.instructions,
                                target_duration_minutes=target_duration,
                                target_tone=target_tone,
                                corrective_feedback=feedback,
                                attempt_metrics=metrics,
                            ),
                            build_candidate_brief=_build_revised_brief,
                            meeting=meeting,
                            context=context,
                            target_duration_minutes=target_duration,
                            target_tone=target_tone,
                            quality_policy=quality_policy,
                            counters=counters,
                            degraded_sources=degraded_sources,
                            current_brief=current_brief,
                            refinement=resolution,
                            refinement_instructions=validated_in.instructions,
                        )
                    )

                    # Step 8: Persist new version (archiving previous revision immutably)
                    with brew_span(
                        "brew.persistence.save_brief_artifacts",
                        operation_name="persistence.save_brief_artifacts",
                        tracer_name=__name__,
                        is_persistence=True,
                    ):
                        saved_brief = await self._brief_repo.save(
                            revised_brief,
                            expected_version=validated_in.expected_version,
                        )

                        saved_meeting = meeting
                        if (
                            target_duration != meeting.duration_minutes
                            or target_tone != meeting.tone
                            or revised_brief.meeting_objective != meeting.objective
                        ):
                            updated_meeting = Meeting(
                                id=meeting.id,
                                owner_user_id=meeting.owner_user_id,
                                contact_id=meeting.contact_id,
                                purpose=meeting.purpose,
                                tone=target_tone,
                                objective=revised_brief.meeting_objective,
                                duration_minutes=target_duration,
                                scheduled_at=meeting.scheduled_at,
                                notes=meeting.notes,
                                status=meeting.status,
                                latest_brief_id=saved_brief.id,
                                created_at=meeting.created_at,
                                updated_at=max(now, meeting.created_at),
                                version=meeting.version + 1,
                            )
                            saved_meeting = await self._meeting_repo.save(
                                updated_meeting,
                                expected_version=meeting.version,
                            )

                        if dedup_key and self._idempotency_repo is not None:
                            await self._idempotency_repo.save(
                                WorkflowIdempotencyRecord(
                                    owner_user_id=principal.user_id,
                                    operation=BriefWorkflowOperation.REVISE,
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
                        operation=BriefWorkflowOperation.REVISE,
                        terminal_state=terminal_state,
                        attempt_count=counters.attempt_count,
                        regeneration_count=counters.regeneration_count,
                        model_invocations=counters.model_invocations,
                        tool_invocations=counters.tool_invocations,
                        replayed=False,
                        quality_passed=True,
                        degraded_sources=degraded_sources,
                        previous_version=previous_version,
                    )
                    logger.info(
                        f"Preparation brief revised to v{saved_brief.version} "
                        f"(state={terminal_state.value})",
                        extra={
                            "event_type": "brief.revised",
                            "operation_name": "workflow.revise_brief",
                            "request_id": corr.request_id,
                            "trace_id": corr.trace_id,
                            "agent_name": BRIEF_REFINER_AGENT_NAME,
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
                    operation=BriefWorkflowOperation.REVISE,
                    terminal_state=classify_domain_failure_state(exc),
                    attempt_count=counters.attempt_count,
                    regeneration_count=counters.regeneration_count,
                    model_invocations=counters.model_invocations,
                    tool_invocations=counters.tool_invocations,
                    degraded_sources=degraded_sources,
                    previous_version=previous_version,
                ) from exc
