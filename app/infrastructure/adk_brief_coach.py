"""ADK brief-specialist adapter implementing ``BriefCoachAgentPort`` for brief workflows.

Two specialist agents serve the workflow, each routed to its own model:
``brief_synthesizer`` writes the first draft on the synthesis model, and ``brief_refiner``
applies one revision on the refinement model (see ``app/model_routing.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Sequence

from google.adk.agents.llm_agent import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.apps.app import App
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from opentelemetry import trace
from pydantic import ValidationError

from app.application.correlation import resolve_or_create_correlation
from app.application.telemetry import (
    ATTR_INPUT_TOKENS,
    ATTR_OUTPUT_TOKENS,
    ATTR_TOTAL_TOKENS,
    ATTR_VALIDATION_PASSED,
    ATTR_VALIDATION_STAGE,
    ATTR_VALIDATION_VIOLATION_COUNT,
    brew_span,
)
from app.config import AppSettings, get_settings
from app.domain.errors import (
    BrewDomainError,
    ModelExecutionError,
    ModelOutputValidationError,
    ModelTimeoutError,
)
from app.domain.models import (
    BriefPreparationContext,
    Meeting,
    PreparationBrief,
)
from app.domain.ports import BriefAttemptMetrics, GeneratedBriefContent
from app.domain.types import (
    BriefWorkflowOperation,
    MeetingDurationMinutes,
    MeetingTone,
    brief_specialist_agent_name,
)
from app.infrastructure.observability import build_adk_telemetry_config
from app.model_routing import ModelStage, build_gemini_model, resolve_model_id
from app.plugins.coach_guardrails import ConversationCoachGuardrailPlugin
from app.plugins.workflow_safeguards import WorkflowSafeguardPlugin
from app.prompts import (
    BRIEF_REFINER_INSTRUCTION,
    BRIEF_SPECIALIST_VERSION,
    BRIEF_SYNTHESIZER_INSTRUCTION,
)
from app.tools.coaching_tools import CoachingToolDependencies, build_coaching_tools

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)

BRIEF_WORKFLOW_JSON_CONTRACT = """

## Structured Brief Workflow Output Contract
You are executing inside Brew's automated Meeting Preparation Workflow.
1. `contact`, `user_preferences`, `approved_preference_memories`, and `approved_contact_memories`
   are ALREADY pre-loaded in the `BASELINE_GROUNDING_CONTEXT` JSON in this prompt; do NOT re-call
   `get_user_preferences` or `get_contact_context` when that context is already provided. Only call
   `get_meeting_history` if checking prior sessions for a returning contact is genuinely needed.
2. If any tool returns `status="error"`, do NOT loop retries endlessly and NEVER invent missing
   history or biographical details.
3. Never use em-dashes in any generated text field (`contact_context`, `meeting_objective`,
   `conversation_openers`, `time_boxed_agenda`, `suggested_questions`,
   `suggested_follow_up_topics`, or `revision_summary`). Use periods, commas, colons, or middle
   dots instead.
4. Return ONLY a single valid JSON object (no markdown commentary outside JSON) conforming to:
   - `contact_context` (string, 3-2000 chars): Grounded counterpart summary using ONLY verified
     facts from the contact profile, retrieved memories, and meeting input. Never invent degrees,
     past employers, tenure, publications, or private characteristics.
   - `meeting_objective` (string, 3-500 chars): Concrete goal for this session.
   - `conversation_openers` (array of 2 to 3 strings): Tailored openers matching the target tone.
   - `time_boxed_agenda` (array of 2 to 6 objects `{title, duration_minutes, description}`):
     Realistic segments whose `duration_minutes` sum STRICTLY to the target `duration_minutes`.
   - `suggested_questions` (array of 5 to 8 objects `{id, question, rationale, category}`, unless
     an explicit `preferred_question_count` is specified): Prioritized, non-redundant open-ended
     questions whose `rationale` explains how each question advances the meeting goal.
   - `suggested_follow_up_topics` (array of 1 to 6 strings): Concrete follow-up threads.
   - `referenced_memory_ids` (array of strings): ONLY memory IDs present in approved context.
   - `revision_summary` (string or null): Null on initial generation; concise summary of applied
     changes on brief refinement.
