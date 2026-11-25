"""Contact entity: a counterpart profile owned by a Brew user."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from app.domain.contacts.types import OrganizationNameText
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.types import (
    ContextSummaryText,
    EntityId,
    ShortLabelText,
    UtcDatetime,
    VersionNumber,
)


class Contact(ImmutableDomainModel):
    """Counterpart profile owned by an authenticated Brew user."""

    id: EntityId
    owner_user_id: EntityId
    name: ShortLabelText
    title: ShortLabelText | None = None
    role: ShortLabelText | None = None
    organization: OrganizationNameText | None = None
    context_notes: ContextSummaryText | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: VersionNumber = 1

    @model_validator(mode="after")
    def _validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        return self
