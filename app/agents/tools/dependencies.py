"""Capability-restricted dependency bundle and its default and scoped lookup."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

from app.application.coaching.capabilities import (
    PendingProposalOnlyFacade,
    ReadOnlyApprovedMemoryFacade,
    ReadOnlyContactFacade,
    ReadOnlyMeetingFacade,
    ReadOnlyPreferencesFacade,
)
from app.application.coaching.queries import ConversationCoachService
from app.config import get_settings
from app.domain.contacts.ports import ContactReaderPort
from app.domain.meetings.ports import MeetingReaderPort
from app.domain.memory.ports import (
    ApprovedMemoryReaderPort,
    MemoryProposalAgentPort,
    PendingMemoryProposalStagerPort,
    UserPreferencesReaderPort,
)
from app.domain.shared.clock import ClockPort
from app.domain.shared.ports import IdGeneratorPort

# ---------------------------------------------------------------------------
# Capability-Restricted Dependency Wiring
# ---------------------------------------------------------------------------


class CoachingToolDependencies:
    """Capability-restricted dependency bundle for ``conversation_coach`` tools.

    Physically wraps repositories in read-only / pending-only facades so the
    agent never holds unrestricted write, delete, approval, or raw DB handles.
    """

    def __init__(
        self,
        *,
        preferences_reader: UserPreferencesReaderPort,
        contact_reader: ContactReaderPort,
        meeting_reader: MeetingReaderPort,
        memory_reader: ApprovedMemoryReaderPort,
        proposal_stager: PendingMemoryProposalStagerPort,
        proposal_agent: MemoryProposalAgentPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        io_timeout_seconds: float = 10.0,
    ) -> None:
        if io_timeout_seconds <= 0:
            msg = "io_timeout_seconds must be greater than 0."
            raise ValueError(msg)

        self.io_timeout_seconds = io_timeout_seconds
        self.preferences_reader = ReadOnlyPreferencesFacade(preferences_reader)
        self.contact_reader = ReadOnlyContactFacade(contact_reader)
        self.meeting_reader = ReadOnlyMeetingFacade(meeting_reader)
        self.memory_reader = ReadOnlyApprovedMemoryFacade(memory_reader)
        self.proposal_stager = PendingProposalOnlyFacade(proposal_stager)
        self.service = ConversationCoachService(
            preferences_reader=self.preferences_reader,
            contact_reader=self.contact_reader,
            meeting_reader=self.meeting_reader,
            memory_reader=self.memory_reader,
            proposal_stager=self.proposal_stager,
            proposal_agent=proposal_agent,
            clock=clock,
            id_generator=id_generator,
        )


_scoped_dependencies: contextvars.ContextVar[CoachingToolDependencies | None] = (
    contextvars.ContextVar("brew_coaching_tool_dependencies", default=None)
)
_default_dependencies: CoachingToolDependencies | None = None


def set_default_coaching_dependencies(deps: CoachingToolDependencies | None) -> None:
    """Register process-default ``CoachingToolDependencies`` (used by FastAPI startup)."""
    global _default_dependencies
    _default_dependencies = deps


@contextlib.contextmanager
def bind_coaching_dependencies(deps: CoachingToolDependencies) -> Iterator[None]:
    """Bind ``CoachingToolDependencies`` within the active async/execution context."""
    token = _scoped_dependencies.set(deps)
    try:
        yield
    finally:
        _scoped_dependencies.reset(token)


def get_coaching_dependencies() -> CoachingToolDependencies:
    """Resolve active ``CoachingToolDependencies`` without exposing raw repositories."""
    scoped = _scoped_dependencies.get()
    if scoped is not None:
        return scoped
    if _default_dependencies is not None:
        return _default_dependencies

    # Lazy fallback for standalone CLI invocations (e.g., `agents-cli run`).
    from app.composition.builders import build_service_container

    settings = get_settings()
    container = build_service_container(settings)
    deps = CoachingToolDependencies(
        preferences_reader=container.preferences_repo,
        contact_reader=container.contact_repo,
        meeting_reader=container.meeting_repo,
        memory_reader=container.memory_repo,
        proposal_stager=container.proposal_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
        io_timeout_seconds=settings.firestore_timeout_seconds,
    )
    set_default_coaching_dependencies(deps)
    return deps
