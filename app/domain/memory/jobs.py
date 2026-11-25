"""Background memory-extraction job record and its state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import Field, model_validator

from app.domain.memory.types import MemoryExtractionJobStatus, MemorySourceType
from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.errors import ConflictError
from app.domain.shared.types import EntityId, SourceExcerptText, UtcDatetime


class MemoryExtractionJob(ImmutableDomainModel):
    """Background extraction of candidate memories from one set of post-meeting notes.

    The raw notes are deliberately not part of this record. They live only in the memory of
    the running task, so a job document never stores unreviewed user text. The job points at
    the proposals it staged; those stay pending until the user reviews them.
    """

    id: EntityId
    owner_user_id: EntityId
    status: MemoryExtractionJobStatus = MemoryExtractionJobStatus.QUEUED
    source_type: MemorySourceType = MemorySourceType.MEETING_NOTES
    contact_id: EntityId | None = None
    meeting_id: EntityId | None = None
    brief_id: EntityId | None = None
    proposal_ids: list[EntityId] = Field(default_factory=list, max_length=50)
    skipped_duplicates: Annotated[int, Field(ge=0)] = 0
    filtered_sensitive_count: Annotated[int, Field(ge=0)] = 0
    error_code: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    error_message: SourceExcerptText | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate_job_invariants(self) -> Self:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at."
            raise ValueError(msg)
        if self.status.is_terminal and self.completed_at is None:
            msg = "Terminal jobs must record completed_at."
            raise ValueError(msg)
        if not self.status.is_terminal and self.completed_at is not None:
            msg = "Only terminal jobs may record completed_at."
            raise ValueError(msg)
        if self.status is MemoryExtractionJobStatus.FAILED and self.error_code is None:
            msg = "Failed jobs must record error_code."
            raise ValueError(msg)
        if self.status is not MemoryExtractionJobStatus.FAILED and (
            self.error_code is not None or self.error_message is not None
        ):
            msg = "Only failed jobs may record an error."
            raise ValueError(msg)
        if self.status is not MemoryExtractionJobStatus.SUCCEEDED and self.proposal_ids:
            msg = "Only succeeded jobs may reference staged proposals."
            raise ValueError(msg)
        return self

    def _require_not_terminal(self) -> None:
        if self.status.is_terminal:
            raise ConflictError(
                f"Memory extraction job '{self.id}' already finished as '{self.status.value}'.",
                code="MEMORY_EXTRACTION_JOB_FINISHED",
            )

    def mark_running(self, *, started_at: datetime) -> MemoryExtractionJob:
        """Transition a queued job to RUNNING."""
        self._require_not_terminal()
        return self.model_copy(
            update={
                "status": MemoryExtractionJobStatus.RUNNING,
                "updated_at": max(started_at, self.created_at),
            }
        )

    def mark_succeeded(
        self,
        *,
        proposal_ids: list[str],
        skipped_duplicates: int,
        filtered_sensitive_count: int,
        completed_at: datetime,
    ) -> MemoryExtractionJob:
        """Finish the job, recording which pending proposals it staged for review."""
        self._require_not_terminal()
        resolved_ts = max(completed_at, self.created_at)
        return MemoryExtractionJob.model_validate(
            {
                **self.model_dump(),
                "status": MemoryExtractionJobStatus.SUCCEEDED,
                "proposal_ids": proposal_ids,
                "skipped_duplicates": skipped_duplicates,
                "filtered_sensitive_count": filtered_sensitive_count,
                "updated_at": resolved_ts,
                "completed_at": resolved_ts,
            }
        )

    def mark_failed(
        self,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> MemoryExtractionJob:
        """Finish the job as FAILED with a client-safe error code and message."""
        self._require_not_terminal()
        resolved_ts = max(completed_at, self.created_at)
        return MemoryExtractionJob.model_validate(
            {
                **self.model_dump(),
                "status": MemoryExtractionJobStatus.FAILED,
                "error_code": error_code[:80],
                "error_message": error_message.strip()[:500] or "Memory extraction failed.",
                "updated_at": resolved_ts,
                "completed_at": resolved_ts,
            }
        )
