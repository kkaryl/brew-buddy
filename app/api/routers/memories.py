"""v1 routes for memory proposals, human review, and approved memories."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Response, status

from app.api.dependencies import (
    get_current_principal,
    get_memory_service,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    ApproveMemoryProposalRequest,
    MemoryListResponse,
    MemoryProposalBatchResponse,
    MemoryProposalResponse,
    MemoryResponse,
    ProposeMemoriesRequest,
    RejectMemoryProposalRequest,
    UpdateMemoryRequest,
)
from app.application.memory.service import MemoryService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.memory.types import MemoryScope, MemoryType, ProposalStatus
from app.domain.shared.types import EntityId, VersionNumber

# POST /memories/propose is registered before the extraction-job routes and the rest of
# this module after them, so the module exposes two routers to keep that order.
proposal_intake_router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)
router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


@proposal_intake_router.post(
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
    batch = await memory_service.propose_memories_batch(
        principal=principal,
        notes=payload.notes,
        source_type=payload.source_type,
        meeting_id=payload.meeting_id,
        contact_id=payload.contact_id,
        brief_id=payload.brief_id,
    )
    items = [MemoryProposalResponse.from_domain(proposal) for proposal in batch.proposals]
    return MemoryProposalBatchResponse(
        proposals=items,
        total=len(items),
        skipped_duplicates=batch.skipped_duplicates,
        filtered_sensitive_count=batch.filtered_sensitive_count,
    )


@router.get(
    "/memories/proposals",
    response_model=MemoryProposalBatchResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="List memory proposals for human review",
)
async def list_memory_proposals(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    proposal_status: Annotated[
        ProposalStatus | None,
        Query(
            alias="status",
            description="Optional review status filter ('pending', 'approved', or 'rejected').",
        ),
    ] = None,
    contact_id: Annotated[
        EntityId | None,
        Query(description="Optional contact identifier filter."),
    ] = None,
) -> MemoryProposalBatchResponse:
    """Return candidate memory proposals staged for human review."""
    proposals = await memory_service.list_proposals(
        principal=principal,
        status=proposal_status,
        contact_id=contact_id,
    )
    items = [MemoryProposalResponse.from_domain(item) for item in proposals]
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
        Body(description="Optional version check, user-edited text, and supersede target."),
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
        supersedes_memory_id=resolved_payload.supersedes_memory_id,
    )
    return MemoryResponse.from_domain(approved)


@router.post(
    "/memories/{id}/reject",
    response_model=MemoryProposalResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="Reject a staged memory proposal",
)
async def reject_memory_proposal(
    id: Annotated[EntityId, Path(description="Memory proposal identifier to reject.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    payload: Annotated[
        RejectMemoryProposalRequest | None,
        Body(description="Optional version check and rejection reason."),
    ] = None,
) -> MemoryProposalResponse:
    """Reject a pending memory proposal so it is never persisted as an active memory."""
    resolved_payload = payload or RejectMemoryProposalRequest()
    rejected = await memory_service.reject_proposal(
        principal=principal,
        proposal_id=id,
        expected_version=resolved_payload.expected_version,
        reason=resolved_payload.reason,
    )
    return MemoryProposalResponse.from_domain(rejected)


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
    include_superseded: Annotated[
        bool,
        Query(description="Include historical memories superseded by newer updates."),
    ] = False,
) -> MemoryListResponse:
    """List approved memories owned by the authenticated caller."""
    memories = await memory_service.list_memories(
        principal=principal,
        scope=scope,
        contact_id=contact_id,
        memory_type=memory_type,
        include_revoked=include_revoked,
        include_superseded=include_superseded,
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
