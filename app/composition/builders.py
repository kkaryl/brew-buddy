"""Runtime dependency container builders for in-memory fake and Firestore backends."""

from __future__ import annotations

from google.cloud import firestore

from app.agents.brief_specialists import AdkConversationCoachBriefAdapter
from app.agents.memory_extractor import AdkMemoryProposalAdapter
from app.agents.tools.dependencies import CoachingToolDependencies
from app.composition.container import FakeServiceContainer, ServiceContainer
from app.config import AppSettings
from app.domain.briefs.ports import BriefCoachAgentPort
from app.domain.identity.ports import AuthenticatorPort
from app.domain.memory.ports import MemoryProposalAgentPort
from app.domain.shared.clock import ClockPort
from app.domain.shared.ports import IdGeneratorPort
from app.infrastructure.background_jobs import InProcessBackgroundJobRunner
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.firestore.briefs import FirestoreBriefRepository
from app.infrastructure.firestore.contacts import FirestoreContactRepository
from app.infrastructure.firestore.idempotency import FirestoreWorkflowIdempotencyRepository
from app.infrastructure.firestore.meetings import FirestoreMeetingRepository
from app.infrastructure.firestore.memories import FirestoreMemoryRepository
from app.infrastructure.firestore.memory_jobs import FirestoreMemoryExtractionJobRepository
from app.infrastructure.firestore.memory_proposals import FirestoreMemoryProposalRepository
from app.infrastructure.firestore.preferences import FirestoreUserPreferencesRepository
from app.infrastructure.identity.runtime import build_runtime_authenticator
from app.infrastructure.ids import UuidIdGenerator
from app.infrastructure.sessions import create_firestore_async_client
from app.infrastructure.stubs.brief_coach import FakeBriefCoachAgent
from app.infrastructure.stubs.memory_extractor import FakeMemoryProposalAgent


def _should_use_adk_brief_coach(settings: AppSettings) -> bool:
    if settings.brief_coach_backend == "adk":
        return True
    if settings.brief_coach_backend == "fake":
        return False
    return settings.environment != "test"


def _should_use_adk_memory_extractor(settings: AppSettings) -> bool:
    if settings.memory_extractor_backend == "adk":
        return True
    if settings.memory_extractor_backend == "fake":
        return False
    return settings.environment != "test"


def build_firestore_service_container(
    settings: AppSettings,
    *,
    client: firestore.AsyncClient | None = None,
    clock: ClockPort | None = None,
    id_generator: IdGeneratorPort | None = None,
    authenticator: AuthenticatorPort | None = None,
    brief_agent: BriefCoachAgentPort | None = None,
    proposal_agent: MemoryProposalAgentPort | None = None,
) -> ServiceContainer:
    """Wire all domain repositories against Google Cloud Firestore ``AsyncClient``."""
    resolved_client = client or create_firestore_async_client(
        project=settings.google_cloud_project,
        database=settings.firestore_database,
    )
    timeout = settings.firestore_timeout_seconds
    resolved_clock = clock or SystemUtcClock()
    resolved_ids = id_generator or UuidIdGenerator()
    resolved_proposal_agent: MemoryProposalAgentPort
    if proposal_agent is not None:
        resolved_proposal_agent = proposal_agent
    elif _should_use_adk_memory_extractor(settings):
        resolved_proposal_agent = AdkMemoryProposalAdapter(settings=settings)
    else:
        resolved_proposal_agent = FakeMemoryProposalAgent()

    preferences_repo = FirestoreUserPreferencesRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    contact_repo = FirestoreContactRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    meeting_repo = FirestoreMeetingRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    brief_repo = FirestoreBriefRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    proposal_repo = FirestoreMemoryProposalRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    memory_repo = FirestoreMemoryRepository(
        resolved_client,
        timeout_seconds=timeout,
    )
    idempotency_repo = FirestoreWorkflowIdempotencyRepository(
        resolved_client,
        timeout_seconds=timeout,
    )

    resolved_brief_agent: BriefCoachAgentPort
    if brief_agent is not None:
        resolved_brief_agent = brief_agent
    elif _should_use_adk_brief_coach(settings):
        resolved_brief_agent = AdkConversationCoachBriefAdapter(
            tool_dependencies=CoachingToolDependencies(
                preferences_reader=preferences_repo,
                contact_reader=contact_repo,
                meeting_reader=meeting_repo,
                memory_reader=memory_repo,
                proposal_stager=proposal_repo,
                proposal_agent=resolved_proposal_agent,
                clock=resolved_clock,
                id_generator=resolved_ids,
                io_timeout_seconds=timeout,
            ),
            settings=settings,
        )
    else:
        resolved_brief_agent = FakeBriefCoachAgent()

    return ServiceContainer(
        clock=resolved_clock,
        id_generator=resolved_ids,
        authenticator=authenticator or build_runtime_authenticator(settings, clock=resolved_clock),
        preferences_repo=preferences_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        proposal_repo=proposal_repo,
        memory_repo=memory_repo,
        brief_agent=resolved_brief_agent,
        proposal_agent=resolved_proposal_agent,
        idempotency_repo=idempotency_repo,
        job_repo=FirestoreMemoryExtractionJobRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        job_runner=InProcessBackgroundJobRunner(
            max_concurrency=settings.memory_job_max_concurrency,
        ),
    )


def build_service_container(
    settings: AppSettings,
    *,
    firestore_client: firestore.AsyncClient | None = None,
) -> ServiceContainer:
    """Construct the active ``ServiceContainer`` based on ``settings.persistence_backend``."""
    if settings.persistence_backend == "firestore":
        return build_firestore_service_container(settings, client=firestore_client)

    container = FakeServiceContainer()
    container.authenticator = build_runtime_authenticator(settings, clock=container.clock)
    container.job_runner = InProcessBackgroundJobRunner(
        max_concurrency=settings.memory_job_max_concurrency,
    )
    if settings.seed_eval_fixtures:
        from app.infrastructure.stubs.eval_fixtures import populate_in_memory_eval_fixtures

        populate_in_memory_eval_fixtures(container)
    if _should_use_adk_memory_extractor(settings):
        container.proposal_agent = AdkMemoryProposalAdapter(settings=settings)
    if _should_use_adk_brief_coach(settings):
        container.brief_agent = AdkConversationCoachBriefAdapter(
            tool_dependencies=CoachingToolDependencies(
                preferences_reader=container.preferences_repo,
                contact_reader=container.contact_repo,
                meeting_reader=container.meeting_repo,
                memory_reader=container.memory_repo,
                proposal_stager=container.proposal_repo,
                proposal_agent=container.proposal_agent,
                clock=container.clock,
                id_generator=container.id_generator,
                io_timeout_seconds=settings.firestore_timeout_seconds,
            ),
            settings=settings,
        )
    return container
