"""Runtime dependency container builders for in-memory fake and Firestore backends."""

from __future__ import annotations

from google.cloud import firestore

from app.config import AppSettings
from app.domain.health import ClockPort
from app.domain.ports import (
    AuthenticatorPort,
    BriefCoachAgentPort,
    IdGeneratorPort,
    MemoryProposalAgentPort,
)
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.fakes import (
    FakeAuthenticator,
    FakeBriefCoachAgent,
    FakeMemoryProposalAgent,
    FakeServiceContainer,
    ServiceContainer,
    UuidIdGenerator,
)
from app.infrastructure.firestore_repositories import (
    FirestoreBriefRepository,
    FirestoreContactRepository,
    FirestoreMeetingRepository,
    FirestoreMemoryProposalRepository,
    FirestoreMemoryRepository,
    FirestoreUserPreferencesRepository,
)
from app.infrastructure.session_service_factory import create_firestore_async_client


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
    return ServiceContainer(
        clock=clock or SystemUtcClock(),
        id_generator=id_generator or UuidIdGenerator(),
        authenticator=authenticator or FakeAuthenticator(),
        preferences_repo=FirestoreUserPreferencesRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        contact_repo=FirestoreContactRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        meeting_repo=FirestoreMeetingRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        brief_repo=FirestoreBriefRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        proposal_repo=FirestoreMemoryProposalRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        memory_repo=FirestoreMemoryRepository(
            resolved_client,
            timeout_seconds=timeout,
        ),
        brief_agent=brief_agent or FakeBriefCoachAgent(),
        proposal_agent=proposal_agent or FakeMemoryProposalAgent(),
    )


def build_service_container(
    settings: AppSettings,
    *,
    firestore_client: firestore.AsyncClient | None = None,
) -> ServiceContainer:
    """Construct the active ``ServiceContainer`` based on ``settings.persistence_backend``."""
    if settings.persistence_backend == "firestore":
        return build_firestore_service_container(settings, client=firestore_client)
    return FakeServiceContainer()
