"""v1 routes for background memory-extraction jobs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.dependencies import (
    get_current_principal,
    get_memory_extraction_job_service,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    MemoryExtractionJobResponse,
    ProposeMemoriesRequest,
)
from app.application.memory.jobs import MemoryExtractionJobService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.types import EntityId

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


@router.post(
    "/memories/extraction-jobs",
    response_model=MemoryExtractionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["memories"],
    summary="Start background extraction of candidate memories",
)
async def start_memory_extraction_job(
    response: Response,
    payload: ProposeMemoriesRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    job_service: Annotated[MemoryExtractionJobService, Depends(get_memory_extraction_job_service)],
) -> MemoryExtractionJobResponse:
    """Accept notes, return at once, and extract candidate memories in the background.

    Ownership of the referenced contact, meeting and brief is checked before the job is
    accepted, so a wrong or foreign id is still rejected immediately. Poll
    ``GET /api/v1/memories/extraction-jobs/{id}`` for the result. Proposals are staged as
    ``pending`` and need explicit approval before they become memories.
    """
    job = await job_service.submit(
        principal=principal,
        notes=payload.notes,
        source_type=payload.source_type,
        meeting_id=payload.meeting_id,
        contact_id=payload.contact_id,
        brief_id=payload.brief_id,
    )
    response.headers["Location"] = f"/api/v1/memories/extraction-jobs/{job.id}"
    response.headers["Retry-After"] = "1"
    return MemoryExtractionJobResponse.from_domain(job, [])


@router.get(
    "/memories/extraction-jobs/{id}",
    response_model=MemoryExtractionJobResponse,
    status_code=status.HTTP_200_OK,
    tags=["memories"],
    summary="Poll a background memory-extraction job",
)
async def get_memory_extraction_job(
    id: Annotated[EntityId, Path(description="Memory-extraction job identifier.")],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    job_service: Annotated[MemoryExtractionJobService, Depends(get_memory_extraction_job_service)],
) -> MemoryExtractionJobResponse:
    """Return the job's status and, once it has succeeded, the pending proposals it staged."""
    view = await job_service.get(principal=principal, job_id=id)
    return MemoryExtractionJobResponse.from_domain(view.job, view.proposals)