"""


def _strip_optional_json_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    match = _JSON_FENCE_RE.match(cleaned)
    if match is not None:
        return match.group(1).strip()
    return cleaned


def _format_baseline_context_payload(context: BriefPreparationContext) -> dict[str, object]:
    """Serialize verified pre-brief context as untrusted structured data for grounding."""
    prefs = context.user_preferences
    return {
        "data_trust_level": "untrusted_user_data",
        "contact": {
            "id": context.contact.id,
            "name": context.contact.name,
            "title": context.contact.title,
            "role": context.contact.role,
            "organization": context.contact.organization,
            "context_notes": context.contact.context_notes,
        },
        "user_preferences": (
            {
                "default_tone": prefs.default_tone.value,
                "default_duration_minutes": prefs.default_duration_minutes,
                "preferred_question_count": prefs.preferred_question_count,
                "communication_style_notes": prefs.communication_style_notes,
                "focus_areas": list(prefs.focus_areas),
            }
            if prefs is not None
            else None
        ),
        "approved_preference_memories": [
            {
                "memory_id": item.memory_id,
                "type": item.memory_type.value,
                "epistemic_status": item.epistemic_status.value,
                "source_type": item.source.source_type.value,
                "recorded_at_utc": item.source.recorded_at.isoformat(),
                "text": item.text,
            }
            for item in context.preference_memories
        ],
        "approved_contact_memories": [
            {
                "memory_id": item.memory_id,
                "type": item.memory_type.value,
                "epistemic_status": item.epistemic_status.value,
                "source_type": item.source.source_type.value,
                "meeting_id": item.source.meeting_id,
                "recorded_at_utc": item.source.recorded_at.isoformat(),
                "text": item.text,
            }
            for item in context.contact_memories
        ],
        "recent_meetings": [
            {
                "meeting_id": item.meeting_id,
                "purpose": item.purpose.value,
                "objective": item.objective,
                "duration_minutes": item.duration_minutes,
                "notes_excerpt": item.notes_excerpt,
            }
            for item in context.recent_meetings
        ],
        "allowed_referenced_memory_ids": context.referenced_memory_ids,
    }


def _build_generation_prompt(
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    corrective_feedback: Sequence[str] | None,
) -> str:
    target_q_desc = (
        f"exactly {context.user_preferences.preferred_question_count}"
        if context.user_preferences is not None
        else "5 to 8"
    )
    payload = {
        "workflow_task": "generate_preparation_brief",
        "meeting": {
            "id": meeting.id,
            "contact_id": meeting.contact_id,
            "purpose": meeting.purpose.value,
            "tone": meeting.tone.value,
            "objective": meeting.objective,
            "duration_minutes": meeting.duration_minutes,
            "notes": meeting.notes,
        },
        "quality_requirements": {
            "openers": "2 to 3 tailored openers",
            "questions": f"{target_q_desc} non-redundant questions with goal-linked rationales",
            "agenda_total_minutes": meeting.duration_minutes,
        },
        "verified_baseline_context": _format_baseline_context_payload(context),
    }
    prompt = (
        "Synthesize an initial meeting preparation brief in strict JSON format.\n"
        f"REQUEST_PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if corrective_feedback:
        joined = "\n".join(f"- {item}" for item in corrective_feedback)
        prompt += (
            "\n\n[CORRECTIVE REGENERATION REQUIRED — FIX ALL VIOLATIONS]\n"
            "Your previous candidate brief failed validation. Regenerate a complete valid JSON "
            f"brief fixing every item below:\n{joined}"
        )
    return prompt


def _build_refinement_prompt(
    *,
    current_brief: PreparationBrief,
    meeting: Meeting,
    context: BriefPreparationContext,
    instructions: str,
    target_duration_minutes: int,
    target_tone: MeetingTone,
    corrective_feedback: Sequence[str] | None,
) -> str:
    payload = {
        "workflow_task": "refine_preparation_brief",
        "refinement_instructions": instructions,
        "target_duration_minutes": target_duration_minutes,
        "target_tone": target_tone.value,
        "current_brief_version": current_brief.version,
        "current_brief": {
            "contact_context": current_brief.contact_context,
            "meeting_objective": current_brief.meeting_objective,
            "conversation_openers": list(current_brief.conversation_openers),
            "time_boxed_agenda": [
                item.model_dump(mode="json") for item in current_brief.time_boxed_agenda
            ],
            "suggested_questions": [
                item.model_dump(mode="json") for item in current_brief.suggested_questions
            ],
            "suggested_follow_up_topics": list(current_brief.suggested_follow_up_topics),
            "referenced_memory_ids": list(current_brief.referenced_memory_ids),
        },
        "meeting": {
            "id": meeting.id,
            "contact_id": meeting.contact_id,
            "purpose": meeting.purpose.value,
            "objective": meeting.objective,
        },
        "verified_baseline_context": _format_baseline_context_payload(context),
    }
    prompt = (
        "Refine the existing preparation brief according to `refinement_instructions`, "
        "preserving unchanged context sensibly and adapting the agenda strictly to "
        "`target_duration_minutes` and `target_tone`.\n"
        f"REFINEMENT_PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if corrective_feedback:
        joined = "\n".join(f"- {item}" for item in corrective_feedback)
        prompt += (
            "\n\n[CORRECTIVE REGENERATION REQUIRED — FIX ALL VIOLATIONS]\n"
            "Your previous refined brief failed validation. Regenerate a complete valid JSON "
            f"brief fixing every item below:\n{joined}"
        )
    return prompt


_SPECIALIST_STAGE: dict[BriefWorkflowOperation, ModelStage] = {
    BriefWorkflowOperation.GENERATE: ModelStage.BRIEF_SYNTHESIS,
    BriefWorkflowOperation.REVISE: ModelStage.BRIEF_REFINEMENT,
}
_SPECIALIST_INSTRUCTION: dict[BriefWorkflowOperation, str] = {
    BriefWorkflowOperation.GENERATE: BRIEF_SYNTHESIZER_INSTRUCTION,
    BriefWorkflowOperation.REVISE: BRIEF_REFINER_INSTRUCTION,
}
_SPECIALIST_DESCRIPTION: dict[BriefWorkflowOperation, str] = {
    BriefWorkflowOperation.GENERATE: (
        "Brew Brief Synthesizer. Writes the first structured preparation brief, grounded in "
        "user-approved context."
    ),
    BriefWorkflowOperation.REVISE: (
        "Brew Brief Refiner. Applies one revision instruction to an existing preparation brief."
    ),
}


class AdkConversationCoachBriefAdapter:
    """Runs Brew's ``brief_synthesizer`` and ``brief_refiner`` specialists with read tools."""

    def __init__(
        self,
        *,
        tool_dependencies: CoachingToolDependencies,
        settings: AppSettings | None = None,
        model_override: BaseLlm | None = None,
        model_timeout_seconds: float | None = None,
        max_total_tool_calls: int = 8,
    ) -> None:
        self._settings = settings or get_settings()
        self._tool_dependencies = tool_dependencies
        self._model_override = model_override
        self._model_timeout_seconds = (
            model_timeout_seconds
            if model_timeout_seconds is not None
            else self._settings.model_workflow_timeout_seconds
        )
        self._max_total_tool_calls = max_total_tool_calls

    def _build_workflow_agent(self, operation: BriefWorkflowOperation) -> Agent:
        """Build the specialist for ``operation`` on the model routed to its stage."""
        timeout_ms = int(self._model_timeout_seconds * 1000)
        active_model = (
            self._model_override
            if self._model_override is not None
            else build_gemini_model(self._settings, stage=_SPECIALIST_STAGE[operation])
        )
        return Agent(
            name=brief_specialist_agent_name(operation),
            description=_SPECIALIST_DESCRIPTION[operation],
            model=active_model,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.2,
                http_options=types.HttpOptions(timeout=timeout_ms),
            ),
            instruction=_SPECIALIST_INSTRUCTION[operation] + BRIEF_WORKFLOW_JSON_CONTRACT,
            tools=build_coaching_tools(
                self._tool_dependencies,
                include_memory_staging=False,
            ),
        )

    async def _run_coach_turn(
        self,
        *,
        operation: BriefWorkflowOperation,
        owner_user_id: str,
        prompt: str,
        span_name: str,
        attempt_metrics: BriefAttemptMetrics | None,
    ) -> GeneratedBriefContent:
        corr = resolve_or_create_correlation()
        metrics = attempt_metrics if attempt_metrics is not None else BriefAttemptMetrics()

        if metrics.remaining_model_budget <= 0:
            raise ModelExecutionError(
                "No remaining model invocation budget for this workflow request.",
                code="MODEL_INVOCATION_LIMIT_EXCEEDED",
            )

        coach_agent = self._build_workflow_agent(operation)
        resolved_model_name = getattr(coach_agent.model, "model", None) or resolve_model_id(
            self._settings, _SPECIALIST_STAGE[operation]
        )
        safeguard_plugin = WorkflowSafeguardPlugin(
            attempt_metrics=metrics,
            max_total_tool_calls=self._max_total_tool_calls,
        )
        guardrail_plugin = ConversationCoachGuardrailPlugin(
            agent_version=BRIEF_SPECIALIST_VERSION,
            model_name=str(resolved_model_name),
        )
        adk_app = App(
            name="app",
            root_agent=coach_agent,
            plugins=[guardrail_plugin, safeguard_plugin],
        )
        session_service = InMemorySessionService()
        runner = Runner(
            app=adk_app,
            session_service=session_service,
            auto_create_session=True,
        )
        session_id = f"wf_{corr.request_id}_{uuid.uuid4().hex[:8]}"
        run_config = RunConfig(
            max_llm_calls=metrics.remaining_model_budget,
            telemetry=build_adk_telemetry_config(self._settings),
        )

        async def _collect_final_text() -> str:
            final_text_chunks: list[str] = []
            async for event in runner.run_async(
                user_id=owner_user_id,
                session_id=session_id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                ),
                run_config=run_config,
            ):
                if getattr(event, "error_message", None):
                    if safeguard_plugin.budget_exceeded or (
                        getattr(event, "error_code", None) == "MODEL_INVOCATION_LIMIT_EXCEEDED"
                    ):
                        raise ModelExecutionError(
                            "Exceeded maximum allowed model invocations for this workflow "
                            f"request ({metrics.remaining_model_budget}).",
                            code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                        )
                    raise ModelExecutionError(
                        f"ADK model returned an error event: {event.error_message}"
                    )
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [part.text for part in event.content.parts if part.text]
                    if text_parts:
                        final_text_chunks.append("\n".join(text_parts))
            if safeguard_plugin.budget_exceeded:
                raise ModelExecutionError(
                    "Exceeded maximum allowed model invocations for this workflow request "
                    f"({metrics.remaining_model_budget}).",
                    code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                )
            return final_text_chunks[-1] if final_text_chunks else ""

        with brew_span(
            span_name,
            operation_name=span_name,
            tracer_name=__name__,
            agent_name=coach_agent.name,
            agent_version=BRIEF_SPECIALIST_VERSION,
            model_name=str(resolved_model_name),
        ) as turn_tracker:
            try:
                raw_text = await asyncio.wait_for(
                    _collect_final_text(),
                    timeout=self._model_timeout_seconds,
                )
            except TimeoutError as exc:
                logger.error(
                    f"ADK {coach_agent.name} timed out after {self._model_timeout_seconds}s",
                    extra={
                        "event_type": "workflow.model.timeout",
                        "operation_name": span_name,
                        "agent_name": coach_agent.name,
                        "agent_version": BRIEF_SPECIALIST_VERSION,
                        "model_name": str(resolved_model_name),
                        "request_id": corr.request_id,
                        "trace_id": corr.trace_id,
                        "result_status": "error",
                        "error_type": type(exc).__name__,
                        "error_code": "MODEL_TIMEOUT",
                        "error_classification": "MODEL_TIMEOUT",
                    },
                )
                raise ModelTimeoutError() from exc
            except BrewDomainError:
                raise
            except Exception as exc:
                if safeguard_plugin.budget_exceeded:
                    raise ModelExecutionError(
                        "Exceeded maximum allowed model invocations for this workflow request "
                        f"({metrics.remaining_model_budget}).",
                        code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                    ) from exc
                if isinstance(exc.__cause__, BrewDomainError):
                    raise exc.__cause__ from exc
                if exc.__class__.__name__ == "LlmCallsLimitExceededError" or (
                    exc.__cause__ is not None
                    and exc.__cause__.__class__.__name__ == "LlmCallsLimitExceededError"
                ):
                    raise ModelExecutionError(
                        "Exceeded maximum allowed ADK LLM calls for this request.",
                        code="MODEL_INVOCATION_LIMIT_EXCEEDED",
                    ) from exc
                logger.error(
                    f"ADK {coach_agent.name} failed during brief execution",
                    extra={
                        "event_type": "workflow.model.error",
                        "operation_name": span_name,
                        "agent_name": coach_agent.name,
                        "agent_version": BRIEF_SPECIALIST_VERSION,
                        "model_name": str(resolved_model_name),
                        "request_id": corr.request_id,
                        "trace_id": corr.trace_id,
                        "result_status": "error",
                        "error_type": type(exc).__name__,
                        "error_code": "MODEL_EXECUTION_ERROR",
                        "error_classification": "MODEL_EXECUTION_ERROR",
                    },
                )
                raise ModelExecutionError(
                    "The coaching model encountered an unexpected execution failure."
                ) from exc
            finally:
                if metrics.total_tokens > 0 or metrics.input_tokens > 0:
                    turn_tracker.set_attributes(
                        {
                            ATTR_INPUT_TOKENS: metrics.input_tokens,
                            ATTR_OUTPUT_TOKENS: metrics.output_tokens,
                            ATTR_TOTAL_TOKENS: metrics.total_tokens,
                        }
                    )

            with brew_span(
                "brew.output.validate",
                operation_name="output.validate",
                tracer_name=__name__,
                agent_name=coach_agent.name,
                agent_version=BRIEF_SPECIALIST_VERSION,
                model_name=str(resolved_model_name),
                attributes={ATTR_VALIDATION_STAGE: "json_schema"},
            ) as val_tracker:
                cleaned_json = _strip_optional_json_fences(raw_text)
                if not cleaned_json:
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: False,
                            ATTR_VALIDATION_VIOLATION_COUNT: 1,
                        }
                    )
                    raise ModelOutputValidationError(
                        "Model returned an empty response instead of a JSON preparation brief.",
                        violations=(
                            "[EMPTY_OUTPUT] Model returned empty text; output must be valid JSON.",
                        ),
                    )

                try:
                    parsed_obj = json.loads(cleaned_json)
                except json.JSONDecodeError as exc:
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: False,
                            ATTR_VALIDATION_VIOLATION_COUNT: 1,
                        }
                    )
                    raise ModelOutputValidationError(
                        "Model output was not valid JSON.",
                        violations=(
                            f"[INVALID_JSON] Output could not be parsed as JSON ({exc.msg}).",
                        ),
                    ) from exc

                if not isinstance(parsed_obj, dict):
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: False,
                            ATTR_VALIDATION_VIOLATION_COUNT: 1,
                        }
                    )
                    raise ModelOutputValidationError(
                        "Model JSON output must be a top-level object.",
                        violations=("[INVALID_JSON_ROOT] Expected a JSON object at top level.",),
                    )

                try:
                    validated = GeneratedBriefContent.model_validate(parsed_obj)
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: True,
                            ATTR_VALIDATION_VIOLATION_COUNT: 0,
                        }
                    )
                    return validated
                except ValidationError as exc:
                    formatted = tuple(
                        f"[SCHEMA_INVALID] {'.'.join(str(p) for p in err.get('loc', ()))}: "
                        f"{err.get('msg', 'Invalid field')}"
                        for err in exc.errors()
                    )
                    val_tracker.set_attributes(
                        {
                            ATTR_VALIDATION_PASSED: False,
                            ATTR_VALIDATION_VIOLATION_COUNT: len(formatted),
                        }
                    )
                    raise ModelOutputValidationError(
                        "Model JSON output failed strict GeneratedBriefContent schema validation.",
                        violations=formatted,
                    ) from exc

    async def generate_brief(
        self,
        *,
        meeting: Meeting,
        context: BriefPreparationContext,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Synthesize an initial preparation brief via the ``brief_synthesizer`` specialist."""
        prompt = _build_generation_prompt(
            meeting=meeting,
            context=context,
            corrective_feedback=corrective_feedback,
        )
        return await self._run_coach_turn(
            operation=BriefWorkflowOperation.GENERATE,
            owner_user_id=context.owner_user_id,
            prompt=prompt,
            span_name="coach.workflow.generate_brief",
            attempt_metrics=attempt_metrics,
        )

    async def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        context: BriefPreparationContext,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Refine an existing preparation brief via the ``brief_refiner`` specialist."""
        prompt = _build_refinement_prompt(
            current_brief=current_brief,
            meeting=meeting,
            context=context,
            instructions=instructions,
            target_duration_minutes=target_duration_minutes,
            target_tone=target_tone,
            corrective_feedback=corrective_feedback,
        )
        return await self._run_coach_turn(
            operation=BriefWorkflowOperation.REVISE,
            owner_user_id=context.owner_user_id,
            prompt=prompt,
            span_name="coach.workflow.revise_brief",
            attempt_metrics=attempt_metrics,
        )
