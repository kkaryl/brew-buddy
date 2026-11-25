"""ServiceContainer: the application's dependency wiring, plus its local in-memory variant."""

from __future__ import annotations

from app.domain.briefs.ports import (
    BriefCoachAgentPort,
    BriefRepository,
    WorkflowIdempotencyRepository,
)
from app.domain.contacts.ports import ContactRepository
from app.domain.identity.ports import AuthenticatorPort
from app.domain.meetings.ports import MeetingRepository
from app.domain.memory.ports import (
    MemoryExtractionJobRepository,
    MemoryProposalAgentPort,
    MemoryProposalRepository,
    MemoryRepository,
    UserPreferencesRepository,
)
from app.domain.shared.clock import ClockPort
from app.domain.shared.ports import BackgroundJobRunnerPort, IdGeneratorPort
from app.infrastructure.background_jobs import InProcessBackgroundJobRunner
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.ids import UuidIdGenerator
from app.infrastructure.inmemory.briefs import InMemoryBriefRepository
from app.infrastructure.inmemory.contacts import InMemoryContactRepository
from app.infrastructure.inmemory.idempotency import InMemoryWorkflowIdempotencyRepository
from app.infrastructure.inmemory.meetings import InMemoryMeetingRepository
from app.infrastructure.inmemory.memories import InMemoryMemoryRepository
from app.infrastructure.inmemory.memory_jobs import InMemoryMemoryExtractionJobRepository
from app.infrastructure.inmemory.memory_proposals import InMemoryMemoryProposalRepository
from app.infrastructure.inmemory.preferences import InMemoryUserPreferencesRepository
from app.infrastructure.stubs.authenticator import FakeAuthenticator
from app.infrastructure.stubs.brief_coach import FakeBriefCoachAgent
from app.infrastructure.stubs.memory_extractor import FakeMemoryProposalAgent


class ServiceContainer:
    """Protocol-typed dependency container supporting both local fakes and Firestore backends."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        authenticator: AuthenticatorPort,
        preferences_repo: UserPreferencesRepository,
        contact_repo: ContactRepository,
        meeting_repo: MeetingRepository,
        brief_repo: BriefRepository,
        proposal_repo: MemoryProposalRepository,
        memory_repo: MemoryRepository,
        brief_agent: BriefCoachAgentPort,
        proposal_agent: MemoryProposalAgentPort,
        idempotency_repo: WorkflowIdempotencyRepository | None = None,
        job_repo: MemoryExtractionJobRepository | None = None,
        job_runner: BackgroundJobRunnerPort | None = None,
    ) -> None:
        self.clock = clock
        self.id_generator = id_generator
        self.authenticator = authenticator
        self.preferences_repo = preferences_repo
        self.contact_repo = contact_repo
        self.meeting_repo = meeting_repo
        self.brief_repo = brief_repo
        self.proposal_repo = proposal_repo
        self.memory_repo = memory_repo
        self.brief_agent = brief_agent
        self.proposal_agent = proposal_agent
        self.idempotency_repo: WorkflowIdempotencyRepository = (
            idempotency_repo
            if idempotency_repo is not None
            else InMemoryWorkflowIdempotencyRepository()
        )
        self.job_repo: MemoryExtractionJobRepository = (
            job_repo if job_repo is not None else InMemoryMemoryExtractionJobRepository()
        )
        self.job_runner: BackgroundJobRunnerPort = (
            job_runner if job_runner is not None else InProcessBackgroundJobRunner()
        )


class FakeServiceContainer(ServiceContainer):
    """Self-contained wiring container holding injected local fake repositories and agents."""

    def __init__(
        self,
        *,
        clock: ClockPort | None = None,
        authenticator: AuthenticatorPort | None = None,
        brief_agent: BriefCoachAgentPort | None = None,
    ) -> None:
        super().__init__(
            clock=clock if clock is not None else SystemUtcClock(),
            id_generator=UuidIdGenerator(),
            authenticator=(authenticator if authenticator is not None else FakeAuthenticator()),
            preferences_repo=InMemoryUserPreferencesRepository(),
            contact_repo=InMemoryContactRepository(),
            meeting_repo=InMemoryMeetingRepository(),
            brief_repo=InMemoryBriefRepository(),
            proposal_repo=InMemoryMemoryProposalRepository(),
            memory_repo=InMemoryMemoryRepository(),
            brief_agent=brief_agent if brief_agent is not None else FakeBriefCoachAgent(),
            proposal_agent=FakeMemoryProposalAgent(),
            idempotency_repo=InMemoryWorkflowIdempotencyRepository(),
        )
