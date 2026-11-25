"""HTTP response contracts for meetings."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ResponseModel
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingPurpose, MeetingStatus, MeetingTone


class MeetingResponse(ResponseModel):
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


class MeetingListResponse(ResponseModel):
    """Collection response for ``GET /api/v1/meetings``."""

    items: list[MeetingResponse] = Field(description="Meetings owned by the authenticated user.")
    total: int = Field(ge=0, description="Total number of meetings returned.")
