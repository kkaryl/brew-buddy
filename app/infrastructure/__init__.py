"""Infrastructure adapters, Firestore repositories, session factory, and fake implementations."""

from __future__ import annotations

from app.infrastructure.adk_brief_coach import AdkConversationCoachBriefAdapter
from app.infrastructure.adk_memory_extractor import AdkMemoryProposalAdapter
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.container import (
    build_firestore_service_container,
    build_service_container,
)
from app.infrastructure.fakes import (
    DEFAULT_FAKE_TOKENS,
    FakeAuthenticator,
    FakeBriefCoachAgent,
    FakeMemoryProposalAgent,
    FakeServiceContainer,
    InMemoryBriefRepository,
    InMemoryContactRepository,
    InMemoryMeetingRepository,
    InMemoryMemoryProposalRepository,
    InMemoryMemoryRepository,
    InMemoryUserPreferencesRepository,
    InMemoryWorkflowIdempotencyRepository,
    SequentialIdGenerator,
    ServiceContainer,
    UuidIdGenerator,
    scrub_basic_pii,
)
from app.infrastructure.firestore_repositories import (
    FirestoreBriefRepository,
    FirestoreContactRepository,
    FirestoreMeetingRepository,
    FirestoreMemoryProposalRepository,
    FirestoreMemoryRepository,
    FirestoreUserPreferencesRepository,
    FirestoreWorkflowIdempotencyRepository,
)
from app.infrastructure.session_service_factory import (
    SessionServiceFactory,
    create_adk_firestore_session_service,
    create_firestore_async_client,
    validate_isolated_session_collection,
)

__all__ = [
    "DEFAULT_FAKE_TOKENS",
    "AdkConversationCoachBriefAdapter",
    "AdkMemoryProposalAdapter",
    "FakeAuthenticator",
    "FakeBriefCoachAgent",
    "FakeMemoryProposalAgent",
    "FakeServiceContainer",
    "FirestoreBriefRepository",
    "FirestoreContactRepository",
    "FirestoreMeetingRepository",
    "FirestoreMemoryProposalRepository",
    "FirestoreMemoryRepository",
    "FirestoreUserPreferencesRepository",
    "FirestoreWorkflowIdempotencyRepository",
    "InMemoryBriefRepository",
    "InMemoryContactRepository",
    "InMemoryMeetingRepository",
    "InMemoryMemoryProposalRepository",
    "InMemoryMemoryRepository",
    "InMemoryUserPreferencesRepository",
    "InMemoryWorkflowIdempotencyRepository",
    "SequentialIdGenerator",
    "ServiceContainer",
    "SessionServiceFactory",
    "SystemUtcClock",
    "UuidIdGenerator",
    "build_firestore_service_container",
    "build_service_container",
    "create_adk_firestore_session_service",
    "create_firestore_async_client",
    "scrub_basic_pii",
    "validate_isolated_session_collection",
]
