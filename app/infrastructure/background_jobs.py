"""In-process background job runner.

Runs a coroutine on the serving event loop after the HTTP response has been returned. It
keeps a strong reference to every task (asyncio only holds weak ones), bounds how many run
at once, and never lets a job's exception escape.

Deployment note: on Cloud Run with request-based billing, CPU is throttled once a response
is sent, so background work only progresses while another request is in flight. Deploy with
CPU always allocated (``--no-cpu-throttling``) or move this port to a queue such as Cloud
Tasks. See ADR-022.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class InProcessBackgroundJobRunner:
    """Schedules jobs as asyncio tasks on the running loop, with bounded concurrency."""

    def __init__(self, *, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            msg = "max_concurrency must be at least 1."
            raise ValueError(msg)
        self._max_concurrency = max_concurrency
        self._tasks: set[asyncio.Task[None]] = set()
        # Created lazily: a semaphore binds to the loop that first awaits it.
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def pending_count(self) -> int:
        """Number of jobs that are queued or running."""
        return len(self._tasks)

    def submit(
        self,
        job: Callable[[], Awaitable[None]],
        *,
        name: str,
    ) -> None:
        """Schedule ``job`` on the running event loop and return immediately."""
        task = asyncio.get_running_loop().create_task(self._run_guarded(job, name), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_guarded(self, job: Callable[[], Awaitable[None]], name: str) -> None:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        async with self._semaphore:
            try:
                await job()
            except Exception:
                # Jobs are expected to record their own failure. This is the last line of
                # defence so one broken job cannot take down the loop or go unnoticed.
                logger.exception(
                    "Background job raised an unhandled exception",
                    extra={
                        "event_type": "background_job.unhandled_error",
                        "operation_name": name.split(":", 1)[0],
                        "result_status": "error",
                    },
                )

    async def drain(self, *, timeout_seconds: float) -> None:
        """Wait for in-flight jobs, then cancel whatever is still running at the deadline."""
        if not self._tasks:
            return
        pending_snapshot = set(self._tasks)
        _, still_running = await asyncio.wait(pending_snapshot, timeout=timeout_seconds)
        for task in still_running:
            task.cancel()
        if still_running:
            logger.warning(
                "Cancelled background jobs that did not finish before shutdown",
                extra={
                    "event_type": "background_job.cancelled_on_shutdown",
                    "operation_name": "background_job.drain",
                    "result_status": "error",
                },
            )
            await asyncio.gather(*still_running, return_exceptions=True)
