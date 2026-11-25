"""Context-free ports: identifier generation and background job running."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class IdGeneratorPort(Protocol):
    """Port generating collision-resistant domain entity identifiers."""

    def new_id(self, prefix: str) -> str:
        """Return a fresh identifier prefixed with ``prefix``."""


class BackgroundJobRunnerPort(Protocol):
    """Port that runs a coroutine after the current request has returned."""

    def submit(
        self,
        job: Callable[[], Awaitable[None]],
        *,
        name: str,
    ) -> None:
        """Schedule job to run in the background. Must not block and must not raise."""

    async def drain(self, *, timeout_seconds: float) -> None:
        """Wait up to timeout_seconds for scheduled jobs to finish (used at shutdown)."""
