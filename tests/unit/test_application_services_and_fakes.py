"""Async unit tests for memory retrieval, memory persistence, session factory, and fake repos."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.application.briefs.service import BriefService
from app.application.contacts.service import ContactService
from app.application.meetings.service import MeetingService
from app.application.memory.persistence import MemoryPersistenceService
from app.application.memory.retrieval import MemoryRetrievalService
from app.application.memory.service import MemoryService
from app.config import AppSettings
from app.domain.briefs.context import ContextBudget
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingPurpose, MeetingStatus, MeetingTone
from app.domain.memory.models import Memory, MemorySource
from app.domain.memory.types import (
    ConsentStatus,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)
from app.domain.shared.errors import (
    AuthorizationError,
    InvalidConfigurationError,
    VersionConflictError,
)
from app.infrastructure.ids import SequentialIdGenerator
from app.infrastructure.inmemory.briefs import InMemoryBriefRepository
from app.infrastructure.inmemory.contacts import InMemoryContactRepository
from app.infrastructure.inmemory.meetings import InMemoryMeetingRepository
from app.infrastructure.inmemory.memories import InMemoryMemoryRepository
from app.infrastructure.inmemory.memory_proposals import InMemoryMemoryProposalRepository
from app.infrastructure.inmemory.preferences import InMemoryUserPreferencesRepository
from app.infrastructure.sessions import SessionServiceFactory, validate_isolated_session_collection
from app.infrastructure.stubs.brief_coach import FakeBriefCoachAgent
from app.infrastructure.stubs.memory_extractor import FakeMemoryProposalAgent
from tests.support.brief_context import assemble_brief_context


class AdvancingUtcClock:
    """Deterministic clock advancing by one minute on every read."""

    def __init__(self, start: datetime) -> None:
        self._current = start

    def now_utc(self) -> datetime:
        current = self._current
        self._current = self._current + timedelta(minutes=1)
        return current


def _wire_local_services(
    clock: AdvancingUtcClock,
) -> tuple[
    ContactService,
    MeetingService,
    BriefService,
    MemoryService,
    MemoryRetrievalService,
    MemoryPersistenceService,
    InMemoryMemoryProposalRepository,
    InMemoryMeetingRepository,
    InMemoryMemoryRepository,
]:
    ids = SequentialIdGenerator()
    contact_repo = InMemoryContactRepository()
    meeting_repo = InMemoryMeetingRepository()
    brief_repo = InMemoryBriefRepository()
    proposal_repo = InMemoryMemoryProposalRepository()
    memory_repo = InMemoryMemoryRepository()
    preferences_repo = InMemoryUserPreferencesRepository()
    brief_agent = FakeBriefCoachAgent()
    proposal_agent = FakeMemoryProposalAgent()

    contact_service = ContactService(
        contact_repo=contact_repo,
        clock=clock,
        id_generator=ids,
    )
    meeting_service = MeetingService(
        meeting_repo=meeting_repo,
        contact_repo=contact_repo,
    )
    retrieval_service = MemoryRetrievalService(
        preferences_repo=preferences_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        memory_repo=memory_repo,
    )
    persistence_service = MemoryPersistenceService(
        preferences_repo=preferences_repo,
        proposal_repo=proposal_repo,
        memory_repo=memory_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        proposal_agent=proposal_agent,
        clock=clock,
        id_generator=ids,
    )
    brief_service = BriefService(
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        memory_retrieval=retrieval_service,
        memory_persistence=persistence_service,
        brief_agent=brief_agent,
        clock=clock,
        id_generator=ids,
    )
    memory_service = MemoryService(
        retrieval=retrieval_service,
        persistence=persistence_service,
    )
    return (
        contact_service,
        meeting_service,
        brief_service,
        memory_service,
        retrieval_service,
        persistence_service,
        proposal_repo,
        meeting_repo,
        memory_repo,
    )


@pytest.mark.asyncio
async def test_memory_proposals_are_isolated_from_approved_memories_until_approved() -> None:
    clock = AdvancingUtcClock(datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC))
    (
        contact_service,
        meeting_service,
        brief_service,
        memory_service,
        _retrieval_service,
        _persistence_service,
        proposal_repo,
        _meeting_repo,
        _memory_repo,
    ) = _wire_local_services(clock)

    alice = AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")
    contact = await contact_service.create_contact(
        principal=alice,
        name="Marcus Vance",
        title="VP of Product",
        organization="Northstar AI",
    )

    initial_brief = await brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.CUSTOMER_DISCOVERY,
        tone=MeetingTone.CURIOUS_EXPLORATORY,
        meeting_objective="Understand enterprise onboarding bottlenecks.",
        duration_minutes=25,
    )
    assert initial_brief.referenced_memory_ids == []
    assert len(await meeting_service.list_meetings(principal=alice)) == 1

    # Propose memories with embedded PII that must be redacted
    proposals = await memory_service.propose_memories(
        principal=alice,
        meeting_id=initial_brief.meeting_id,
        brief_id=initial_brief.id,
        notes=(
            "Marcus mentioned onboarding takes 6 weeks, email him at marcus@example.com. "
            "I prefer concise 3-bullet agendas."
        ),
    )
    assert len(proposals) == 2
    assert all("marcus@example.com" not in p.text for p in proposals)
    assert any("[REDACTED_EMAIL]" in p.text for p in proposals)

    # Proposals exist ONLY in proposal_repo; approved memory_repo remains completely empty
    pending = await proposal_repo.list_by_owner(
        alice.user_id,
        status=ProposalStatus.PENDING,
    )
    assert len(pending) == 2
    assert await memory_service.list_memories(principal=alice) == []

    # Generating another brief before approval still sees zero approved memories
    uninformed_brief = await brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        tone=MeetingTone.WARM_CASUAL,
        meeting_objective="Quick catch-up on pilot progress.",
        duration_minutes=15,
    )
    assert uninformed_brief.referenced_memory_ids == []

    # Approve only the first proposal
    approved_mem = await memory_service.approve_proposal(
        principal=alice,
        proposal_id=proposals[0].id,
        expected_version=1,
    )
    assert approved_mem.version == 1
    assert approved_mem.source.proposal_id == proposals[0].id
    assert approved_mem.scope is MemoryScope.CONTACT

    approved_proposals = await proposal_repo.list_by_owner(
        alice.user_id,
        status=ProposalStatus.APPROVED,
    )
    still_pending = await proposal_repo.list_by_owner(
        alice.user_id,
        status=ProposalStatus.PENDING,
    )
    assert len(approved_proposals) == 1
    assert len(still_pending) == 1
    assert [m.id for m in await memory_service.list_memories(principal=alice)] == [approved_mem.id]

    # Subsequent brief generation now incorporates the approved memory
    informed_brief = await brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        tone=MeetingTone.WARM_CASUAL,
        meeting_objective="Follow up on enterprise onboarding pilot.",
        duration_minutes=30,
    )
    assert informed_brief.referenced_memory_ids == [approved_mem.id]

    # Revoking consent hides memory from active recall and default listing
    revoked = await memory_service.update_memory(
        principal=alice,
        memory_id=approved_mem.id,
        expected_version=1,
        consent_status=ConsentStatus.REVOKED,
    )
    assert revoked.consent_status is ConsentStatus.REVOKED
    assert await memory_service.list_memories(principal=alice) == []
    assert len(await memory_service.list_memories(principal=alice, include_revoked=True)) == 1


@pytest.mark.asyncio
async def test_memory_retrieval_builds_bounded_provenance_aware_context_with_user_isolation() -> (
    None
):
    clock = AdvancingUtcClock(datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC))
    (
        contact_service,
        _meeting_service,
        _brief_service,
        _memory_service,
        retrieval_service,
        persistence_service,
        _proposal_repo,
        meeting_repo,
        memory_repo,
    ) = _wire_local_services(clock)

    alice = AuthenticatedPrincipal(user_id="usr_alice")
    bob = AuthenticatedPrincipal(user_id="usr_bob")

    await persistence_service.upsert_user_preferences(
        principal=alice,
        preferred_question_count=5,
        communication_style_notes="Direct and curious.",
        focus_areas=["platform scaling"],
    )
    alice_contact = await contact_service.create_contact(
        principal=alice,
        name="Linnea Berg",
        title="Principal Architect",
        organization="Kiteworks",
    )
    bob_contact = await contact_service.create_contact(
        principal=bob,
        name="Bob Secret Contact",
    )

    # Seed meetings for Alice (including a CANCELLED meeting that must be excluded)
    t0 = clock.now_utc()
    await meeting_repo.save(
        Meeting(
            id="mtg_cancelled",
            owner_user_id=alice.user_id,
            contact_id=alice_contact.id,
            purpose=MeetingPurpose.MENTORSHIP,
            objective="Cancelled session on Kubernetes scaling.",
            duration_minutes=30,
            status=MeetingStatus.CANCELLED,
            created_at=t0,
            updated_at=t0,
        )
    )
    for idx in range(3):
        ts = clock.now_utc()
        await meeting_repo.save(
            Meeting(
                id=f"mtg_hist_{idx}",
                owner_user_id=alice.user_id,
                contact_id=alice_contact.id,
                purpose=MeetingPurpose.MENTORSHIP,
                objective=f"Discuss multi-region Kubernetes scaling stage {idx}.",
                duration_minutes=30,
                notes=f"Key takeaway from session {idx}.",
                status=MeetingStatus.COMPLETED,
                created_at=ts,
                updated_at=ts,
            )
        )

    # Seed Alice preference & contact memories + a revoked memory + Bob's private memory
    src = MemorySource(
        source_type=MemorySourceType.MEETING_NOTES,
        meeting_id="mtg_hist_2",
        proposal_id="prop_99",
        excerpt="Kubernetes federation latency notes",
        recorded_at=clock.now_utc(),
    )
    await memory_repo.save(
        Memory(
            id="mem_pref_1",
            owner_user_id=alice.user_id,
            scope=MemoryScope.USER_PREFERENCE,
            memory_type=MemoryType.AGENDA_PREFERENCE,
            text="Keep opening rapport under 5 minutes.",
            source=src,
            consent_status=ConsentStatus.APPROVED,
            created_at=t0,
            updated_at=clock.now_utc(),
        )
    )
    for idx in range(3):
        await memory_repo.save(
            Memory(
                id=f"mem_cnt_{idx}",
                owner_user_id=alice.user_id,
                scope=MemoryScope.CONTACT,
                contact_id=alice_contact.id,
                memory_type=MemoryType.FOLLOW_UP_COMMITMENT,
                text=f"Follow up on Kubernetes cell architecture benchmark {idx}.",
                source=src,
                consent_status=ConsentStatus.APPROVED,
                created_at=t0,
                updated_at=clock.now_utc(),
            )
        )
    await memory_repo.save(
        Memory(
            id="mem_cnt_revoked",
            owner_user_id=alice.user_id,
            scope=MemoryScope.CONTACT,
            contact_id=alice_contact.id,
            memory_type=MemoryType.COUNTERPART_BACKGROUND,
            text="Revoked note that must never enter context.",
            source=src,
            consent_status=ConsentStatus.REVOKED,
            created_at=t0,
            updated_at=clock.now_utc(),
        )
    )
    await memory_repo.save(
        Memory(
            id="mem_bob_secret",
            owner_user_id=bob.user_id,
            scope=MemoryScope.USER_PREFERENCE,
            memory_type=MemoryType.COMMUNICATION_PREFERENCE,
            text="Bob private preference must never leak to Alice.",
            source=src,
            consent_status=ConsentStatus.APPROVED,
            created_at=t0,
            updated_at=clock.now_utc(),
        )
    )

    budget = ContextBudget(
        max_recent_meetings=2,
        max_contact_memories=2,
        max_preference_memories=1,
        max_total_chars=600,
    )
    context = await assemble_brief_context(
        retrieval_service,
        principal=alice,
        contact_id=alice_contact.id,
        purpose=MeetingPurpose.MENTORSHIP,
        objective="Plan next Kubernetes scaling deep dive.",
        budget=budget,
    )

    assert context.owner_user_id == alice.user_id
    assert context.user_preferences is not None
    assert context.user_preferences.preferred_question_count == 5
    assert context.contact.id == alice_contact.id
    assert len(context.preference_memories) == 1
    assert len(context.contact_memories) <= 2
    assert len(context.recent_meetings) <= 2
    assert all(m.meeting_id != "mtg_cancelled" for m in context.recent_meetings)
    assert all(item.source.proposal_id == "prop_99" for item in context.contact_memories)
    assert "mem_cnt_revoked" not in context.referenced_memory_ids
    assert "mem_bob_secret" not in context.referenced_memory_ids
    assert context.total_context_chars <= 600
    assert context.was_truncated is True

    # Cross-user contact retrieval fails with AuthorizationError
    with pytest.raises(AuthorizationError):
        await assemble_brief_context(
            retrieval_service,
            principal=alice,
            contact_id=bob_contact.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            objective="Ownership check only.",
        )


@pytest.mark.asyncio
async def test_repository_optimistic_concurrency_guards() -> None:
    clock = AdvancingUtcClock(datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC))
    ids = SequentialIdGenerator()
    contact_repo = InMemoryContactRepository()
    contact_service = ContactService(
        contact_repo=contact_repo,
        clock=clock,
        id_generator=ids,
    )
    alice = AuthenticatedPrincipal(user_id="usr_alice")
    created = await contact_service.create_contact(
        principal=alice,
        name="Elena Rostova",
    )

    updated_v2 = created.model_copy(update={"version": 2, "title": "Principal PM"})
    await contact_repo.save(updated_v2, expected_version=1)

    stale_update = created.model_copy(update={"version": 2, "title": "Stale Write"})
    with pytest.raises(VersionConflictError) as exc_info:
        await contact_repo.save(stale_update, expected_version=1)

    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2


def test_session_service_factory_enforces_domain_collection_separation() -> None:
    assert validate_isolated_session_collection("adk-session") == "adk-session"

    for reserved in ("users", "memories", "memoryProposals", "preferences"):
        with pytest.raises(InvalidConfigurationError):
            validate_isolated_session_collection(reserved)
        with pytest.raises(ValidationError):
            AppSettings(adk_firestore_root_collection=reserved)

    in_mem_settings = AppSettings(
        environment="test",
        persistence_backend="in_memory",
        session_backend="in_memory",
        otel_to_cloud=False,
    )
    session_service = SessionServiceFactory(settings=in_mem_settings).create()
    assert session_service.__class__.__name__ == "InMemorySessionService"
