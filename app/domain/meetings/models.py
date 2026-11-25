"""Meeting entity: a planned conversation between a user and a contact."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from app.domain.meetings.types import MeetingPurpose, MeetingStatus, MeetingTone
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.types import (
    EntityId,
    MeetingDurationMinutes,
    MeetingNotesText,
    ObjectiveText,
    UtcDatetime,
    VersionNumber,
)


class Meeting(ImmutableDomainModel):
    """Scheduled or planned conversation between a user and a contact."""

    id: EntityId
    owner_user_id: EntityId
    contact_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone = MeetingTone.WARM_CASUAL
    objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    notes: MeetingNotesText | None = None
    status: MeetingStatus = MeetingStatus.PREPARING
    latest_brief_id: EntityId | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self
