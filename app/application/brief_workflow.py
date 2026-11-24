"""End-to-end 9-step Meeting Preparation & Refinement Workflow with orchestration safeguards."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.correlation import bind_workflow_correlation
from app.application.memory_persistence_service import (
    MemoryPersistenceService,
    translate_pydantic_error,
)
from app.application.memory_retrieval_service import (
    _estimate_contact_and_prefs_chars,
    _estimate_meeting_summary_chars,
    _estimate_memory_item_chars,
    _meeting_relevance_key,
    _memory_relevance_key,
    _tokenize_keywords,
)
from app.application.telemetry import (
    ATTR_INPUT_TOKENS,
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    ATTR_OUTPUT_TOKENS,
    ATTR_REGENERATION_ATTEMPT,
    ATTR_REGENERATION_COUNT,
    ATTR_TOTAL_TOKENS,
    ATTR_VALIDATION_PASSED,
    ATTR_VALIDATION_STAGE,
    ATTR_VALIDATION_VIOLATION_COUNT,
    brew_span,
    classify_telemetry_error,
)
from app.application.untrusted_data import sanitize_untrusted_text
from app.domain.brief_quality import (
    BriefQualityPolicy,
    RefinementResolution,
    evaluate_brief_quality,
    parse_refinement_overrides,
)
from app.domain.errors import (
    AuthorizationError,
    BrewDomainError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
    ModelExecutionError,
    ModelOutputValidationError,
    ModelTimeoutError,
    PersistenceOperationError,
    VersionConflictError,
)
from app.domain.health import ClockPort
from app.domain.models import (
    AuthenticatedPrincipal,
    BriefPreparationContext,
    BriefWorkflowDiagnostics,
    BriefWorkflowResult,
    Contact,
    ContextBudget,
    Meeting,
    Memory,
    PreparationBrief,
    ProvenanceMemoryItem,
    RecentMeetingSummary,
    WorkflowIdempotencyRecord,
)
from app.domain.ports import (
    BriefAttemptMetrics,
    BriefCoachAgentPort,
    BriefRepository,
    ContactRepository,
    GeneratedBriefContent,
    IdGeneratorPort,
    MeetingRepository,
    MemoryRepository,
    UserPreferencesRepository,
    WorkflowIdempotencyRepository,
)
from app.domain.types import (
    BriefWorkflowOperation,
    BriefWorkflowTerminalState,
    EntityId,
    MeetingDurationMinutes,
    MeetingNotesText,
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryBodyText,
    MemoryScope,
    ObjectiveText,
    ShortTagText,
    UtcDatetime,
    VersionNumber,
)

logger = logging.getLogger(__name__)

MAX_ALLOWED_REGENERATIONS = 1

_T = TypeVar("_T")


class BriefWorkflowSafeguardConfig(BaseModel):
    """Hard orchestration safeguard bounds enforced across every workflow execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_invocations: Annotated[int, Field(ge=1, le=12)] = 6
    max_corrective_regenerations: Annotated[int, Field(ge=0, le=MAX_ALLOWED_REGENERATIONS)] = 1
    max_tool_retries: Annotated[int, Field(ge=0, le=3)] = 1
    context_io_timeout_seconds: Annotated[float, Field(gt=0.0, le=60.0)] = 5.0


class _GenerateWorkflowInput(BaseModel):
    """Strict Step-1 input contract for initial brief generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contact_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone
    meeting_objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    meeting_notes: MeetingNotesText | None = None
    preferred_question_count: Annotated[int, Field(ge=1, le=15)] | None = None
    communication_style_notes: MemoryBodyText | None = None
    focus_areas: list[ShortTagText] | None = Field(default=None, max_length=10)


class _ReviseWorkflowInput(BaseModel):
    """Strict Step-1 input contract for brief refinement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    brief_id: EntityId
    instructions: MemoryBodyText
    expected_version: VersionNumber
    duration_minutes: MeetingDurationMinutes | None = None
    tone: MeetingTone | None = None


@dataclass
class _WorkflowRunCounters:
    """Mutable per-request counters preserved across both happy and failure paths."""

    attempt_count: int = 0
    regeneration_count: int = 0
    model_invocations: int = 0
    tool_invocations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    memories_retrieved: int = 0


def _compute_payload_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sanitize_contact_for_context(contact: Contact) -> Contact:
    if not contact.context_notes:
        return contact
    cleaned = sanitize_untrusted_text(contact.context_notes, max_chars=2000).text
    if len(cleaned) < 3 or cleaned == contact.context_notes:
        return contact
    return contact.model_copy(update={"context_notes": cleaned})


