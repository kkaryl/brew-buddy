"""Assemble pre-brief context in tests through the same assembler the brief workflow uses."""

from __future__ import annotations

from app.application.briefs.context_assembly import ResilientBriefContextAssembler
from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.memory.retrieval import MemoryRetrievalService
from app.domain.briefs.context import BriefPreparationContext, ContextBudget
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.types import MeetingPurpose


async def assemble_brief_context(
    retrieval: MemoryRetrievalService,
    *,
    principal: AuthenticatedPrincipal,
    contact_id: str,
    purpose: MeetingPurpose,
    objective: str,
    budget: ContextBudget | None = None,
) -> BriefPreparationContext:
    """Resolve the owned contact and assemble its context, as brief generation does.

    The assembler replaces an unavailable source with an empty fallback. A test that
    inspects the context must not pass on such a fallback, so any degraded source fails
    here.
    """
    assembler = ResilientBriefContextAssembler(
        preferences_repo=retrieval.preferences_repo,
        contact_repo=retrieval.contact_repo,
        meeting_repo=retrieval.meeting_repo,
        memory_repo=retrieval.memory_repo,
        safeguards=BriefWorkflowSafeguardConfig(),
        context_budget=budget or retrieval.default_budget,
    )
    contact = await assembler.resolve_owned_contact(
        owner_user_id=principal.user_id,
        contact_id=contact_id,
    )
    degraded_sources: list[str] = []
    context = await assembler.assemble_resilient_context(
        principal=principal,
        contact=contact,
        purpose=purpose,
        objective=objective,
        degraded_sources=degraded_sources,
    )
    assert degraded_sources == [], f"context sources degraded: {degraded_sources}"
    return context
