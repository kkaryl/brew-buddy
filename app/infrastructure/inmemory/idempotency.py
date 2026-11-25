"""In-memory workflow idempotency record repository for local mode."""

from __future__ import annotations

import asyncio

from app.domain.briefs.models import WorkflowIdempotencyRecord
from app.domain.briefs.types import BriefWorkflowOperation


class InMemoryWorkflowIdempotencyRepository:
    """Async fake repository storing deduplication records per ``(owner, operation, key)``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._records: dict[tuple[str, str, str], WorkflowIdempotencyRecord] = {}

    async def get(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> WorkflowIdempotencyRecord | None:
        async with self._lock:
            return self._records.get((owner_user_id, operation.value, idempotency_key))

    async def save(
        self,
        record: WorkflowIdempotencyRecord,
    ) -> WorkflowIdempotencyRecord:
        async with self._lock:
            self._records[
                (record.owner_user_id, record.operation.value, record.idempotency_key)
            ] = record
            return record
