"""Execution diagnostics for one brief workflow run, and how they travel on an error."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.domain.briefs.types import BriefWorkflowOperation, BriefWorkflowTerminalState
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.errors import BrewDomainError
from app.domain.shared.types import EntityId, ShortTagText, VersionNumber


class BriefWorkflowDiagnostics(ImmutableDomainModel):
    """Structured execution diagnostics and safeguard telemetry for a brief workflow run."""

    request_id: EntityId
    trace_id: EntityId
    operation: BriefWorkflowOperation
    terminal_state: BriefWorkflowTerminalState
    attempt_count: Annotated[int, Field(ge=0, le=5)] = 1
    regeneration_count: Annotated[int, Field(ge=0, le=1)] = 0
    model_invocations: Annotated[int, Field(ge=0, le=50)] = 0
    tool_invocations: Annotated[int, Field(ge=0, le=100)] = 0
    replayed: bool = False
    quality_passed: bool = True
    degraded_sources: list[ShortTagText] = Field(default_factory=list, max_length=20)
    previous_version: VersionNumber | None = None


def brief_workflow_diagnostics(error: BrewDomainError) -> BriefWorkflowDiagnostics | None:
    """Return the brief workflow diagnostics attached to ``error``, if any.

    The brief workflow attaches its diagnostics to whatever domain error ends a run. The
    error base class lives in the shared context and knows nothing about briefs, so this
    is the typed way to read them back.
    """
    attached = error.workflow_diagnostics
    return attached if isinstance(attached, BriefWorkflowDiagnostics) else None
