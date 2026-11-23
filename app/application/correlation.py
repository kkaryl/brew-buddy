"""Request and trace correlation context propagated across Brew's workflow layers."""

from __future__ import annotations

import contextlib
import contextvars
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

_SAFE_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_correlation_id(candidate: str | None, *, prefix: str) -> str:
    """Return a validated correlation identifier or generate a safe prefixed UUID."""
    if candidate is not None:
        cleaned = candidate.strip()
        if cleaned and _SAFE_CORRELATION_ID_RE.match(cleaned):
            return cleaned
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True, slots=True)
class WorkflowCorrelation:
    """Unified request and distributed trace correlation IDs for a workflow run."""

    request_id: str
    trace_id: str


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
) -> WorkflowCorrelation:
    """Resolve explicit correlation IDs, inherit active context, or mint matching safe IDs."""
    existing = _WORKFLOW_CORRELATION_VAR.get()
    if request_id is None and trace_id is None and existing is not None:
        return existing

    resolved_req = (
        normalize_correlation_id(request_id, prefix="req")
        if request_id is not None
        else (existing.request_id if existing is not None else None)
    )
    resolved_trace = (
        normalize_correlation_id(trace_id, prefix="trc")
        if trace_id is not None
        else (existing.trace_id if existing is not None else None)
    )

    if resolved_req is None and resolved_trace is not None:
        resolved_req = resolved_trace
    elif resolved_trace is None and resolved_req is not None:
        resolved_trace = resolved_req
    elif resolved_req is None and resolved_trace is None:
        minted = f"req_{uuid.uuid4().hex[:16]}"
        resolved_req = minted
        resolved_trace = minted

    assert resolved_req is not None
    assert resolved_trace is not None
    return WorkflowCorrelation(request_id=resolved_req, trace_id=resolved_trace)


@contextlib.contextmanager
def bind_workflow_correlation(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[WorkflowCorrelation]:
    """Bind unified ``request_id`` and ``trace_id`` across async workflow stages."""
    correlation = resolve_or_create_correlation(request_id=request_id, trace_id=trace_id)
    token = _WORKFLOW_CORRELATION_VAR.set(correlation)
    try:
        yield correlation
    finally:
        _WORKFLOW_CORRELATION_VAR.reset(token)
