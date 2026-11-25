"""Per-request run counters and failure diagnostics for the brief workflow."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.application.shared.telemetry import classify_telemetry_error
from app.domain.briefs.diagnostics import BriefWorkflowDiagnostics
from app.domain.briefs.types import BriefWorkflowOperation, BriefWorkflowTerminalState
from app.domain.shared.errors import (
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

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRunCounters:
    """Mutable per-request counters preserved across both happy and failure paths."""

    attempt_count: int = 0
    regeneration_count: int = 0
    model_invocations: int = 0
    tool_invocations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    memories_retrieved: int = 0


def attach_failure_diagnostics(
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


def classify_domain_failure_state(
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
