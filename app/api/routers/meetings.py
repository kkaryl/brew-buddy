"""v1 route for listing meetings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_current_principal,
    get_meeting_service,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    MeetingListResponse,
    MeetingResponse,
)
from app.application.meetings.service import MeetingService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.types import EntityId

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


@router.get(
    "/meetings",
    response_model=MeetingListResponse,
    status_code=status.HTTP_200_OK,
    tags=["meetings"],
    summary="List meetings owned by the authenticated user",
)
async def list_meetings(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
    contact_id: Annotated[
        EntityId | None,
        Query(description="Optional contact identifier filter."),
    ] = None,
) -> MeetingListResponse:
    """List meetings belonging to the authenticated caller."""
    meetings = await meeting_service.list_meetings(
        principal=principal,
        contact_id=contact_id,
    )
    items = [MeetingResponse.from_domain(meeting) for meeting in meetings]
    return MeetingListResponse(items=items, total=len(items))
