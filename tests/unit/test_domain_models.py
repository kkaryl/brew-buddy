"""Unit tests for Brew Pydantic v2 domain entities, invariants, and UTC timestamps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain.briefs.models import ConversationQuestion, PreparationBrief, TimeBoxedAgendaItem
from app.domain.contacts.models import Contact
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingPurpose, MeetingTone
from app.domain.memory.models import Memory, MemoryProposal, MemorySource, UserPreferences
from app.domain.memory.types import (
    ConsentStatus,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ProposalStatus,
)
from app.domain.shared.errors import ConflictError, DomainValidationError


def _utc(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 11, 22, hour, minute, 0, tzinfo=UTC)


def test_utc_timestamp_normalization_and_naive_rejection() -> None:
    plus_two = timezone(timedelta(hours=2))
    contact = Contact(
        id="cnt_100",
        owner_user_id="usr_alice",
        name="Jordan Lee",
        title="Staff Engineer",
        role="Mentor",
        organization="Acme Cloud",
        context_notes="Met at distributed systems summit.",
        created_at=datetime(2026, 11, 22, 14, 30, 0, tzinfo=plus_two),
        updated_at=datetime(2026, 11, 22, 15, 0, 0, tzinfo=plus_two),
    )

    assert contact.created_at == datetime(2026, 11, 22, 12, 30, 0, tzinfo=UTC)
    assert contact.created_at.tzinfo is UTC
    assert contact.updated_at == datetime(2026, 11, 22, 13, 0, 0, tzinfo=UTC)

    # Naive datetime rejected
    with pytest.raises(ValidationError, match="timezone-aware"):
        Contact(
            id="cnt_naive",
            owner_user_id="usr_alice",
            name="Jordan Lee",
            created_at=datetime(2026, 11, 22, 12, 0, 0),
            updated_at=_utc(12, 5),
        )

    # Out-of-range calendar year rejected
    with pytest.raises(ValidationError, match="Timestamp year"):
        Contact(
            id="cnt_year",
            owner_user_id="usr_alice",
            name="Jordan Lee",
            created_at=datetime(1999, 12, 31, 23, 59, 0, tzinfo=UTC),
            updated_at=_utc(12, 0),
        )

    # updated_at < created_at rejected
    with pytest.raises(ValidationError, match="updated_at"):
        Contact(
            id="cnt_order",
            owner_user_id="usr_alice",
            name="Jordan Lee",
            created_at=_utc(14, 0),
            updated_at=_utc(13, 0),
        )


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "   ",
        "../traversal",
        "id/with/slash",
        "id with spaces",
        "_leading_underscore",
        "a" * 129,
    ],
)
def test_entity_id_rejects_invalid_identifiers(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Contact(
            id=bad_id,
            owner_user_id="usr_alice",
            name="Valid Name",
            created_at=_utc(),
            updated_at=_utc(),
        )


def test_user_preferences_and_meeting_validation() -> None:
    prefs = UserPreferences(
        id="pref_1",
        owner_user_id="usr_alice",
        default_tone=MeetingTone.CURIOUS_EXPLORATORY,
        default_duration_minutes=45,
        preferred_question_count=5,
        communication_style_notes="Keep openers warm and direct.",
        focus_areas=["system design", "career growth"],
        created_at=_utc(),
        updated_at=_utc(),
    )
    serialized = prefs.model_dump(mode="json")
    restored = UserPreferences.model_validate(serialized)
    assert restored == prefs

    meeting = Meeting(
        id="mtg_1",
        owner_user_id="usr_alice",
        contact_id="cnt_1",
        purpose=MeetingPurpose.MENTORSHIP,
        tone=MeetingTone.CANDID_COACHING,
        objective="Discuss staff-level technical leadership habits.",
        duration_minutes=30,
        scheduled_at=_utc(16, 0),
        created_at=_utc(12, 0),
        updated_at=_utc(12, 0),
    )
    assert meeting.duration_minutes == 30

    with pytest.raises(ValidationError):
        Meeting(
            id="mtg_short",
            owner_user_id="usr_alice",
            contact_id="cnt_1",
            purpose=MeetingPurpose.COFFEE_CHAT,
            objective="Too short duration.",
            duration_minutes=4,
            created_at=_utc(),
            updated_at=_utc(),
        )

    with pytest.raises(ValidationError):
        Meeting(
            id="mtg_long",
            owner_user_id="usr_alice",
            contact_id="cnt_1",
            purpose=MeetingPurpose.COFFEE_CHAT,
            objective="Too long duration.",
            duration_minutes=185,
            created_at=_utc(),
            updated_at=_utc(),
        )


def test_preparation_brief_enforces_timebox_and_question_uniqueness() -> None:
    brief = PreparationBrief(
        id="brf_1",
        owner_user_id="usr_alice",
        meeting_id="mtg_1",
        contact_id="cnt_1",
        duration_minutes=30,
        tone=MeetingTone.WARM_CASUAL,
        contact_context="Priya Nair, Engineering Director at Nimbus.",
        meeting_objective="Understand platform migration lessons.",
        conversation_openers=["Thanks for making time today, Priya!"],
        time_boxed_agenda=[
            TimeBoxedAgendaItem(
                title="Warm-up",
                duration_minutes=5,
                description="Reconnect and frame goal.",
            ),
            TimeBoxedAgendaItem(
                title="Deep Dive",
                duration_minutes=20,
                description="Explore platform migration trade-offs.",
            ),
            TimeBoxedAgendaItem(
                title="Wrap-up",
                duration_minutes=5,
                description="Confirm takeaways and next steps.",
            ),
        ],
        suggested_questions=[
            ConversationQuestion(
                id="q_1",
                question="Which migration bottleneck surprised your team most?",
                rationale="Surfaces concrete lessons rather than high-level summaries.",
                category="architecture",
            )
        ],
        suggested_follow_up_topics=["Share migration RFC template"],
        referenced_memory_ids=["mem_1"],
        version=1,
        created_at=_utc(12, 0),
        updated_at=_utc(12, 0),
    )
    assert brief.version == 1

    # Agenda minutes mismatching duration_minutes fails validation
    with pytest.raises(ValidationError, match="sum to 30 minutes"):
        PreparationBrief(
            id="brf_bad_sum",
            owner_user_id="usr_alice",
            meeting_id="mtg_1",
            contact_id="cnt_1",
            duration_minutes=30,
            tone=MeetingTone.WARM_CASUAL,
            contact_context="Priya Nair, Engineering Director at Nimbus.",
            meeting_objective="Understand platform migration lessons.",
            conversation_openers=["Thanks for making time today, Priya!"],
            time_boxed_agenda=[
                TimeBoxedAgendaItem(
                    title="Only Segment",
                    duration_minutes=20,
                    description="Leaves 10 minutes unaccounted for.",
                )
            ],
            suggested_questions=brief.suggested_questions,
            suggested_follow_up_topics=brief.suggested_follow_up_topics,
            created_at=_utc(),
            updated_at=_utc(),
        )

    # Duplicate ConversationQuestion IDs fail validation
    dup_q = ConversationQuestion(
        id="q_1",
        question="Another question reusing ID q_1?",
        rationale="Duplicate ID test.",
    )
    with pytest.raises(ValidationError, match="unique IDs"):
        PreparationBrief(
            id="brf_dup_q",
            owner_user_id="usr_alice",
            meeting_id="mtg_1",
            contact_id="cnt_1",
            duration_minutes=30,
            tone=MeetingTone.WARM_CASUAL,
            contact_context=brief.contact_context,
            meeting_objective=brief.meeting_objective,
            conversation_openers=brief.conversation_openers,
            time_boxed_agenda=brief.time_boxed_agenda,
            suggested_questions=[brief.suggested_questions[0], dup_q],
            suggested_follow_up_topics=brief.suggested_follow_up_topics,
            created_at=_utc(),
            updated_at=_utc(),
        )


def test_memory_proposal_and_approved_memory_invariants_and_transitions() -> None:
    source = MemorySource(
        source_type=MemorySourceType.MEETING_NOTES,
        meeting_id="mtg_1",
        excerpt="Priya prefers async agendas 24h before mentorship chats.",
        recorded_at=_utc(12, 0),
    )

    # Contact scope requires contact_id
    with pytest.raises(ValidationError, match="contact_id is required"):
        MemoryProposal(
            id="prop_invalid",
            owner_user_id="usr_alice",
            scope=MemoryScope.CONTACT,
            contact_id=None,
            memory_type=MemoryType.COUNTERPART_BACKGROUND,
            text="Missing contact ID.",
            rationale="Should fail scope check.",
            source=source,
            created_at=_utc(),
            updated_at=_utc(),
        )

    # User preference scope forbids contact_id
    with pytest.raises(ValidationError, match="contact_id must be omitted"):
        Memory(
            id="mem_invalid",
            owner_user_id="usr_alice",
            scope=MemoryScope.USER_PREFERENCE,
            contact_id="cnt_1",
            memory_type=MemoryType.COMMUNICATION_PREFERENCE,
            text="Unexpected contact ID.",
            source=source,
            created_at=_utc(),
            updated_at=_utc(),
        )

    proposal = MemoryProposal(
        id="prop_1",
        owner_user_id="usr_alice",
        scope=MemoryScope.CONTACT,
        contact_id="cnt_1",
        memory_type=MemoryType.COUNTERPART_BACKGROUND,
        text="Priya prefers async agendas 24h before mentorship chats.",
        rationale="Useful context when preparing for future sessions with Priya.",
        source=source,
        created_at=_utc(12, 0),
        updated_at=_utc(12, 0),
    )
    assert proposal.status is ProposalStatus.PENDING
    assert proposal.version == 1

    approved_proposal = proposal.mark_approved(
        approved_memory_id="mem_1",
        reviewed_at=_utc(12, 15),
    )
    assert approved_proposal.status is ProposalStatus.APPROVED
    assert approved_proposal.approved_memory_id == "mem_1"
    assert approved_proposal.version == 2

    # Approving an already approved proposal raises ConflictError
    with pytest.raises(ConflictError):
        approved_proposal.mark_approved(
            approved_memory_id="mem_2",
            reviewed_at=_utc(12, 30),
        )

    memory = Memory(
        id="mem_1",
        owner_user_id="usr_alice",
        scope=MemoryScope.CONTACT,
        contact_id="cnt_1",
        memory_type=MemoryType.COUNTERPART_BACKGROUND,
        text=proposal.text,
        source=MemorySource(
            source_type=source.source_type,
            meeting_id=source.meeting_id,
            proposal_id=proposal.id,
            excerpt=source.excerpt,
            recorded_at=source.recorded_at,
        ),
        consent_status=ConsentStatus.APPROVED,
        created_at=_utc(12, 15),
        updated_at=_utc(12, 15),
        version=1,
    )

    with pytest.raises(DomainValidationError):
        memory.apply_update(updated_at=_utc(12, 20))

    updated_memory = memory.apply_update(
        text="Priya prefers bullet-point async agendas 24h ahead.",
        consent_status=ConsentStatus.REVOKED,
        updated_at=_utc(12, 20),
    )
    assert updated_memory.version == 2
    assert updated_memory.consent_status is ConsentStatus.REVOKED
