"""In-memory memory extraction job repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.memory.jobs import MemoryExtractionJob


class InMemoryMemoryExtractionJobRepository:
    """Async fake repository mirroring ``users/{uid}/memoryJobs/{jobId}``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._jobs: dict[tuple[str, str], MemoryExtractionJob] = {}

    async def get_for_owner(
        self,
        owner_user_id: str,
        job_id: str,
    ) -> MemoryExtractionJob | None:
        async with self._lock:
            return self._jobs.get((owner_user_id, job_id))

    async def save(self, job: MemoryExtractionJob) -> MemoryExtractionJob:
        async with self._lock:
            self._jobs[(job.owner_user_id, job.id)] = job
            return job
