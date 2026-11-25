"""Preparation brief, its parts, workflow result and idempotency record."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, model_validator

from app.domain.briefs.diagnostics import BriefWorkflowDiagnostics
from app.domain.briefs.types import (
    AgendaDescriptionText,
    AgendaTitleText,
    BriefWorkflowOperation,
    FollowUpTopicText,
    OpenerText,
    QuestionPromptText,
)
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingTone
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.types import (
    ContextSummaryText,
    EntityId,
    MeetingDurationMinutes,
    MemoryBodyText,
    ObjectiveText,
    RationaleText,
    ShortTagText,
    UtcDatetime,
    VersionNumber,
)


class TimeBoxedAgendaItem(ImmutableDomainModel):
    """Single time-allocated segment within a preparation brief's agenda."""

    title: AgendaTitleText
    duration_minutes: Annotated[int, Field(ge=1, le=180)]
    description: AgendaDescriptionText


class ConversationQuestion(ImmutableDomainModel):
    """Suggested question paired with its coaching rationale."""

    id: EntityId
    question: QuestionPromptText
    rationale: RationaleText
    category: ShortTagText | None = None


class PreparationBrief(ImmutableDomainModel):
    """Versioned, time-boxed preparation brief for a meeting."""

    id: EntityId
    owner_user_id: EntityId
    meeting_id: EntityId
    contact_id: EntityId
    duration_minutes: MeetingDurationMinutes
    tone: MeetingTone
    contact_context: ContextSummaryText
    meeting_objective: ObjectiveText
    conversation_openers: list[OpenerText] = Field(min_length=1, max_length=10)
    time_boxed_agenda: list[TimeBoxedAgendaItem] = Field(min_length=1, max_length=12)
    suggested_questions: list[ConversationQuestion] = Field(min_length=1, max_length=15)
    suggested_follow_up_topics: list[FollowUpTopicText] = Field(min_length=1, max_length=10)
    referenced_memory_ids: list[EntityId] = Field(default_factory=list, max_length=50)
    revision_summary: MemoryBodyText | None = None
    version: VersionNumber = 1
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_brief_invariants(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)

        allocated_total = sum(segment.duration_minutes for segment in self.time_boxed_agenda)
        if allocated_total != self.duration_minutes:
            msg = (
                f"Time-boxed agenda segments must sum to {self.duration_minutes} minutes, "
                f"got {allocated_total} minutes."
            )
            raise ValueError(msg)

        question_ids = [item.id for item in self.suggested_questions]
        if len(set(question_ids)) != len(question_ids):
            msg = "Suggested questions must have unique IDs within a brief."
            raise ValueError(msg)

        return self


class BriefWorkflowResult(ImmutableDomainModel):
    """Structured workflow outcome combining the persisted brief, meeting, and diagnostics."""

    brief: PreparationBrief
    meeting: Meeting
    diagnostics: BriefWorkflowDiagnostics


class WorkflowIdempotencyRecord(ImmutableDomainModel):
    """Durable deduplication record binding a caller idempotency key to a persisted brief."""

    owner_user_id: EntityId
    operation: BriefWorkflowOperation
    idempotency_key: EntityId
    payload_fingerprint: Annotated[str, Field(min_length=8, max_length=128)]
    brief_id: EntityId
    brief_version: VersionNumber
    meeting_id: EntityId
    created_at: UtcDatetime
