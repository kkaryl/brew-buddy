"""v1 routes for listing, creating, and deleting contacts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.dependencies import (
    get_contact_service,
    get_current_principal,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    ContactListResponse,
    ContactResponse,
    CreateContactRequest,
)
from app.application.contacts.service import ContactService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.types import EntityId, VersionNumber

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


@router.get(
    "/contacts",
    response_model=ContactListResponse,
    status_code=status.HTTP_200_OK,
    tags=["contacts"],
    summary="List contacts owned by the authenticated user",
)
async def list_contacts(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ContactListResponse:
    """List counterpart profiles created by the authenticated user."""
    contacts = await contact_service.list_contacts(principal=principal)
    items = [ContactResponse.from_domain(contact) for contact in contacts]
    return ContactListResponse(items=items, total=len(items))


@router.post(
    "/contacts",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["contacts"],
    summary="Create a new contact",
)
async def create_contact(
    payload: CreateContactRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ContactResponse:
    """Create a counterpart profile owned by the authenticated user."""
    contact = await contact_service.create_contact(
        principal=principal,
        name=payload.name,
        title=payload.title,
        role=payload.role,
        organization=payload.organization,
        context_notes=payload.context_notes,
    )
    return ContactResponse.from_domain(contact)


@router.delete(
    "/contacts/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["contacts"],
    summary="Delete a contact and their briefs, meetings, and memories",
)
async def delete_contact(
    id: Annotated[EntityId, Path(description="Contact identifier to delete.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
    expected_version: Annotated[
        VersionNumber | None,
        Query(description="Optional expected contact version for optimistic concurrency."),
    ] = None,
) -> Response:
    """Permanently delete a contact along with their briefs, meetings, and memories."""
    await contact_service.delete_contact(
        principal=principal,
        contact_id=id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
