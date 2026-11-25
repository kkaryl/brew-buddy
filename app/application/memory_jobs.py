"""Background memory extraction: submit a job, return at once, let the client poll.

Extracting candidate memories calls a model, so it must not hold an HTTP request open.
``submit`` checks the caller's references up front (so a wrong or foreign id is still
rejected immediately), records a ``queued`` job, and hands the model call to a background
runner. The job only ever stages ``pending`` proposals. Approval stays a separate, explicit
user action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.application.memory_persistence_service import MemoryPersistenceService
from app.application.telemetry import ATTR_MEMORY_SAVED_COUNT, brew_span
from app.domain.errors import BrewDomainError, EntityNotFoundError
from app.domain.health import ClockPort
from app.domain.models import AuthenticatedPrincipal, MemoryExtractionJob, MemoryProposal
from app.domain.ports import (
    BackgroundJobRunnerPort,
    IdGeneratorPort,
    MemoryExtractionJobRepository,
    MemoryProposalRepository,
)
from app.domain.types import MemoryExtractionJobStatus, MemorySourceType

logger = logging.getLogger(__name__)

DEFAULT_STALE_AFTER_SECONDS = 300.0
STALLED_ERROR_CODE = "MEMORY_EXTRACTION_STALLED"
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class MemoryExtractionJobView:
    """A job together with the proposals it staged (empty until it succeeds)."""

    job: MemoryExtractionJob
    proposals: list[MemoryProposal]


class MemoryExtractionJobService:
    """Submits, runs and reports background memory-extraction jobs."""

    def __init__(
        self,
        *,
        persistence: MemoryPersistenceService,
        job_repo: MemoryExtractionJobRepository,
        proposal_repo: MemoryProposalRepository,
        job_runner: BackgroundJobRunnerPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self._persistence = persistence
        self._job_repo = job_repo
        self._proposal_repo = proposal_repo
        self._job_runner = job_runner
        self._clock = clock
        self._id_generator = id_generator
        self._stale_after = timedelta(seconds=stale_after_seconds)

    async def submit(
        self,
        *,
        principal: AuthenticatedPrincipal,
        notes: str,
        source_type: MemorySourceType = MemorySourceType.MEETING_NOTES,
        meeting_id: str | None = None,
        contact_id: str | None = None,
        brief_id: str | None = None,
    ) -> MemoryExtractionJob:
        """Validate references, record a queued job, and schedule extraction."""
        # Raises 403, 404 or 422 now, while the caller is still waiting on the request.
        await self._persistence.validate_proposal_references(
            principal=principal,
            meeting_id=meeting_id,
            contact_id=contact_id,
            brief_id=brief_id,
        )

        now = self._clock.now_utc()
        job = await self._job_repo.save(
            MemoryExtractionJob(
                id=self._id_generator.new_id("mjob"),
                owner_user_id=principal.user_id,
                source_type=source_type,
                contact_id=contact_id,
                meeting_id=meeting_id,
                brief_id=brief_id,
                created_at=now,
                updated_at=now,
            )
        )

        async def _run() -> None:
            await self._run_job(job=job, principal=principal, notes=notes)

        self._job_runner.submit(_run, name=f"memory.extract_job:{job.id}")
        logger.info(
            "Memory extraction job queued",
            extra={
                "event_type": "memory.extraction_job.queued",
                "operation_name": "memory.extract_job",
                "result_status": job.status.value,
            },
        )
        return job

    async def _run_job(
        self,
        *,
        job: MemoryExtractionJob,
        principal: AuthenticatedPrincipal,
        notes: str,
    ) -> None:
        with brew_span(
            "brew.memory.extract_job",
            operation_name="memory.extract_job",
            tracer_name=__name__,
        ) as tracker:
            running = await self._job_repo.save(job.mark_running(started_at=self._clock.now_utc()))
            try:
                batch = await self._persistence.propose_memories_batch(
                    principal=principal,
                    notes=notes,
                    source_type=job.source_type,
                    meeting_id=job.meeting_id,
                    contact_id=job.contact_id,
                    brief_id=job.brief_id,
                )
            except BrewDomainError as exc:
                finished = running.mark_failed(
                    error_code=exc.code,
                    error_message=exc.message,
                    completed_at=self._clock.now_utc(),
                )
                tracker.mark_error(exc.code, error_code=exc.code, error_type=type(exc).__name__)
            except Exception as exc:
                logger.exception(
                    "Memory extraction job failed unexpectedly",
                    extra={
                        "event_type": "memory.extraction_job.unexpected_error",
                        "operation_name": "memory.extract_job",
                        "result_status": "error",
                        "error_type": type(exc).__name__,
                    },
                )
                finished = running.mark_failed(
                    error_code=INTERNAL_ERROR_CODE,
                    error_message="Memory extraction failed unexpectedly. Please try again.",
                    completed_at=self._clock.now_utc(),
                )
                tracker.mark_error(
                    INTERNAL_ERROR_CODE,
                    error_code=INTERNAL_ERROR_CODE,
                    error_type=type(exc).__name__,
                )
            else:
                finished = running.mark_succeeded(
                    proposal_ids=[proposal.id for proposal in batch.proposals],
                    skipped_duplicates=batch.skipped_duplicates,
                    filtered_sensitive_count=batch.filtered_sensitive_count,
                    completed_at=self._clock.now_utc(),
                )
                tracker.set_attribute(ATTR_MEMORY_SAVED_COUNT, len(batch.proposals))

            await self._job_repo.save(finished)
            logger.info(
                "Memory extraction job finished",
                extra={
                    "event_type": "memory.extraction_job.finished",
                    "operation_name": "memory.extract_job",
                    "result_status": finished.status.value,
                    "error_code": finished.error_code,
                    "memory_saved_count": len(finished.proposal_ids),
                },
            )

    async def get(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: str,
    ) -> MemoryExtractionJobView:
        """Return the caller's job and, once it has succeeded, the proposals it staged."""
        uid = principal.user_id
        job = await self._job_repo.get_for_owner(uid, job_id)
        if job is None or job.owner_user_id != uid:
            raise EntityNotFoundError(entity_name="MemoryExtractionJob", entity_id=job_id)

        now = self._clock.now_utc()
        if not job.status.is_terminal and now - job.updated_at > self._stale_after:
            # The instance that owned the task is gone (restart, scale-in). Close the job
            # so the client gets a definite answer instead of polling forever.
            job = await self._job_repo.save(
                job.mark_failed(
                    error_code=STALLED_ERROR_CODE,
                    error_message=(
                        "Memory extraction did not finish. Please submit your notes again."
                    ),
                    completed_at=now,
                )
            )

        proposals: list[MemoryProposal] = []
        if job.status is MemoryExtractionJobStatus.SUCCEEDED:
            for proposal_id in job.proposal_ids:
                proposal = await self._proposal_repo.get_for_owner(uid, proposal_id)
                if proposal is not None and proposal.owner_user_id == uid:
                    proposals.append(proposal)
        return MemoryExtractionJobView(job=job, proposals=proposals)
