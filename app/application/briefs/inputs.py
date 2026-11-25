"""Brief workflow input contracts, safeguard bounds and the request payload fingerprint."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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

MAX_ALLOWED_REGENERATIONS = 1


class BriefWorkflowSafeguardConfig(BaseModel):
    """Hard orchestration safeguard bounds enforced across every workflow execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_invocations: Annotated[int, Field(ge=1, le=12)] = 6
    max_corrective_regenerations: Annotated[int, Field(ge=0, le=MAX_ALLOWED_REGENERATIONS)] = 1
    max_tool_retries: Annotated[int, Field(ge=0, le=3)] = 1
    context_io_timeout_seconds: Annotated[float, Field(gt=0.0, le=60.0)] = 5.0


class GenerateWorkflowInput(BaseModel):
    """Strict Step-1 input contract for initial brief generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contact_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone
    meeting_objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    meeting_notes: MeetingNotesText | None = None
    preferred_question_count: Annotated[int, Field(ge=1, le=15)] | None = None
    communication_style_notes: MemoryBodyText | None = None
    focus_areas: list[ShortTagText] | None = Field(default=None, max_length=10)


class ReviseWorkflowInput(BaseModel):
    """Strict Step-1 input contract for brief refinement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    brief_id: EntityId
    instructions: MemoryBodyText
    expected_version: VersionNumber
    duration_minutes: MeetingDurationMinutes | None = None
    tone: MeetingTone | None = None


def compute_payload_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
