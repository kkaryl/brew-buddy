"""Pydantic v2 HTTP request and response contracts for Brew API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    Contact,
    ConversationQuestion,
    Meeting,
    Memory,
    MemoryProposal,
    MemorySource,
    PreparationBrief,
    TimeBoxedAgendaItem,
)
from app.domain.types import (
    ConsentStatus,
    ContextSummaryText,
    EntityId,
    MeetingDurationMinutes,
    MeetingNotesText,
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryBodyText,
    MemoryScope,
    MemorySourceType,
    MemoryType,
    ObjectiveText,
    OrganizationNameText,
    ProposalStatus,
    RawSessionNotesText,
    ShortLabelText,
    ShortTagText,
    UtcDatetime,
    VersionNumber,
)


class _StrictRequestModel(BaseModel):
    """Base model forbidding unexpected or client-spoofed identity fields."""

    model_config = ConfigDict(extra="forbid")


class _ResponseModel(BaseModel):
    """Base model for serialized API responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorDetailItem(_ResponseModel):
    """Field-level validation or constraint failure detail."""

    field: str = Field(description="Dot-delimited request location of the offending input.")
    message: str = Field(description="Human-readable validation error explanation.")
    error_type: str = Field(description="Machine-readable validation category.")


class ErrorObject(_ResponseModel):
    """Structured error payload included in every error response."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Safe human-readable error message.")
    trace_id: str = Field(description="Request correlation or OpenTelemetry trace identifier.")
    details: list[ErrorDetailItem] = Field(
        default_factory=list,
        description="Optional field-level validation failures.",
    )


class ApiErrorResponse(_ResponseModel):
    """Canonical error envelope returned across all Brew API endpoints."""

    error: ErrorObject


class CreateContactRequest(_StrictRequestModel):
    """Request payload for ``POST /api/v1/contacts``."""

    name: ShortLabelText = Field(description="Counterpart full name.")
    title: ShortLabelText | None = Field(default=None, description="Counterpart job title.")
    role: ShortLabelText | None = Field(
        default=None,
        description="Counterpart functional role or relationship role.",
    )
    organization: OrganizationNameText | None = Field(
        default=None,
        description="Company, team, or organization.",
    )
    context_notes: ContextSummaryText | None = Field(
        default=None,
        description="Known background context or how you connected.",
    )


class ContactResponse(_ResponseModel):
    """Serialized representation of a ``Contact``."""

    id: str = Field(description="Unique contact identifier.")
    name: str = Field(description="Counterpart full name.")
    title: str | None = Field(default=None, description="Counterpart job title.")
    role: str | None = Field(default=None, description="Counterpart functional role.")
    organization: str | None = Field(default=None, description="Counterpart organization.")
    context_notes: str | None = Field(default=None, description="Background context notes.")
    version: int = Field(description="Optimistic concurrency version.")
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")

    @classmethod
    def from_domain(cls, contact: Contact) -> ContactResponse:
        return cls(
            id=contact.id,
            name=contact.name,
            title=contact.title,
            role=contact.role,
            organization=contact.organization,
            context_notes=contact.context_notes,
            version=contact.version,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )


class ContactListResponse(_ResponseModel):
    """Paginated/collection response for ``GET /api/v1/contacts``."""

    items: list[ContactResponse] = Field(description="Contacts owned by the authenticated user.")
    total: int = Field(ge=0, description="Total number of contacts returned.")


class MeetingResponse(_ResponseModel):
    """Serialized representation of a ``Meeting``."""

    id: str = Field(description="Unique meeting identifier.")
    contact_id: str = Field(description="Associated contact identifier.")
    purpose: MeetingPurpose = Field(description="Meeting archetype.")
    tone: MeetingTone = Field(description="Desired coaching and conversation tone.")
    objective: str = Field(description="Primary objective for the conversation.")
    duration_minutes: int = Field(description="Allocated meeting duration in minutes.")
    scheduled_at: datetime | None = Field(
        default=None,
        description="Optional scheduled UTC timestamp.",
    )
    notes: str | None = Field(default=None, description="Optional pre- or post-meeting notes.")
    status: MeetingStatus = Field(description="Current lifecycle status of the meeting.")
    latest_brief_id: str | None = Field(
        default=None,
        description="Identifier of the latest generated preparation brief.",
    )
    version: int = Field(description="Optimistic concurrency version.")
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")

    @classmethod
    def from_domain(cls, meeting: Meeting) -> MeetingResponse:
        return cls(
            id=meeting.id,
            contact_id=meeting.contact_id,
            purpose=meeting.purpose,
            tone=meeting.tone,
            objective=meeting.objective,
            duration_minutes=meeting.duration_minutes,
            scheduled_at=meeting.scheduled_at,
            notes=meeting.notes,
            status=meeting.status,
            latest_brief_id=meeting.latest_brief_id,
            version=meeting.version,
            created_at=meeting.created_at,
            updated_at=meeting.updated_at,
        )


class MeetingListResponse(_ResponseModel):
    """Collection response for ``GET /api/v1/meetings``."""

    items: list[MeetingResponse] = Field(description="Meetings owned by the authenticated user.")
    total: int = Field(ge=0, description="Total number of meetings returned.")


class UserPreferencesInput(_StrictRequestModel):
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


class GenerateBriefRequest(_StrictRequestModel):
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


class ReviseBriefRequest(_StrictRequestModel):
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


class AgendaItemResponse(_ResponseModel):
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


class ConversationQuestionResponse(_ResponseModel):
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


class PreparationBriefResponse(_ResponseModel):
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

    @classmethod
    def from_domain(cls, brief: PreparationBrief) -> PreparationBriefResponse:
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
        )


class MemorySourceResponse(_ResponseModel):
    """Serialized ``MemorySource`` provenance reference."""

    source_type: MemorySourceType = Field(description="Originating workflow stage.")
    meeting_id: str | None = Field(default=None, description="Originating meeting ID, if any.")
    brief_id: str | None = Field(default=None, description="Originating brief ID, if any.")
    proposal_id: str | None = Field(
        default=None,
        description="Originating memory proposal ID once approved.",
    )
    excerpt: str | None = Field(default=None, description="PII-scrubbed source excerpt.")
    recorded_at: datetime = Field(description="UTC timestamp when provenance was recorded.")

    @classmethod
    def from_domain(cls, source: MemorySource) -> MemorySourceResponse:
        return cls(
            source_type=source.source_type,
            meeting_id=source.meeting_id,
            brief_id=source.brief_id,
            proposal_id=source.proposal_id,
            excerpt=source.excerpt,
            recorded_at=source.recorded_at,
        )


class ProposeMemoriesRequest(_StrictRequestModel):
    """Request payload for ``POST /api/v1/memories/propose``."""

    notes: RawSessionNotesText = Field(
        description="Post-meeting notes or session reflections used to propose memories.",
    )
    source_type: MemorySourceType = Field(
        default=MemorySourceType.MEETING_NOTES,
        description="Provenance source type.",
    )
    meeting_id: EntityId | None = Field(
        default=None,
        description="Optional meeting ID associated with the notes.",
    )
    contact_id: EntityId | None = Field(
        default=None,
        description="Optional contact ID associated with the notes.",
    )
    brief_id: EntityId | None = Field(
        default=None,
        description="Optional preparation brief ID associated with the notes.",
    )


class MemoryProposalResponse(_ResponseModel):
    """Serialized ``MemoryProposal`` staged in the separate proposal store."""

    id: str = Field(description="Unique memory proposal identifier.")
    scope: MemoryScope = Field(description="Target memory scope.")
    contact_id: str | None = Field(
        default=None,
        description="Related contact ID when scope is 'contact'.",
    )
    memory_type: MemoryType = Field(description="Semantic classification of the memory.")
    text: str = Field(description="Proposed memory statement.")
    rationale: str = Field(description="Why Brew proposed saving this memory.")
    source: MemorySourceResponse = Field(description="Provenance reference.")
    status: ProposalStatus = Field(description="Current review status.")
    approved_memory_id: str | None = Field(
        default=None,
        description="ID of the approved Memory record once approved.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")
    reviewed_at: datetime | None = Field(
        default=None,
        description="UTC review timestamp once approved or rejected.",
    )
    version: int = Field(description="Optimistic concurrency version.")

    @classmethod
    def from_domain(cls, proposal: MemoryProposal) -> MemoryProposalResponse:
        return cls(
            id=proposal.id,
            scope=proposal.scope,
            contact_id=proposal.contact_id,
            memory_type=proposal.memory_type,
            text=proposal.text,
            rationale=proposal.rationale,
            source=MemorySourceResponse.from_domain(proposal.source),
            status=proposal.status,
            approved_memory_id=proposal.approved_memory_id,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            reviewed_at=proposal.reviewed_at,
            version=proposal.version,
        )


class MemoryProposalBatchResponse(_ResponseModel):
    """Response payload for ``POST /api/v1/memories/propose``."""

    proposals: list[MemoryProposalResponse] = Field(
        description="Candidate memory proposals awaiting explicit user approval.",
    )
    total: int = Field(ge=0, description="Number of proposals generated.")


class ApproveMemoryProposalRequest(_StrictRequestModel):
    """Request payload for ``POST /api/v1/memories/{id}/approve``."""

    expected_version: VersionNumber = Field(
        default=1,
        description="Expected version of the pending memory proposal.",
    )
    edited_text: MemoryBodyText | None = Field(
        default=None,
        description="Optional user-edited memory text to persist upon approval.",
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Optional overridden memory classification.",
    )


class UpdateMemoryRequest(_StrictRequestModel):
    """Request payload for ``PATCH /api/v1/memories/{id}``."""

    expected_version: VersionNumber = Field(
        description="Current memory version expected by caller for optimistic concurrency.",
    )
    text: MemoryBodyText | None = Field(
        default=None,
        description="Updated memory text.",
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Updated memory type.",
    )
    consent_status: ConsentStatus | None = Field(
        default=None,
        description="Updated user consent status (e.g. 'revoked').",
    )

    @model_validator(mode="after")
    def _ensure_at_least_one_patch_field(self) -> Self:
        if self.text is None and self.memory_type is None and self.consent_status is None:
            msg = "At least one of 'text', 'memory_type', or 'consent_status' must be provided."
            raise ValueError(msg)
        return self


class MemoryResponse(_ResponseModel):
    """Serialized user-approved ``Memory``."""

    id: str = Field(description="Unique approved memory identifier.")
    owner_user_id: str = Field(description="Authenticated owner user identifier.")
    scope: MemoryScope = Field(description="Scope ('user_preference' or 'contact').")
    contact_id: str | None = Field(
        default=None,
        description="Related contact ID when scope is 'contact'.",
    )
    memory_type: MemoryType = Field(description="Semantic memory type.")
    text: str = Field(description="Approved memory text.")
    source: MemorySourceResponse = Field(description="Provenance / source reference.")
    consent_status: ConsentStatus = Field(description="User consent status.")
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-updated timestamp.")
    version: int = Field(description="Optimistic concurrency version.")

    @classmethod
    def from_domain(cls, memory: Memory) -> MemoryResponse:
        return cls(
            id=memory.id,
            owner_user_id=memory.owner_user_id,
            scope=memory.scope,
            contact_id=memory.contact_id,
            memory_type=memory.memory_type,
            text=memory.text,
            source=MemorySourceResponse.from_domain(memory.source),
            consent_status=memory.consent_status,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            version=memory.version,
        )


class MemoryListResponse(_ResponseModel):
    """Collection response for ``GET /api/v1/memories``."""

    items: list[MemoryResponse] = Field(description="Approved memories matching query filters.")
    total: int = Field(ge=0, description="Total number of approved memories returned.")
