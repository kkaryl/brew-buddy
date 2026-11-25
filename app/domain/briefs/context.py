"""Bounded, provenance-aware context assembled before brief generation."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, model_validator

from app.domain.contacts.models import Contact
from app.domain.meetings.types import MeetingPurpose, MeetingStatus, MeetingTone
from app.domain.memory.models import (
    Memory,
    MemorySource,
    UserPreferences,
    validate_memory_scope_contact_binding,
)
from app.domain.memory.types import MemoryEpistemicStatus, MemoryScope, MemoryType
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.errors import DomainValidationError
from app.domain.shared.types import (
    EntityId,
    MeetingDurationMinutes,
    MemoryBodyText,
    ObjectiveText,
    SourceExcerptText,
    UtcDatetime,
)


class ContextBudget(ImmutableDomainModel):
    """Upper bounds enforced when assembling pre-brief context from durable storage."""

    max_recent_meetings: Annotated[int, Field(ge=1, le=20)] = 5
    max_contact_memories: Annotated[int, Field(ge=1, le=30)] = 8
    max_preference_memories: Annotated[int, Field(ge=1, le=20)] = 5
    max_total_chars: Annotated[int, Field(ge=200, le=32000)] = 4000


class RecentMeetingSummary(ImmutableDomainModel):
    """Bounded summary of a recent relevant meeting with the selected contact."""

    meeting_id: EntityId
    purpose: MeetingPurpose
    tone: MeetingTone
    objective: ObjectiveText
    duration_minutes: MeetingDurationMinutes
    scheduled_at: UtcDatetime | None = None
    status: MeetingStatus
    notes_excerpt: SourceExcerptText | None = None
    updated_at: UtcDatetime


class ProvenanceMemoryItem(ImmutableDomainModel):
    """Approved memory paired with explicit provenance for grounded brief synthesis."""

    memory_id: EntityId
    scope: MemoryScope
    contact_id: EntityId | None = None
    memory_type: MemoryType
    text: MemoryBodyText
    source: MemorySource
    epistemic_status: MemoryEpistemicStatus = MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_scope_binding(self) -> Self:
        validate_memory_scope_contact_binding(self.scope, self.contact_id)
        return self

    @classmethod
    def from_memory(cls, memory: Memory) -> ProvenanceMemoryItem:
        """Project a consented active ``Memory`` entity into a provenance-tagged context item."""
        if not memory.is_active:
            raise DomainValidationError(
                f"Cannot include inactive memory '{memory.id}' "
                f"(lifecycle_state='{memory.lifecycle_state.value}', "
                f"consent_status='{memory.consent_status.value}') in preparation context."
            )
        return cls(
            memory_id=memory.id,
            scope=memory.scope,
            contact_id=memory.contact_id,
            memory_type=memory.memory_type,
            text=memory.text,
            source=memory.source,
            epistemic_status=memory.epistemic_status,
            updated_at=memory.updated_at,
        )


class BriefPreparationContext(ImmutableDomainModel):
    """Bounded, provenance-aware context assembled prior to brief generation or revision."""

    owner_user_id: EntityId
    contact: Contact
    user_preferences: UserPreferences | None = None
    preference_memories: list[ProvenanceMemoryItem] = Field(default_factory=list)
    contact_memories: list[ProvenanceMemoryItem] = Field(default_factory=list)
    recent_meetings: list[RecentMeetingSummary] = Field(default_factory=list)
    budget: ContextBudget = Field(default_factory=ContextBudget)
    total_context_chars: Annotated[int, Field(ge=0)] = 0
    was_truncated: bool = False

    @model_validator(mode="after")
    def _validate_ownership_and_bounds(self) -> Self:
        if self.contact.owner_user_id != self.owner_user_id:
            msg = "Selected contact does not belong to context owner_user_id."
            raise ValueError(msg)

        if (
            self.user_preferences is not None
            and self.user_preferences.owner_user_id != self.owner_user_id
        ):
            msg = "User preferences do not belong to context owner_user_id."
            raise ValueError(msg)

        for pref_item in self.preference_memories:
            if pref_item.scope is not MemoryScope.USER_PREFERENCE:
                msg = "preference_memories may only contain 'user_preference' memories."
                raise ValueError(msg)

        for contact_item in self.contact_memories:
            if contact_item.scope is not MemoryScope.CONTACT:
                msg = "contact_memories may only contain 'contact' memories."
                raise ValueError(msg)
            if contact_item.contact_id != self.contact.id:
                msg = "contact_memories item contact_id does not match selected contact."
                raise ValueError(msg)

        if len(self.recent_meetings) > self.budget.max_recent_meetings:
            msg = "recent_meetings exceeds budget.max_recent_meetings."
            raise ValueError(msg)
        if len(self.contact_memories) > self.budget.max_contact_memories:
            msg = "contact_memories exceeds budget.max_contact_memories."
            raise ValueError(msg)
        if len(self.preference_memories) > self.budget.max_preference_memories:
            msg = "preference_memories exceeds budget.max_preference_memories."
            raise ValueError(msg)
        if self.total_context_chars > self.budget.max_total_chars:
            msg = "total_context_chars exceeds budget.max_total_chars."
            raise ValueError(msg)

        return self

    @property
    def referenced_memory_ids(self) -> list[str]:
        """Return ordered IDs of all approved memories included in this context."""
        return [
            *(item.memory_id for item in self.preference_memories),
            *(item.memory_id for item in self.contact_memories),
        ]
