"""Steps 4 to 7 of the brief workflow: attempt, validate, single corrective regeneration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from pydantic import ValidationError

from app.application.briefs.diagnostics import WorkflowRunCounters
from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.shared.telemetry import (
    ATTR_REGENERATION_ATTEMPT,
    ATTR_VALIDATION_PASSED,
    ATTR_VALIDATION_STAGE,
    ATTR_VALIDATION_VIOLATION_COUNT,
    brew_span,
)
from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import PreparationBrief
from app.domain.briefs.ports import BriefAttemptMetrics, GeneratedBriefContent
from app.domain.briefs.quality.gate import evaluate_brief_quality
from app.domain.briefs.quality.policy import BriefQualityPolicy
from app.domain.briefs.quality.refinement import RefinementResolution
from app.domain.briefs.types import BriefWorkflowOperation, brief_specialist_agent_name
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingTone
from app.domain.shared.errors import ModelExecutionError, ModelOutputValidationError

logger = logging.getLogger(__name__)


class BriefSynthesisLoop:
    """Runs one attempt, validates it, and allows a single corrective regeneration."""

    def __init__(self, *, safeguards: BriefWorkflowSafeguardConfig) -> None:
        self._safeguards = safeguards

    async def synthesize_and_validate_with_single_repair(
        self,
        *,
        operation: BriefWorkflowOperation,
        invoke_attempt: Callable[
            [Sequence[str] | None, BriefAttemptMetrics],
            Awaitable[GeneratedBriefContent],
        ],
        build_candidate_brief: Callable[[GeneratedBriefContent], PreparationBrief],
        meeting: Meeting,
        context: BriefPreparationContext,
        target_duration_minutes: int,
        target_tone: MeetingTone,
        quality_policy: BriefQualityPolicy,
        counters: WorkflowRunCounters,
        degraded_sources: list[str],
        current_brief: PreparationBrief | None = None,
        refinement: RefinementResolution | None = None,
        refinement_instructions: str | None = None,
    ) -> PreparationBrief:
        """Execute Steps 4-7: synthesize, validate schema/quality, regenerate at most once."""
        max_attempts = 1 + self._safeguards.max_corrective_regenerations
        feedback: list[str] | None = None
        last_violations: list[str] = []

        for attempt in range(1, max_attempts + 1):
            counters.attempt_count = attempt
            remaining_budget = self._safeguards.max_model_invocations - counters.model_invocations
            if remaining_budget <= 0:
                raise ModelExecutionError(
                    "Exceeded maximum allowed model invocations for a single brief workflow "
                    f"request ({self._safeguards.max_model_invocations}).",
                    code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                )

            attempt_metrics = BriefAttemptMetrics(
                remaining_model_budget=remaining_budget,
                max_tool_retries=self._safeguards.max_tool_retries,
            )

            async def _execute_single_attempt(
                active_attempt: int,
                active_feedback: list[str] | None,
                metrics: BriefAttemptMetrics,
            ) -> tuple[PreparationBrief | None, list[str], BaseException | None]:
                try:
                    generated_raw = await invoke_attempt(active_feedback, metrics)
                except ModelOutputValidationError as exc:
                    violations = list(exc.violations) or [exc.message]
                    return None, violations, exc
                finally:
                    counters.model_invocations += metrics.model_invocations
                    counters.tool_invocations += metrics.tool_invocations
                    counters.input_tokens += metrics.input_tokens
                    counters.output_tokens += metrics.output_tokens
                    counters.total_tokens += metrics.total_tokens
                    for tool_name in metrics.degraded_tools:
                        if tool_name not in degraded_sources:
                            degraded_sources.append(tool_name)

                with brew_span(
                    "brew.output.validate",
                    operation_name="output.validate",
                    tracer_name=__name__,
                    agent_name=brief_specialist_agent_name(operation),
                    agent_version="1.0.0",
                    attributes={
                        ATTR_VALIDATION_STAGE: "domain_and_quality",
                        ATTR_REGENERATION_ATTEMPT: active_attempt - 1,
                    },
                ) as val_tracker:
                    try:
                        validated_content = GeneratedBriefContent.model_validate(
                            generated_raw.model_dump()
                            if isinstance(generated_raw, GeneratedBriefContent)
                            else generated_raw
                        )
                        if operation is BriefWorkflowOperation.REVISE and current_brief is not None:
                            validated_content = self._preserve_refinement_defaults(
                                revised=validated_content,
                                current_brief=current_brief,
                                context=context,
                                instructions=refinement_instructions or "",
                            )
                        candidate_brief = build_candidate_brief(validated_content)
                    except ValidationError as exc:
                        violations = [
                            f"[SCHEMA_INVALID] {'.'.join(str(p) for p in err.get('loc', ()))}: "
                            f"{err.get('msg', 'Invalid field')}"
                            for err in exc.errors()
                        ]
                        val_tracker.set_attributes(
                            {
                                ATTR_VALIDATION_PASSED: False,
                                ATTR_VALIDATION_VIOLATION_COUNT: len(violations),
                            }
                        )
                        val_tracker.mark_error(
                            "OUTPUT_VALIDATION_ERROR",
                            error_code="MODEL_OUTPUT_VALIDATION_ERROR",
                            error_type=type(exc).__name__,
                        )
                        return None, violations, exc

                    quality_report = evaluate_brief_quality(
                        validated_content,
                        meeting=meeting,
                        context=context,
                        target_duration_minutes=target_duration_minutes,
                        target_tone=target_tone,
                        policy=quality_policy,
                        current_brief=current_brief,
                        refinement=refinement,
                        refinement_instructions=refinement_instructions,
                    )
                    if quality_report.passed:
                        val_tracker.set_attributes(
                            {
                                ATTR_VALIDATION_PASSED: True,
                                ATTR_VALIDATION_VIOLATION_COUNT: 0,
                            }
                        )
                        return candidate_brief, [], None

                    violations = quality_report.formatted_feedback()
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: False,
                            ATTR_VALIDATION_VIOLATION_COUNT: len(violations),
                        }
                    )
                    val_tracker.mark_error(
                        "OUTPUT_VALIDATION_ERROR",
                        error_code="MODEL_OUTPUT_VALIDATION_ERROR",
                        error_type="BriefQualityViolation",
                    )
                    return None, violations, None

            if attempt > 1:
                with brew_span(
                    "brew.workflow.corrective_regeneration",
                    operation_name="workflow.corrective_regeneration",
                    tracer_name=__name__,
                    agent_name=brief_specialist_agent_name(operation),
                    agent_version="1.0.0",
                    attributes={
                        ATTR_REGENERATION_ATTEMPT: attempt - 1,
                        "brew.validation.prior_violation_count": len(feedback or ()),
                    },
                ) as regen_tracker:
                    candidate, last_violations, cause = await _execute_single_attempt(
                        attempt,
                        feedback,
                        attempt_metrics,
                    )
                    if candidate is not None:
                        regen_tracker.status = "repaired"
                        return candidate
                    regen_tracker.mark_error(
                        "OUTPUT_VALIDATION_ERROR",
                        error_code="MODEL_OUTPUT_VALIDATION_ERROR",
                        error_type=(
                            type(cause).__name__ if cause is not None else "BriefQualityViolation"
                        ),
                    )
            else:
                candidate, last_violations, cause = await _execute_single_attempt(
                    attempt,
                    feedback,
                    attempt_metrics,
                )
                if candidate is not None:
                    return candidate

            if attempt < max_attempts:
                counters.regeneration_count += 1
                feedback = last_violations
                logger.info(
                    "Triggering single corrective regeneration after output validation failure",
                    extra={
                        "event_type": "workflow.brief.corrective_regeneration",
                        "operation_name": "workflow.corrective_regeneration",
                        "agent_name": brief_specialist_agent_name(operation),
                        "attempt_count": attempt,
                        "regeneration_count": counters.regeneration_count,
                        "error_classification": "OUTPUT_VALIDATION_ERROR",
                    },
                )
                continue

            if isinstance(cause, ModelOutputValidationError):
                raise ModelOutputValidationError(
                    "Model output failed strict schema validation after corrective regeneration.",
                    violations=tuple(last_violations),
                ) from cause
            if isinstance(cause, ValidationError):
                raise ModelOutputValidationError(
                    "Generated preparation brief failed strict schema validation after "
                    "corrective regeneration.",
                    violations=tuple(last_violations),
                ) from cause
            raise ModelOutputValidationError(
                "Generated preparation brief failed deterministic quality checks after "
                "corrective regeneration.",
                violations=tuple(last_violations),
            )

        raise ModelOutputValidationError(
            "Generated preparation brief could not satisfy quality checks.",
            violations=tuple(last_violations),
        )

    @staticmethod
    def _preserve_refinement_defaults(
        *,
        revised: GeneratedBriefContent,
        current_brief: PreparationBrief,
        context: BriefPreparationContext,
        instructions: str,
    ) -> GeneratedBriefContent:
        """Retain grounded memories and unchanged fields sensibly during refinement."""
        active_context_ids = set(context.referenced_memory_ids)
        retained_ids: list[str] = []
        for mem_id in revised.referenced_memory_ids:
            if mem_id in active_context_ids and mem_id not in retained_ids:
                retained_ids.append(mem_id)
        for mem_id in current_brief.referenced_memory_ids:
            if mem_id in active_context_ids and mem_id not in retained_ids:
                retained_ids.append(mem_id)
        for mem_id in context.referenced_memory_ids:
            if mem_id not in retained_ids:
                retained_ids.append(mem_id)

        summary = revised.revision_summary or f"Refined brief: {instructions.strip()}"[:1000]
        follow_ups = (
            revised.suggested_follow_up_topics
            if revised.suggested_follow_up_topics
            else list(current_brief.suggested_follow_up_topics)
        )
        return revised.model_copy(
            update={
                "referenced_memory_ids": retained_ids[:50],
                "suggested_follow_up_topics": follow_ups,
                "revision_summary": summary,
            }
        )
