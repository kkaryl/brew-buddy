"""Span scope and failure telemetry shared by the conversation_coach tools."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.agents.tools.contracts import ToolErrorDetail
from app.application.shared.telemetry import (
    ATTR_DURATION_MS,
    ATTR_OPERATION_NAME,
    ATTR_RESULT_STATUS,
    ATTR_TOOL_NAME,
    SpanOutcomeTracker,
    mark_span_error,
    set_safe_span_attributes,
    stamp_correlation_attributes,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)


@contextlib.contextmanager
def tool_telemetry_scope(tool_name: str) -> Iterator[SpanOutcomeTracker]:
    """Enrich ADK's ``execute_tool`` span when active, or open a standalone tool span."""
    current = trace.get_current_span()
    current_name = getattr(current, "name", "")
    is_adk_tool_span = bool(current.is_recording() and str(current_name).startswith("execute_tool"))
    started = time.perf_counter()

    if is_adk_tool_span:
        stamp_correlation_attributes(current)
        set_safe_span_attributes(
            current,
            {
                ATTR_OPERATION_NAME: f"tool.{tool_name}",
                ATTR_TOOL_NAME: tool_name,
            },
        )
        tracker = SpanOutcomeTracker(span=current)
        try:
            yield tracker
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            set_safe_span_attributes(
                current,
                {
                    ATTR_DURATION_MS: elapsed_ms,
                    ATTR_RESULT_STATUS: tracker.status,
                },
            )
        return

    with _tracer.start_as_current_span(f"coach.tool.{tool_name}") as span:
        stamp_correlation_attributes(span)
        set_safe_span_attributes(
            span,
            {
                ATTR_OPERATION_NAME: f"tool.{tool_name}",
                ATTR_TOOL_NAME: tool_name,
            },
        )
        tracker = SpanOutcomeTracker(span=span)
        try:
            yield tracker
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            set_safe_span_attributes(
                span,
                {
                    ATTR_DURATION_MS: elapsed_ms,
                    ATTR_RESULT_STATUS: tracker.status,
                },
            )
            if tracker.status != "error" and span.is_recording():
                span.set_status(Status(StatusCode.OK))


def record_tool_failure_telemetry(
    tracker: SpanOutcomeTracker,
    *,
    tool_name: str,
    err: ToolErrorDetail,
    exc: Exception,
) -> None:
    tracker.status = "error"
    tracker.error_classification = err.code
    tracker.error_code = err.code
    mark_span_error(
        tracker.span,
        classification=err.code,
        error_code=err.code,
        error_type=type(exc).__name__,
        description=err.code,
    )
    logger.warning(
        f"Coaching tool {tool_name} failed with {err.code}",
        extra={
            "event_type": "tool.execution.failed",
            "operation_name": f"tool.{tool_name}",
            "tool_name": tool_name,
            "result_status": "error",
            "error_type": type(exc).__name__,
            "error_code": err.code,
            "error_classification": err.code,
        },
    )
