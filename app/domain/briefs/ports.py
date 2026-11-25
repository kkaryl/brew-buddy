"""Brief repository, coach agent port and workflow idempotency port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import (
    ConversationQuestion,
    PreparationBrief,
    TimeBoxedAgendaItem,
    WorkflowIdempotencyRecord,
)
from app.domain.briefs.types import BriefWorkflowOperation, FollowUpTopicText, OpenerText
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingTone
from app.domain.shared.types import (
    ContextSummaryText,
    EntityId,
    MeetingDurationMinutes,
    MemoryBodyText,
    ObjectiveText,
)


class BriefRepository(Protocol):
    """Async persistence port for ``users/{uid}/briefs/{briefId}``."""

    async def get_for_owner(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> PreparationBrief | None:
        """Fetch ``brief_id`` strictly under ``owner_user_id``."""

    async def exists_for_any_owner(self, brief_id: str) -> bool:
        """Return ``True`` if ``brief_id`` exists under any user partition."""

    async def list_by_meeting(
        self,
        owner_user_id: str,
        meeting_id: str,
    ) -> list[PreparationBrief]:
        """List preparation briefs owned by ``owner_user_id`` for ``meeting_id``."""

    async def save(
        self,
        brief: PreparationBrief,
        *,
        expected_version: int | None = None,
    ) -> PreparationBrief:
        """Persist a new or revised brief enforcing optimistic version checks."""

    async def list_revisions(
        self,
        owner_user_id: str,
        brief_id: str,
    ) -> list[PreparationBrief]:
        """Return immutable historical revisions of ``brief_id`` ordered by version."""

    async def get_revision(
        self,
        owner_user_id: str,
        brief_id: str,
        version: int,
    ) -> PreparationBrief | None:
        """Fetch a specific immutable historical revision of ``brief_id``."""


class GeneratedBriefContent(BaseModel):
    """Validated structured output returned by the brief coaching agent port."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contact_context: ContextSummaryText
    meeting_objective: ObjectiveText
    conversation_openers: list[OpenerText] = Field(min_length=1, max_length=10)
    time_boxed_agenda: list[TimeBoxedAgendaItem] = Field(min_length=1, max_length=12)
    suggested_questions: list[ConversationQuestion] = Field(min_length=1, max_length=15)
    suggested_follow_up_topics: list[FollowUpTopicText] = Field(min_length=1, max_length=10)
    referenced_memory_ids: list[EntityId] = Field(default_factory=list, max_length=50)
    revision_summary: MemoryBodyText | None = None


class BriefAttemptMetrics(BaseModel):
    """Per-attempt execution telemetry and safeguard budget shared with coach adapters."""

    model_config = ConfigDict(extra="forbid")

    remaining_model_budget: int = Field(default=6, ge=0, le=50)
    max_tool_retries: int = Field(default=1, ge=0, le=5)
    model_invocations: int = Field(default=0, ge=0)
    tool_invocations: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    degraded_tools: list[str] = Field(default_factory=list)


class WorkflowIdempotencyRepository(Protocol):
    """Async persistence port for workflow request deduplication records."""

    async def get(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> WorkflowIdempotencyRecord | None:
        """Fetch an existing deduplication record for ``owner_user_id``."""

    async def save(
        self,
        record: WorkflowIdempotencyRecord,
    ) -> WorkflowIdempotencyRecord:
        """Persist a workflow deduplication record."""


class BriefCoachAgentPort(Protocol):
    """Async agent interface synthesizing and revising structured preparation briefs."""

    async def generate_brief(
        self,
        *,
        meeting: Meeting,
        context: BriefPreparationContext,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Synthesize an initial time-boxed brief grounded in ``BriefPreparationContext``."""

    async def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        context: BriefPreparationContext,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        """Revise an existing preparation brief grounded in ``BriefPreparationContext``."""
