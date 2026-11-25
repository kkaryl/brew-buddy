"""Request and trace correlation context propagated across Brew's workflow layers."""

from __future__ import annotations

import contextlib
import contextvars
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from opentelemetry import trace

_SAFE_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_correlation_id(candidate: str | None, *, prefix: str) -> str:
    """Return a validated correlation identifier or generate a safe prefixed UUID."""
    if candidate is not None:
        cleaned = candidate.strip()
        if cleaned and _SAFE_CORRELATION_ID_RE.match(cleaned):
            return cleaned
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def current_otel_trace_id_hex() -> str | None:
    """Return the active 32-hex OpenTelemetry trace ID when a valid span is recording."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return format(span_context.trace_id, "032x")
    return None


def current_otel_span_id_hex() -> str | None:
    """Return the active 16-hex OpenTelemetry span ID when a valid span is recording."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return format(span_context.span_id, "016x")
    return None


@dataclass(frozen=True, slots=True)
class WorkflowCorrelation:
    """Unified request and distributed trace correlation IDs for a workflow run."""

    request_id: str
    trace_id: str
    otel_trace_id: str | None = None


_WORKFLOW_CORRELATION_VAR: contextvars.ContextVar[WorkflowCorrelation | None] = (
    contextvars.ContextVar("brew_workflow_correlation", default=None)
)


def get_workflow_correlation() -> WorkflowCorrelation | None:
    """Return the active ``WorkflowCorrelation`` bound to the current async context, if any."""
    return _WORKFLOW_CORRELATION_VAR.get()


def resolve_or_create_correlation(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    otel_trace_id: str | None = None,
) -> WorkflowCorrelation:
    """Resolve explicit correlation IDs, inherit active context/OTel span, or mint safe IDs."""
    existing = _WORKFLOW_CORRELATION_VAR.get()
    active_otel = (
        otel_trace_id
        or current_otel_trace_id_hex()
        or (existing.otel_trace_id if existing is not None else None)
    )

    if request_id is None and trace_id is None and existing is not None:
        if active_otel and existing.otel_trace_id != active_otel:
            return WorkflowCorrelation(
                request_id=existing.request_id,
                trace_id=existing.trace_id,
                otel_trace_id=active_otel,
            )
        return existing

    resolved_req = (
        normalize_correlation_id(request_id, prefix="req")
        if request_id is not None
        else (existing.request_id if existing is not None else None)
    )
    resolved_trace = (
        normalize_correlation_id(trace_id, prefix="trc")
        if trace_id is not None
        else (existing.trace_id if existing is not None else active_otel)
    )

    if resolved_req is None and resolved_trace is not None:
        resolved_req = resolved_trace
    elif resolved_trace is None and resolved_req is not None:
        resolved_trace = active_otel or resolved_req
    elif resolved_req is None and resolved_trace is None:
        minted = active_otel or f"req_{uuid.uuid4().hex[:16]}"
        resolved_req = minted
        resolved_trace = minted

    assert resolved_req is not None
    assert resolved_trace is not None
    return WorkflowCorrelation(
        request_id=resolved_req,
        trace_id=resolved_trace,
        otel_trace_id=active_otel,
    )


@contextlib.contextmanager
def bind_workflow_correlation(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    otel_trace_id: str | None = None,
) -> Iterator[WorkflowCorrelation]:
    """Bind unified ``request_id`` and ``trace_id`` across async workflow stages."""
    correlation = resolve_or_create_correlation(
        request_id=request_id,
        trace_id=trace_id,
        otel_trace_id=otel_trace_id,
    )
    token = _WORKFLOW_CORRELATION_VAR.set(correlation)
    try:
        yield correlation
    finally:
        _WORKFLOW_CORRELATION_VAR.reset(token)
