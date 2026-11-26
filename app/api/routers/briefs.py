"""v1 routes for generating, revising and reading preparation briefs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.dependencies import (
    get_brief_service,
    get_current_principal,
)
from app.api.errors import resolve_request_and_trace_ids
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    BriefRevisionListResponse,
    GenerateBriefRequest,
    PreparationBriefResponse,
    ReviseBriefRequest,
)
from app.application.briefs.service import BriefService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.types import EntityId, VersionNumber

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


@router.post(
    "/briefs/generate",
    response_model=PreparationBriefResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["briefs"],
    summary="Generate a time-boxed preparation brief",
)
async def generate_brief(
    request: Request,
    response: Response,
    payload: GenerateBriefRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    brief_service: Annotated[BriefService, Depends(get_brief_service)],
    idempotency_key: Annotated[
        EntityId | None,
        Header(
            alias="Idempotency-Key",
            description="Optional caller deduplication key preventing duplicate brief generation.",
        ),
    ] = None,
) -> PreparationBriefResponse:
    """Create a meeting for an owned contact and synthesize a personalized preparation brief."""
    request_id, trace_id = resolve_request_and_trace_ids(request)
    prefs = payload.preferences
    result = await brief_service.generate_brief_workflow(
        principal=principal,
        contact_id=payload.contact_id,
        purpose=payload.purpose,
        tone=payload.tone,
        meeting_objective=payload.meeting_objective,
        duration_minutes=payload.duration_minutes,
        scheduled_at=payload.scheduled_at,
        meeting_notes=payload.meeting_notes,
        preferred_question_count=(prefs.preferred_question_count if prefs is not None else None),
        communication_style_notes=(prefs.communication_style_notes if prefs is not None else None),
        focus_areas=prefs.focus_areas if prefs is not None else None,
        idempotency_key=idempotency_key,
        request_id=request_id,
        trace_id=trace_id,
    )
    response.headers["X-Request-ID"] = result.diagnostics.request_id
    return PreparationBriefResponse.from_workflow_result(result)


@router.post(
    "/briefs/{id}/revise",
    response_model=PreparationBriefResponse,
    status_code=status.HTTP_200_OK,
    tags=["briefs"],
    summary="Revise an existing preparation brief",
)
async def revise_brief(
    request: Request,
    response: Response,
    id: Annotated[EntityId, Path(description="Preparation brief identifier.")],
    payload: ReviseBriefRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    brief_service: Annotated[BriefService, Depends(get_brief_service)],
    idempotency_key: Annotated[
        EntityId | None,
        Header(
            alias="Idempotency-Key",
            description="Optional caller deduplication key preventing duplicate brief revisions.",
        ),
    ] = None,
) -> PreparationBriefResponse:
    """Apply natural-language revision instructions with optimistic version checking."""
    request_id, trace_id = resolve_request_and_trace_ids(request)
    result = await brief_service.revise_brief_workflow(
        principal=principal,
        brief_id=id,
        instructions=payload.instructions,
        expected_version=payload.expected_version,
        duration_minutes=payload.duration_minutes,
        tone=payload.tone,
        idempotency_key=idempotency_key,
        request_id=request_id,
        trace_id=trace_id,
    )
    response.headers["X-Request-ID"] = result.diagnostics.request_id
    return PreparationBriefResponse.from_workflow_result(result)


@router.get(
    "/briefs/{id}/revisions",
    response_model=BriefRevisionListResponse,
    status_code=status.HTTP_200_OK,
    tags=["briefs"],
    summary="List immutable historical revisions of a preparation brief",
)
async def list_brief_revisions(
    id: Annotated[EntityId, Path(description="Preparation brief identifier.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    brief_service: Annotated[BriefService, Depends(get_brief_service)],
) -> BriefRevisionListResponse:
    """Return every saved revision snapshot of an owned preparation brief in version order."""
    revisions = await brief_service.list_brief_revisions(principal=principal, brief_id=id)
    items = [PreparationBriefResponse.from_domain(item) for item in revisions]
    return BriefRevisionListResponse(items=items, total=len(items))


@router.get(
    "/briefs/{id}",
    response_model=PreparationBriefResponse,
    status_code=status.HTTP_200_OK,
    tags=["briefs"],
    summary="Retrieve a preparation brief by ID",
)
async def get_brief(
    id: Annotated[EntityId, Path(description="Preparation brief identifier.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    brief_service: Annotated[BriefService, Depends(get_brief_service)],
) -> PreparationBriefResponse:
    """Return a preparation brief owned by the authenticated caller."""
    brief = await brief_service.get_brief(principal=principal, brief_id=id)
    return PreparationBriefResponse.from_domain(brief)


@router.delete(
    "/briefs/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["briefs"],
    summary="Delete a preparation brief and its revision snapshots",
)
async def delete_brief(
    id: Annotated[EntityId, Path(description="Preparation brief identifier.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    brief_service: Annotated[BriefService, Depends(get_brief_service)],
    expected_version: Annotated[
        VersionNumber | None,
        Query(description="Optional expected brief version for optimistic concurrency."),
    ] = None,
) -> Response:
    """Permanently delete a preparation brief owned by the authenticated caller."""
    await brief_service.delete_brief(
        principal=principal,
        brief_id=id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
