"""Minimal, PII-scrubbed read models returned to the coaching tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectedMemorySummary:
    """Minimal, PII-scrubbed approved memory projection safe for LLM context."""

    memory_id: str
    memory_type: str
    text: str


@dataclass(frozen=True, slots=True)
class UserPreferencesProjection:
    """Minimal projection of a user's coaching preferences and preference memories."""

    has_saved_preferences: bool
    default_tone: str | None
    default_duration_minutes: int | None
    preferred_question_count: int | None
    communication_style_notes: str | None
    focus_areas: list[str]
    approved_preference_memories: list[ProjectedMemorySummary]
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class ContactContextProjection:
    """Minimal projection of an owned contact profile and approved contact memories."""

    contact_id: str
    name: str
    title: str | None
    role: str | None
    organization: str | None
    context_notes: str | None
    approved_memories: list[ProjectedMemorySummary]
    has_prior_context: bool
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class ProjectedMeetingHistoryItem:
    """Minimal projection of a past or planned meeting with sanitized notes excerpt."""

    meeting_id: str
    contact_id: str
    purpose: str
    tone: str
    objective: str
    duration_minutes: int
    status: str
    scheduled_at_utc: str | None
    notes_excerpt: str | None


@dataclass(frozen=True, slots=True)
class MeetingHistoryProjection:
    """Bounded list of relevant meetings belonging to the authenticated caller."""

    meetings: list[ProjectedMeetingHistoryItem]
    total_returned: int
    was_truncated: bool
    injection_detected: bool


@dataclass(frozen=True, slots=True)
class StagedMemoryCandidateProjection:
    """Minimal summary of a staged ``pending`` memory proposal awaiting human review."""

    proposal_id: str
    scope: str
    contact_id: str | None
    memory_type: str
    text: str
    rationale: str


@dataclass(frozen=True, slots=True)
class SuggestedMemoryCandidatesProjection:
    """Result of extracting and staging candidate memories from untrusted notes."""

    candidates: list[StagedMemoryCandidateProjection]
    total_suggested: int
    filtered_untrusted_directives: int
