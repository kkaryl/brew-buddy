"""Regression tests for duplicate and supersession decisions on long-term memory.

Two rules are pinned here because both protect the human-in-the-loop guarantee:

1. A statement that repeats an approved memory with a different figure is an update the
   user must see, never a duplicate that is silently merged away.
2. Approving a proposal may only supersede a memory the user was shown as the target,
   either staged on the proposal or named in the approval request.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.memory.persistence import MemoryPersistenceService
from app.composition.container import FakeServiceContainer
from app.domain.contacts.models import Contact
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.memory.models import Memory, MemoryProposal, MemorySource
from app.domain.memory.relations import MemoryRelationKind, classify_candidate_against_existing
from app.domain.memory.types import (
    MemoryLifecycleState,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)

_NOW = datetime(2026, 11, 24, 9, 0, 0, tzinfo=UTC)
_OWNER = "usr_alice"
_CONTACT_ID = "cnt_priya"
_SOURCE = MemorySource(source_type=MemorySourceType.MEETING_NOTES, recorded_at=_NOW)


def _approved_memory(memory_id: str, text: str) -> Memory:
    return Memory(
        id=memory_id,
        owner_user_id=_OWNER,
        scope=MemoryScope.CONTACT,
        contact_id=_CONTACT_ID,
        memory_type=MemoryType.COUNTERPART_BACKGROUND,
        text=text,
        source=_SOURCE,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _classify(candidate_text: str, existing: Memory) -> MemoryRelationKind:
    return classify_candidate_against_existing(
        scope=MemoryScope.CONTACT,
        contact_id=_CONTACT_ID,
        memory_type=MemoryType.COUNTERPART_BACKGROUND,
        text=candidate_text,
        existing_memories=[existing],
        contact_name="Priya Shah",
    ).kind


@pytest.mark.parametrize(
    ("existing_text", "candidate_text"),
    [
        (
            "Team size is 12 engineers on platform infra",
            "Team size is 40 engineers on platform infra",
        ),
        (
            "Priya manages 3 direct reports on the payments team",
            "Priya manages 5 direct reports on the payments team",
        ),
        (
            "Target launch for the migration is 2026 across all regions",
            "Target launch for the migration is 2027 across all regions",
        ),
    ],
)
def test_same_statement_with_a_changed_figure_is_an_update_not_a_duplicate(
    existing_text: str,
    candidate_text: str,
) -> None:
    existing = _approved_memory("mem_existing", existing_text)

    assert _classify(candidate_text, existing) is MemoryRelationKind.SUPERSEDES


def test_same_statement_with_the_same_figure_is_still_a_duplicate() -> None:
    existing = _approved_memory("mem_existing", "Team size is 12 engineers on platform infra")

    assert (
        _classify("Team size is 12 engineers on the platform infra.", existing)
        is MemoryRelationKind.DUPLICATE
    )


@pytest.mark.asyncio
async def test_approval_never_supersedes_a_memory_the_user_was_not_shown() -> None:
    container = FakeServiceContainer()
    await container.contact_repo.save(
        Contact(
            id=_CONTACT_ID,
            owner_user_id=_OWNER,
            name="Priya Shah",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    unrelated = _approved_memory("mem_hiking", "Priya likes hiking in Marin on weekends")
    await container.memory_repo.save(unrelated)
    # Staged with no supersede target: the review card shows the user no conflict.
    await container.proposal_repo.save(
        MemoryProposal(
            id="prop_office",
            owner_user_id=_OWNER,
            scope=MemoryScope.CONTACT,
            contact_id=_CONTACT_ID,
            memory_type=MemoryType.COUNTERPART_BACKGROUND,
            text="Priya never worked in the Marin office",
            rationale="Corrects an assumption about where she is based.",
            source=_SOURCE,
            status=ProposalStatus.PENDING,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    service = MemoryPersistenceService(
        preferences_repo=container.preferences_repo,
        proposal_repo=container.proposal_repo,
        memory_repo=container.memory_repo,
        contact_repo=container.contact_repo,
        meeting_repo=container.meeting_repo,
        brief_repo=container.brief_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
    )

    approved = await service.approve_proposal(
        principal=AuthenticatedPrincipal(user_id=_OWNER),
        proposal_id="prop_office",
        expected_version=1,
    )

    assert approved.supersedes_memory_id is None
    still_stored = await container.memory_repo.get_for_owner(_OWNER, unrelated.id)
    assert still_stored is not None
    assert still_stored.lifecycle_state is MemoryLifecycleState.APPROVED
    active = await container.memory_repo.list_by_owner(_OWNER)
    assert {memory.id for memory in active} == {unrelated.id, approved.id}
