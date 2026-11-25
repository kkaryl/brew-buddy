"""HTTP request and response contracts for preparation briefs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.api.schemas.base import ResponseModel, StrictRequestModel
from app.domain.briefs.diagnostics import BriefWorkflowDiagnostics
from app.domain.briefs.models import (
    BriefWorkflowResult,
    ConversationQuestion,
    PreparationBrief,
    TimeBoxedAgendaItem,
)
from app.domain.briefs.types import BriefWorkflowOperation, BriefWorkflowTerminalState
from app.domain.meetings.types import MeetingPurpose, MeetingTone
from app.domain.shared.types import (
    EntityId,
    MeetingDurationMinutes,
    MeetingNotesText,
    MemoryBodyText,
    ObjectiveText,
    ShortTagText,
    UtcDatetime,
    VersionNumber,
)


class UserPreferencesInput(StrictRequestModel):
    """Optional coaching preference overrides supplied during brief generation."""

    preferred_question_count: Annotated[int, Field(ge=1, le=15)] | None = Field(
        default=None,
        description="Preferred number of suggested conversation questions (1 to 15).",
    )
    communication_style_notes: MemoryBodyText | None = Field(
        default=None,
        description="Personal communication style preferences.",
    )
    focus_areas: list[ShortTagText] | None = Field(
        default=None,
        max_length=10,
        description="Optional coaching focus tags.",
    )


class GenerateBriefRequest(StrictRequestModel):
    """Request payload for ``POST /api/v1/briefs/generate``."""

    contact_id: EntityId = Field(description="Target contact identifier.")
    purpose: MeetingPurpose = Field(description="Meeting archetype.")
    tone: MeetingTone = Field(
        default=MeetingTone.WARM_CASUAL,
        description="Desired conversation tone.",
    )
    meeting_objective: ObjectiveText = Field(
        description="Concrete goal for this conversation.",
    )
    duration_minutes: MeetingDurationMinutes = Field(
        description="Target meeting duration in minutes (5 to 180).",
    )
    scheduled_at: UtcDatetime | None = Field(
        default=None,
        description="Optional timezone-aware scheduled date/time (normalized to UTC).",
    )
    meeting_notes: MeetingNotesText | None = Field(
        default=None,
        description="Optional additional background context for this meeting.",
    )
    preferences: UserPreferencesInput | None = Field(
        default=None,
        description="Optional user preference overrides.",
    )


class ReviseBriefRequest(StrictRequestModel):
    """Request payload for ``POST /api/v1/briefs/{id}/revise``."""

    instructions: MemoryBodyText = Field(
        description="Natural-language revision instructions.",
    )
    expected_version: VersionNumber = Field(
        description="Current brief version expected by the caller for optimistic concurrency.",
    )
    duration_minutes: MeetingDurationMinutes | None = Field(
        default=None,
        description="Optional updated meeting duration in minutes.",
    )
    tone: MeetingTone | None = Field(
        default=None,
        description="Optional updated coaching tone.",
    )


class AgendaItemResponse(ResponseModel):
    """Serialized time-boxed agenda segment."""

    title: str = Field(description="Agenda segment title.")
    duration_minutes: int = Field(description="Minutes allocated to this segment.")
    description: str = Field(description="Segment focus and coaching guidance.")

    @classmethod
    def from_domain(cls, item: TimeBoxedAgendaItem) -> AgendaItemResponse:
        return cls(
            title=item.title,
            duration_minutes=item.duration_minutes,
            description=item.description,
        )


class ConversationQuestionResponse(ResponseModel):
    """Serialized ``ConversationQuestion`` pairing a question with its rationale."""

    id: str = Field(description="Unique question identifier within the brief.")
    question: str = Field(description="Suggested question phrasing.")
    rationale: str = Field(description="Why this question fits the meeting objective and context.")
    category: str | None = Field(default=None, description="Optional thematic category.")

    @classmethod
    def from_domain(cls, question: ConversationQuestion) -> ConversationQuestionResponse:
        return cls(
            id=question.id,
            question=question.question,
            rationale=question.rationale,
            category=question.category,
        )


class BriefWorkflowDiagnosticsResponse(ResponseModel):
    """Structured workflow execution metadata returned alongside preparation briefs."""

    request_id: str = Field(description="Request correlation identifier.")
    trace_id: str = Field(description="Distributed trace identifier.")
    operation: BriefWorkflowOperation = Field(
        description="Workflow operation ('generate' or 'revise').",
    )
    terminal_state: BriefWorkflowTerminalState = Field(
        description="Explicit workflow terminal state.",
    )
    attempt_count: int = Field(ge=0, description="Synthesis attempts executed (0 on replay).")
    regeneration_count: int = Field(
        ge=0,
        le=1,
        description="Corrective regenerations triggered (at most 1).",
    )
    model_invocations: int = Field(ge=0, description="Total LLM calls executed for this request.")
    tool_invocations: int = Field(ge=0, description="Total ADK tool calls executed.")
    replayed: bool = Field(description="True when served from idempotency deduplication store.")
    quality_passed: bool = Field(description="True when deterministic quality checks passed.")
    degraded_sources: list[str] = Field(
        default_factory=list,
        description="Optional context/tool sources that degraded gracefully.",
    )
    previous_version: int | None = Field(
        default=None,
        description="Prior brief version preserved in history before refinement.",
    )

    @classmethod
    def from_domain(
        cls,
        diagnostics: BriefWorkflowDiagnostics,
    ) -> BriefWorkflowDiagnosticsResponse:
        return cls(
            request_id=diagnostics.request_id,
            trace_id=diagnostics.trace_id,
            operation=diagnostics.operation,
            terminal_state=diagnostics.terminal_state,
            attempt_count=diagnostics.attempt_count,
            regeneration_count=diagnostics.regeneration_count,
            model_invocations=diagnostics.model_invocations,
            tool_invocations=diagnostics.tool_invocations,
            replayed=diagnostics.replayed,
            quality_passed=diagnostics.quality_passed,
            degraded_sources=list(diagnostics.degraded_sources),
            previous_version=diagnostics.previous_version,
        )


class PreparationBriefResponse(ResponseModel):
    """Serialized ``PreparationBrief`` returned by brief endpoints."""

    id: str = Field(description="Unique preparation brief identifier.")
    meeting_id: str = Field(description="Associated meeting identifier.")
    contact_id: str = Field(description="Associated contact identifier.")
    duration_minutes: int = Field(description="Total time-boxed duration in minutes.")
    tone: MeetingTone = Field(description="Tone applied to the brief.")
    contact_context: str = Field(description="Grounded summary of counterpart context.")
    meeting_objective: str = Field(description="Meeting objective.")
    conversation_openers: list[str] = Field(description="Tailored conversation openers.")
    time_boxed_agenda: list[AgendaItemResponse] = Field(
        description="Time-boxed agenda segments summing to duration_minutes.",
    )
    suggested_questions: list[ConversationQuestionResponse] = Field(
        description="Suggested questions and coaching rationales.",
    )
    suggested_follow_up_topics: list[str] = Field(
        description="Suggested follow-up topics and next steps.",
    )
    referenced_memory_ids: list[str] = Field(
        description="IDs of approved memories used to ground this brief.",
    )
    revision_summary: str | None = Field(
        default=None,
        description="Summary of the latest revision, when revised.",
    )
    version: int = Field(description="Optimistic concurrency version.")
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")
    workflow: BriefWorkflowDiagnosticsResponse | None = Field(
        default=None,
        description="Workflow execution diagnostics when produced by generate or revise.",
    )

    @classmethod
    def from_domain(
        cls,
        brief: PreparationBrief,
        *,
        diagnostics: BriefWorkflowDiagnostics | None = None,
    ) -> PreparationBriefResponse:
        return cls(
            id=brief.id,
            meeting_id=brief.meeting_id,
            contact_id=brief.contact_id,
            duration_minutes=brief.duration_minutes,
            tone=brief.tone,
            contact_context=brief.contact_context,
            meeting_objective=brief.meeting_objective,
            conversation_openers=list(brief.conversation_openers),
            time_boxed_agenda=[
                AgendaItemResponse.from_domain(item) for item in brief.time_boxed_agenda
            ],
            suggested_questions=[
                ConversationQuestionResponse.from_domain(q) for q in brief.suggested_questions
            ],
            suggested_follow_up_topics=list(brief.suggested_follow_up_topics),
            referenced_memory_ids=list(brief.referenced_memory_ids),
            revision_summary=brief.revision_summary,
            version=brief.version,
            created_at=brief.created_at,
            updated_at=brief.updated_at,
            workflow=(
                BriefWorkflowDiagnosticsResponse.from_domain(diagnostics)
                if diagnostics is not None
                else None
            ),
        )

    @classmethod
    def from_workflow_result(cls, result: BriefWorkflowResult) -> PreparationBriefResponse:
        return cls.from_domain(result.brief, diagnostics=result.diagnostics)


class BriefRevisionListResponse(ResponseModel):
    """Immutable revision history collection for ``GET /api/v1/briefs/{id}/revisions``."""

    items: list[PreparationBriefResponse] = Field(
        description="Ordered immutable revisions of the preparation brief.",
    )
    total: int = Field(ge=0, description="Total number of saved revisions.")
