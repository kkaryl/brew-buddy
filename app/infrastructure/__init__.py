"""Infrastructure adapters and injected fake implementations for Brew."""

from __future__ import annotations

from app.infrastructure.clock import SystemUtcClock
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
    SequentialIdGenerator,
    UuidIdGenerator,
    scrub_basic_pii,
)

__all__ = [
    "DEFAULT_FAKE_TOKENS",
    "FakeAuthenticator",
    "FakeBriefCoachAgent",
    "FakeMemoryProposalAgent",
    "FakeServiceContainer",
    "InMemoryBriefRepository",
    "InMemoryContactRepository",
    "InMemoryMeetingRepository",
    "InMemoryMemoryProposalRepository",
    "InMemoryMemoryRepository",
    "InMemoryUserPreferencesRepository",
    "SequentialIdGenerator",
    "SystemUtcClock",
    "UuidIdGenerator",
    "scrub_basic_pii",
]
