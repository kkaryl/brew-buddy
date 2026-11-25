"""HTTP response contracts for background memory-extraction jobs."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ResponseModel
from app.api.schemas.memories import MemoryProposalBatchResponse, MemoryProposalResponse
from app.domain.memory.jobs import MemoryExtractionJob
from app.domain.memory.models import MemoryProposal
from app.domain.memory.types import MemoryExtractionJobStatus


class MemoryExtractionJobErrorResponse(ResponseModel):
    """Client-safe reason a background memory-extraction job failed."""

    code: str = Field(description="Machine-readable failure code, for example 'MODEL_TIMEOUT'.")
    message: str = Field(description="Human-readable explanation safe to show the user.")


class MemoryExtractionJobResponse(ResponseModel):
    """State of a background memory-extraction job started from post-meeting notes."""

    id: str = Field(description="Unique memory-extraction job identifier.")
    status: MemoryExtractionJobStatus = Field(
        description="'queued', 'running', 'succeeded', or 'failed'.",
    )
    contact_id: str | None = Field(
        default=None,
        description="Contact the notes were submitted for, when one was given.",
    )
    meeting_id: str | None = Field(
        default=None,
        description="Meeting the notes were submitted for, when one was given.",
    )
    brief_id: str | None = Field(
        default=None,
        description="Preparation brief the notes were submitted for, when one was given.",
    )
    result: MemoryProposalBatchResponse | None = Field(
        default=None,
        description="Pending proposals staged for review. Present only when status is 'succeeded'.",
    )
    error: MemoryExtractionJobErrorResponse | None = Field(
        default=None,
        description="Failure reason. Present only when status is 'failed'.",
    )
    created_at: datetime = Field(description="UTC time the job was accepted.")
    updated_at: datetime = Field(description="UTC time of the last status change.")
    completed_at: datetime | None = Field(
        default=None,
        description="UTC time the job reached a terminal status.",
    )

    @classmethod
    def from_domain(
        cls,
        job: MemoryExtractionJob,
        proposals: list[MemoryProposal],
    ) -> MemoryExtractionJobResponse:
        """Serialize a job and, once it has succeeded, the proposals it staged."""
        result: MemoryProposalBatchResponse | None = None
        if job.status is MemoryExtractionJobStatus.SUCCEEDED:
            items = [MemoryProposalResponse.from_domain(proposal) for proposal in proposals]
            result = MemoryProposalBatchResponse(
                proposals=items,
                total=len(items),
                skipped_duplicates=job.skipped_duplicates,
                filtered_sensitive_count=job.filtered_sensitive_count,
            )
        error: MemoryExtractionJobErrorResponse | None = None
        if job.status is MemoryExtractionJobStatus.FAILED:
            error = MemoryExtractionJobErrorResponse(
                code=job.error_code or "INTERNAL_ERROR",
                message=job.error_message or "Memory extraction failed.",
            )
        return cls(
            id=job.id,
            status=job.status,
            contact_id=job.contact_id,
            meeting_id=job.meeting_id,
            brief_id=job.brief_id,
            result=result,
            error=error,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )
