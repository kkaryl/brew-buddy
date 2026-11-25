"""HTTP request and response contracts for contacts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ResponseModel, StrictRequestModel
from app.domain.contacts.models import Contact
from app.domain.contacts.types import OrganizationNameText
from app.domain.shared.types import ContextSummaryText, ShortLabelText


class CreateContactRequest(StrictRequestModel):
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


class ContactResponse(ResponseModel):
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


class ContactListResponse(ResponseModel):
    """Paginated/collection response for ``GET /api/v1/contacts``."""

    items: list[ContactResponse] = Field(description="Contacts owned by the authenticated user.")
    total: int = Field(ge=0, description="Total number of contacts returned.")