def _sanitize_memory_for_context(memory: Memory) -> Memory:
    cleaned_text = sanitize_untrusted_text(memory.text, max_chars=1000).text
    safe_text = cleaned_text if len(cleaned_text) >= 3 else memory.text
    safe_source = memory.source
    if memory.source.excerpt:
        cleaned_excerpt = sanitize_untrusted_text(memory.source.excerpt, max_chars=500).text
        if cleaned_excerpt:
            safe_source = memory.source.model_copy(update={"excerpt": cleaned_excerpt})
    if safe_text == memory.text and safe_source == memory.source:
        return memory
    return memory.model_copy(update={"text": safe_text, "source": safe_source})


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
        self._idempotency_locks: dict[str, asyncio.Lock] = {}

    def _lock_for_idempotency_key(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> asyncio.Lock:
        composite = f"{owner_user_id}:{operation.value}:{idempotency_key}"
        lock = self._idempotency_locks.get(composite)
        if lock is None:
            lock = asyncio.Lock()
            self._idempotency_locks[composite] = lock
        return lock

    async def _call_optional_context_source(
        self,
        source_label: str,
        operation: Callable[[], Awaitable[_T]],
        *,
        fallback: _T,
        degraded_sources: list[str],
    ) -> _T:
        """Execute an optional context read with bounded retries and graceful degradation."""
        max_attempts = 1 + self._safeguards.max_tool_retries
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    operation(),
                    timeout=self._safeguards.context_io_timeout_seconds,
                )
            except (TimeoutError, PersistenceOperationError):
                if attempt >= max_attempts:
                    if source_label not in degraded_sources:
                        degraded_sources.append(source_label)
                    logger.warning(
                        f"Optional context source '{source_label}' unavailable after "
                        f"{attempt} attempt(s); continuing with grounded baseline context",
                        extra={"event_type": "workflow.context.degraded"},
                    )
                    return fallback
        return fallback

    async def _resolve_owned_contact(
        self,
        *,
        owner_user_id: str,
        contact_id: str,
    ) -> Contact:
        contact = await self._contact_repo.get_for_owner(owner_user_id, contact_id)
        if contact is None:
            if await self._contact_repo.exists_for_any_owner(contact_id):
                raise AuthorizationError()
            raise EntityNotFoundError(entity_name="Contact", entity_id=contact_id)
        return contact

    async def _assemble_resilient_context(
        self,
        *,
        principal: AuthenticatedPrincipal,
        contact: Contact,
        purpose: MeetingPurpose,
        objective: str,
        degraded_sources: list[str],
        exclude_meeting_id: str | None = None,
    ) -> BriefPreparationContext:
        """Step 3: Retrieve preferences, history, and approved memories with bounded budget."""
        with brew_span(
            "brew.context.retrieve",
            operation_name="context.retrieve",
            tracer_name=__name__,
        ) as ctx_tracker:
            uid = principal.user_id
            safe_contact = _sanitize_contact_for_context(contact)

            empty_pref_memories: list[Memory] = []
            empty_meetings: list[Meeting] = []
            empty_contact_memories: list[Memory] = []
            (
                user_preferences,
                raw_pref_memories,
                raw_meetings,
                raw_contact_memories,
            ) = await asyncio.gather(
                self._call_optional_context_source(
                    "user_preferences",
                    lambda: self._preferences_repo.get_by_owner(uid),
                    fallback=None,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "preference_memories",
                    lambda: self._memory_repo.list_by_owner(
                        uid,
                        scope=MemoryScope.USER_PREFERENCE,
                        include_revoked=False,
                    ),
                    fallback=empty_pref_memories,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "meeting_history",
                    lambda: self._meeting_repo.list_by_owner(uid, contact_id=contact.id),
                    fallback=empty_meetings,
                    degraded_sources=degraded_sources,
                ),
                self._call_optional_context_source(
                    "contact_memories",
                    lambda: self._memory_repo.list_by_owner(
                        uid,
                        scope=MemoryScope.CONTACT,
                        contact_id=contact.id,
                        include_revoked=False,
                    ),
                    fallback=empty_contact_memories,
                    degraded_sources=degraded_sources,
                ),
            )

            if user_preferences is not None and user_preferences.owner_user_id != uid:
                user_preferences = None

            objective_tokens = _tokenize_keywords(objective)

            eligible_meetings = [
                mtg
                for mtg in raw_meetings
                if mtg.owner_user_id == uid
                and mtg.contact_id == contact.id
                and mtg.status is not MeetingStatus.CANCELLED
                and (exclude_meeting_id is None or mtg.id != exclude_meeting_id)
            ]
            ranked_meetings = sorted(
                eligible_meetings,
                key=lambda mtg: _meeting_relevance_key(
                    mtg,
                    target_purpose=purpose,
                    objective_tokens=objective_tokens,
                ),
                reverse=True,
            )

            eligible_pref_memories = [
                _sanitize_memory_for_context(mem)
                for mem in raw_pref_memories
                if mem.owner_user_id == uid
                and mem.is_active
                and mem.scope is MemoryScope.USER_PREFERENCE
            ]
            ranked_pref_memories = sorted(
                eligible_pref_memories,
                key=lambda mem: _memory_relevance_key(mem, objective_tokens=objective_tokens),
                reverse=True,
            )

            eligible_contact_memories = [
                _sanitize_memory_for_context(mem)
                for mem in raw_contact_memories
                if mem.owner_user_id == uid
                and mem.is_active
                and mem.scope is MemoryScope.CONTACT
                and mem.contact_id == contact.id
            ]
            ranked_contact_memories = sorted(
                eligible_contact_memories,
                key=lambda mem: _memory_relevance_key(mem, objective_tokens=objective_tokens),
                reverse=True,
            )

            budget = self._context_budget
            running_chars = min(
                _estimate_contact_and_prefs_chars(safe_contact, user_preferences),
                budget.max_total_chars,
            )
            was_truncated = False

            selected_pref_items: list[ProvenanceMemoryItem] = []
            for mem in ranked_pref_memories:
                if len(selected_pref_items) >= budget.max_preference_memories:
                    was_truncated = True
                    break
                item = ProvenanceMemoryItem.from_memory(mem)
                cost = _estimate_memory_item_chars(item)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_pref_items.append(item)
                running_chars += cost

            selected_contact_items: list[ProvenanceMemoryItem] = []
            for mem in ranked_contact_memories:
                if len(selected_contact_items) >= budget.max_contact_memories:
                    was_truncated = True
                    break
                item = ProvenanceMemoryItem.from_memory(mem)
                cost = _estimate_memory_item_chars(item)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_contact_items.append(item)
                running_chars += cost

            selected_meetings: list[RecentMeetingSummary] = []
            for mtg in ranked_meetings:
                if len(selected_meetings) >= budget.max_recent_meetings:
                    was_truncated = True
                    break
                raw_excerpt = mtg.notes[:280] if mtg.notes else None
                safe_excerpt: str | None = None
                if raw_excerpt:
                    cleaned_notes = sanitize_untrusted_text(raw_excerpt, max_chars=280).text
                    safe_excerpt = cleaned_notes or None
                summary = RecentMeetingSummary(
                    meeting_id=mtg.id,
                    purpose=mtg.purpose,
                    tone=mtg.tone,
                    objective=mtg.objective,
                    duration_minutes=mtg.duration_minutes,
                    scheduled_at=mtg.scheduled_at,
                    status=mtg.status,
                    notes_excerpt=safe_excerpt,
                    updated_at=mtg.updated_at,
                )
                cost = _estimate_meeting_summary_chars(summary)
                if running_chars + cost > budget.max_total_chars:
                    was_truncated = True
                    continue
                selected_meetings.append(summary)
                running_chars += cost

            retrieved_memories = len(selected_pref_items) + len(selected_contact_items)
            ctx_tracker.set_attributes(
                {
                    ATTR_MEMORY_RETRIEVED_COUNT: retrieved_memories,
                    "brew.context.preference_memories_count": len(selected_pref_items),
                    "brew.context.contact_memories_count": len(selected_contact_items),
                    "brew.context.recent_meetings_count": len(selected_meetings),
                    "brew.context.truncated": was_truncated,
                    "brew.context.degraded_sources_count": len(degraded_sources),
                }
            )
            if degraded_sources:
                ctx_tracker.mark_degraded("CONTEXT_SOURCE_DEGRADED")

            logger.info(
                "Retrieved pre-brief context and memories",
                extra={
                    "event_type": "workflow.context.retrieved",
                    "operation_name": "context.retrieve",
                    "memory_retrieved_count": retrieved_memories,
                    "result_status": ctx_tracker.status,
                },
            )
            return BriefPreparationContext(
                owner_user_id=uid,
                contact=safe_contact,
                user_preferences=user_preferences,
                preference_memories=selected_pref_items,
                contact_memories=selected_contact_items,
                recent_meetings=selected_meetings,
                budget=budget,
                total_context_chars=running_chars,
                was_truncated=was_truncated,
            )

    def _attach_failure_diagnostics(
        self,
        exc: BrewDomainError,
        *,
        request_id: str,
        trace_id: str,
        operation: BriefWorkflowOperation,
        terminal_state: BriefWorkflowTerminalState,
        attempt_count: int,
        regeneration_count: int,
        model_invocations: int,
        tool_invocations: int,
        degraded_sources: Sequence[str],
        previous_version: int | None = None,
    ) -> BrewDomainError:
        diagnostics = BriefWorkflowDiagnostics(
            request_id=request_id,
            trace_id=trace_id,
            operation=operation,
            terminal_state=terminal_state,
            attempt_count=attempt_count,
            regeneration_count=regeneration_count,
            model_invocations=model_invocations,
            tool_invocations=tool_invocations,
            replayed=False,
            quality_passed=False,
            degraded_sources=list(degraded_sources),
            previous_version=previous_version,
        )
        exc.workflow_diagnostics = diagnostics
        logger.warning(
            f"Brief workflow terminated with state={terminal_state.value} ({exc.code})",
            extra={
                "event_type": "workflow.brief.failed",
                "operation_name": f"workflow.{operation.value}_brief",
                "request_id": request_id,
                "trace_id": trace_id,
                "result_status": "error",
                "error_type": type(exc).__name__,
                "error_code": exc.code,
                "error_classification": classify_telemetry_error(exc),
                "attempt_count": attempt_count,
                "regeneration_count": regeneration_count,
            },
        )
        return exc

    def _classify_domain_failure_state(
        self,
        exc: BrewDomainError,
    ) -> BriefWorkflowTerminalState:
        if isinstance(exc, AuthorizationError):
            return BriefWorkflowTerminalState.FAILED_FORBIDDEN
        if isinstance(exc, EntityNotFoundError):
            return BriefWorkflowTerminalState.FAILED_NOT_FOUND
        if isinstance(exc, (VersionConflictError, ConflictError)):
            return BriefWorkflowTerminalState.FAILED_CONFLICT
        if isinstance(exc, ModelTimeoutError):
            return BriefWorkflowTerminalState.FAILED_MODEL_TIMEOUT
        if isinstance(exc, ModelExecutionError):
            return BriefWorkflowTerminalState.FAILED_MODEL_ERROR
        if isinstance(exc, ModelOutputValidationError):
            return BriefWorkflowTerminalState.FAILED_OUTPUT_VALIDATION
        if isinstance(exc, PersistenceOperationError):
            return BriefWorkflowTerminalState.FAILED_PERSISTENCE
        if isinstance(exc, DomainValidationError):
            return BriefWorkflowTerminalState.FAILED_INPUT_VALIDATION
        return BriefWorkflowTerminalState.FAILED_MODEL_ERROR

    async def _try_replay_idempotent_result(
        self,
        *,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
        payload_fingerprint: str,
        request_id: str,
        trace_id: str,
    ) -> BriefWorkflowResult | None:
        if self._idempotency_repo is None:
            return None
        existing = await self._idempotency_repo.get(owner_user_id, operation, idempotency_key)
        if existing is None:
            return None
        if existing.payload_fingerprint != payload_fingerprint:
            raise ConflictError(
                f"Idempotency key '{idempotency_key}' was already used with a different "
                "meeting preparation request payload.",
                code="IDEMPOTENCY_KEY_CONFLICT",
            )

        replay_brief = await self._brief_repo.get_revision(
            owner_user_id,
            existing.brief_id,
            existing.brief_version,
        )
        if replay_brief is None:
            replay_brief = await self._brief_repo.get_for_owner(owner_user_id, existing.brief_id)
        replay_meeting = await self._meeting_repo.get_for_owner(owner_user_id, existing.meeting_id)
        if replay_brief is None or replay_meeting is None:
            return None

        previous_version = replay_brief.version - 1 if replay_brief.version > 1 else None
        diagnostics = BriefWorkflowDiagnostics(
            request_id=request_id,
            trace_id=trace_id,
            operation=operation,
            terminal_state=BriefWorkflowTerminalState.COMPLETED_IDEMPOTENT_REPLAY,
            attempt_count=0,
            regeneration_count=0,
            model_invocations=0,
            tool_invocations=0,
            replayed=True,
            quality_passed=True,
            degraded_sources=[],
            previous_version=previous_version,
        )
        logger.info(
            "Replayed deduplicated preparation brief workflow result",
            extra={
                "event_type": "workflow.brief.replayed",
                "request_id": request_id,
                "trace_id": trace_id,
            },
        )
        return BriefWorkflowResult(
            brief=replay_brief,
            meeting=replay_meeting,
            diagnostics=diagnostics,
        )

    async def _synthesize_and_validate_with_single_repair(
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
        counters: _WorkflowRunCounters,
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
                    agent_name="conversation_coach",
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
                    agent_name="conversation_coach",
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
                        "agent_name": "conversation_coach",
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
                agent_name="conversation_coach",
                agent_version="1.0.0",
            ) as wf_tracker,
        ):
            counters = _WorkflowRunCounters()
            degraded_sources: list[str] = []

            try:
                # Step 1: Receive and validate meeting context
                try:
                    validated_in = _GenerateWorkflowInput(
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
                fingerprint = _compute_payload_fingerprint(
                    {
                        "owner_user_id": principal.user_id,
                        "operation": BriefWorkflowOperation.GENERATE.value,
                        **validated_in.model_dump(mode="json"),
                    }
                )

                if dedup_key:
                    lock = self._lock_for_idempotency_key(
                        principal.user_id,
                        BriefWorkflowOperation.GENERATE,
                        dedup_key,
                    )
                    await lock.acquire()
                else:
                    lock = None

                try:
                    if dedup_key:
                        replayed = await self._try_replay_idempotent_result(
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
                    contact = await self._resolve_owned_contact(
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
                    context = await self._assemble_resilient_context(
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
                    validated_brief = await self._synthesize_and_validate_with_single_repair(
                        operation=BriefWorkflowOperation.GENERATE,
                        invoke_attempt=lambda feedback, metrics: self._brief_agent.generate_brief(
                            meeting=meeting,
                            context=context,
                            corrective_feedback=feedback,
                            attempt_metrics=metrics,
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
                            "agent_name": "conversation_coach",
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
                raise self._attach_failure_diagnostics(
                    exc,
                    request_id=corr.request_id,
                    trace_id=corr.trace_id,
                    operation=BriefWorkflowOperation.GENERATE,
                    terminal_state=self._classify_domain_failure_state(exc),
                    attempt_count=counters.attempt_count,
                    regeneration_count=counters.regeneration_count,
                    model_invocations=counters.model_invocations,
                    tool_invocations=counters.tool_invocations,
                    degraded_sources=degraded_sources,
                ) from exc

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
                agent_name="conversation_coach",
                agent_version="1.0.0",
            ) as wf_tracker,
        ):
            counters = _WorkflowRunCounters()
            degraded_sources: list[str] = []
            previous_version: int | None = None

            try:
                # Step 1: Receive and validate refinement request
                try:
                    validated_in = _ReviseWorkflowInput(
                        brief_id=brief_id,
                        instructions=instructions,
                        expected_version=expected_version,
                        duration_minutes=duration_minutes,
                        tone=tone,
                    )
                except ValidationError as exc:
                    raise translate_pydantic_error(exc) from exc

                dedup_key = idempotency_key.strip() if idempotency_key else None
                fingerprint = _compute_payload_fingerprint(
                    {
                        "owner_user_id": principal.user_id,
                        "operation": BriefWorkflowOperation.REVISE.value,
                        **validated_in.model_dump(mode="json"),
                    }
                )

                if dedup_key:
                    lock = self._lock_for_idempotency_key(
                        principal.user_id,
                        BriefWorkflowOperation.REVISE,
                        dedup_key,
                    )
                    await lock.acquire()
                else:
                    lock = None

                try:
                    if dedup_key:
                        replayed = await self._try_replay_idempotent_result(
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

                    contact = await self._resolve_owned_contact(
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
                    context = await self._assemble_resilient_context(
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
                    revised_brief = await self._synthesize_and_validate_with_single_repair(
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
                            "agent_name": "conversation_coach",
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
                raise self._attach_failure_diagnostics(
                    exc,
                    request_id=corr.request_id,
                    trace_id=corr.trace_id,
                    operation=BriefWorkflowOperation.REVISE,
                    terminal_state=self._classify_domain_failure_state(exc),
                    attempt_count=counters.attempt_count,
                    regeneration_count=counters.regeneration_count,
                    model_invocations=counters.model_invocations,
                    tool_invocations=counters.tool_invocations,
                    degraded_sources=degraded_sources,
                    previous_version=previous_version,
                ) from exc
