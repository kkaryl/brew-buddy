"""Unit tests for application services, separated proposal storage, and fake adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.application.services import (
    BriefService,
    ContactService,
    MeetingService,
    MemoryService,
)
from app.domain.errors import VersionConflictError
from app.domain.models import AuthenticatedPrincipal
from app.domain.types import (
    ConsentStatus,
    MeetingPurpose,
    MeetingTone,
    MemoryScope,
    ProposalStatus,
)
from app.infrastructure.fakes import (
    FakeBriefCoachAgent,
    FakeMemoryProposalAgent,
    InMemoryBriefRepository,
    InMemoryContactRepository,
    InMemoryMeetingRepository,
    InMemoryMemoryProposalRepository,
    InMemoryMemoryRepository,
    InMemoryUserPreferencesRepository,
    SequentialIdGenerator,
)


class AdvancingUtcClock:
    """Deterministic clock advancing by one minute on every read."""

    def __init__(self, start: datetime) -> None:
        self._current = start

    def now_utc(self) -> datetime:
        current = self._current
        self._current = self._current + timedelta(minutes=1)
        return current


def test_memory_proposals_are_isolated_from_approved_memories_until_approved() -> None:
    clock = AdvancingUtcClock(datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC))
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
    brief_service = BriefService(
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        memory_repo=memory_repo,
        preferences_repo=preferences_repo,
        brief_agent=brief_agent,
        clock=clock,
        id_generator=ids,
    )
    memory_service = MemoryService(
        proposal_repo=proposal_repo,
        memory_repo=memory_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        proposal_agent=proposal_agent,
        clock=clock,
        id_generator=ids,
    )

    alice = AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")
    contact = contact_service.create_contact(
        principal=alice,
        name="Marcus Vance",
        title="VP of Product",
        organization="Northstar AI",
    )

    initial_brief = brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.CUSTOMER_DISCOVERY,
        tone=MeetingTone.CURIOUS_EXPLORATORY,
        meeting_objective="Understand enterprise onboarding bottlenecks.",
        duration_minutes=25,
    )
    assert initial_brief.referenced_memory_ids == []
    assert len(meeting_service.list_meetings(principal=alice)) == 1

    # Propose memories with embedded PII that must be redacted
    proposals = memory_service.propose_memories(
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
    assert len(proposal_repo.list_by_owner(alice.user_id, status=ProposalStatus.PENDING)) == 2
    assert memory_service.list_memories(principal=alice) == []

    # Generating another brief before approval still sees zero approved memories
    uninformed_brief = brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        tone=MeetingTone.WARM_CASUAL,
        meeting_objective="Quick catch-up on pilot progress.",
        duration_minutes=15,
    )
    assert uninformed_brief.referenced_memory_ids == []

    # Approve only the first proposal
    approved_mem = memory_service.approve_proposal(
        principal=alice,
        proposal_id=proposals[0].id,
        expected_version=1,
    )
    assert approved_mem.version == 1
    assert approved_mem.source.proposal_id == proposals[0].id
    assert approved_mem.scope is MemoryScope.CONTACT

    # Verify proposal transitioned to APPROVED in proposal_repo while second remains PENDING
    assert len(proposal_repo.list_by_owner(alice.user_id, status=ProposalStatus.APPROVED)) == 1
    assert len(proposal_repo.list_by_owner(alice.user_id, status=ProposalStatus.PENDING)) == 1
    assert [m.id for m in memory_service.list_memories(principal=alice)] == [approved_mem.id]

    # Subsequent brief generation now incorporates the approved memory
    informed_brief = brief_service.generate_brief(
        principal=alice,
        contact_id=contact.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        tone=MeetingTone.WARM_CASUAL,
        meeting_objective="Follow up on enterprise onboarding pilot.",
        duration_minutes=30,
    )
    assert informed_brief.referenced_memory_ids == [approved_mem.id]

    # Revoking consent hides memory from active recall and default listing
    revoked = memory_service.update_memory(
        principal=alice,
        memory_id=approved_mem.id,
        expected_version=1,
        consent_status=ConsentStatus.REVOKED,
    )
    assert revoked.consent_status is ConsentStatus.REVOKED
    assert memory_service.list_memories(principal=alice) == []
    assert len(memory_service.list_memories(principal=alice, include_revoked=True)) == 1


def test_repository_optimistic_concurrency_guards() -> None:
    clock = AdvancingUtcClock(datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC))
    ids = SequentialIdGenerator()
    contact_repo = InMemoryContactRepository()
    contact_service = ContactService(
        contact_repo=contact_repo,
        clock=clock,
        id_generator=ids,
    )
    alice = AuthenticatedPrincipal(user_id="usr_alice")
    created = contact_service.create_contact(principal=alice, name="Elena Rostova")

    updated_v2 = created.model_copy(update={"version": 2, "title": "Principal PM"})
    contact_repo.save(updated_v2, expected_version=1)

    stale_update = created.model_copy(update={"version": 2, "title": "Stale Write"})
    with pytest.raises(VersionConflictError) as exc_info:
        contact_repo.save(stale_update, expected_version=1)

    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2
