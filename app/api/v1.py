"""Async FastAPI v1 routes for Brew's preparation brief, contact, meeting, and memory APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request, Response, status

from app.api.dependencies import (
    get_brief_service,
    get_contact_service,
    get_current_principal,
    get_meeting_service,
    get_memory_service,
)
from app.api.errors import resolve_request_and_trace_ids
from app.api.schemas import (
    ApiErrorResponse,
    ApproveMemoryProposalRequest,
    BriefRevisionListResponse,
    ContactListResponse,
    ContactResponse,
    CreateContactRequest,
    GenerateBriefRequest,
    MeetingListResponse,
    MeetingResponse,
    MemoryListResponse,
    MemoryProposalBatchResponse,
    MemoryProposalResponse,
    MemoryResponse,
    PreparationBriefResponse,
    ProposeMemoriesRequest,
    ReviseBriefRequest,
    UpdateMemoryRequest,
)
from app.application.services import (
    BriefService,
    ContactService,
    MeetingService,
    MemoryService,
)
from app.domain.models import AuthenticatedPrincipal
from app.domain.types import EntityId, MemoryScope, MemoryType, VersionNumber

_STANDARD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ApiErrorResponse,
        "description": "Missing, malformed, or invalid Bearer authentication credentials.",
    },
    403: {
        "model": ApiErrorResponse,
        "description": "Authenticated user does not own the target resource.",
    },
    404: {
        "model": ApiErrorResponse,
        "description": "Requested resource does not exist.",
    },
    409: {
        "model": ApiErrorResponse,
        "description": "Optimistic concurrency version conflict or invalid lifecycle transition.",
    },
    422: {
        "model": ApiErrorResponse,
        "description": "Request schema, domain invariant, or model output validation failure.",
    },
    502: {
        "model": ApiErrorResponse,
        "description": "Coaching model execution or invocation budget failure.",
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Persistence backend unavailable.",
    },
    504: {
        "model": ApiErrorResponse,
        "description": "Coaching model request deadline exceeded.",
    },
}

router = APIRouter(
    prefix="/api/v1",
    responses=_STANDARD_ERROR_RESPONSES,
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


@router.post(
    "/memories/propose",
    response_model=MemoryProposalBatchResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["memories"],
    summary="Propose candidate memories from session notes",
)
async def propose_memories(
    payload: ProposeMemoriesRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryProposalBatchResponse:
    """Extract candidate memories and stage them separately from approved memories."""
    proposals = await memory_service.propose_memories(
        principal=principal,
        notes=payload.notes,
        source_type=payload.source_type,
        meeting_id=payload.meeting_id,
        contact_id=payload.contact_id,
        brief_id=payload.brief_id,
    )
    items = [MemoryProposalResponse.from_domain(proposal) for proposal in proposals]
    return MemoryProposalBatchResponse(proposals=items, total=len(items))


@router.post(
    "/memories/{id}/approve",
    response_model=MemoryResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="Approve a staged memory proposal",
)
async def approve_memory_proposal(
    id: Annotated[EntityId, Path(description="Memory proposal identifier to approve.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    payload: Annotated[
        ApproveMemoryProposalRequest | None,
        Body(description="Optional version check and user-edited text."),
    ] = None,
) -> MemoryResponse:
    """Promote a pending memory proposal into durable approved memory storage."""
    resolved_payload = payload or ApproveMemoryProposalRequest()
    approved = await memory_service.approve_proposal(
        principal=principal,
        proposal_id=id,
        expected_version=resolved_payload.expected_version,
        edited_text=resolved_payload.edited_text,
        memory_type=resolved_payload.memory_type,
    )
    return MemoryResponse.from_domain(approved)


@router.get(
    "/memories",
    response_model=MemoryListResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="List approved memories",
)
async def list_memories(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    scope: Annotated[
        MemoryScope | None,
        Query(description="Optional scope filter ('user_preference' or 'contact')."),
    ] = None,
    contact_id: Annotated[
        EntityId | None,
        Query(description="Optional contact identifier filter."),
    ] = None,
    memory_type: Annotated[
        MemoryType | None,
        Query(description="Optional memory classification filter."),
    ] = None,
    include_revoked: Annotated[
        bool,
        Query(description="Include memories whose consent_status was revoked."),
    ] = False,
) -> MemoryListResponse:
    """List approved memories owned by the authenticated caller."""
    memories = await memory_service.list_memories(
        principal=principal,
        scope=scope,
        contact_id=contact_id,
        memory_type=memory_type,
        include_revoked=include_revoked,
    )
    items = [MemoryResponse.from_domain(memory) for memory in memories]
    return MemoryListResponse(items=items, total=len(items))


@router.patch(
    "/memories/{id}",
    response_model=MemoryResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="Update an approved memory",
)
async def update_memory(
    id: Annotated[EntityId, Path(description="Approved memory identifier.")],
    payload: UpdateMemoryRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryResponse:
    """Modify an approved memory's text, type, or consent status with version checking."""
    updated = await memory_service.update_memory(
        principal=principal,
        memory_id=id,
        expected_version=payload.expected_version,
        text=payload.text,
        memory_type=payload.memory_type,
        consent_status=payload.consent_status,
    )
    return MemoryResponse.from_domain(updated)


@router.delete(
    "/memories/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["memories"],
    summary="Delete an approved memory",
)
async def delete_memory(
    id: Annotated[EntityId, Path(description="Approved memory identifier.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    expected_version: Annotated[
        VersionNumber | None,
        Query(description="Optional expected version for optimistic concurrency."),
    ] = None,
) -> Response:
    """Permanently delete an approved memory owned by the authenticated caller."""
    await memory_service.delete_memory(
        principal=principal,
        memory_id=id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
