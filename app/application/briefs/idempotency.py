"""Idempotency for the brief workflow: per-key locking and replay of a recorded result."""

from __future__ import annotations

import asyncio
import logging

from app.domain.briefs.diagnostics import BriefWorkflowDiagnostics
from app.domain.briefs.models import BriefWorkflowResult
from app.domain.briefs.ports import BriefRepository, WorkflowIdempotencyRepository
from app.domain.briefs.types import BriefWorkflowOperation, BriefWorkflowTerminalState
from app.domain.meetings.ports import MeetingRepository
from app.domain.shared.errors import ConflictError

logger = logging.getLogger(__name__)


class WorkflowIdempotencyGuard:
    """Serializes requests sharing an idempotency key and replays an already recorded result."""

    def __init__(
        self,
        *,
        idempotency_repo: WorkflowIdempotencyRepository | None,
        brief_repo: BriefRepository,
        meeting_repo: MeetingRepository,
    ) -> None:
        self._idempotency_repo = idempotency_repo
        self._brief_repo = brief_repo
        self._meeting_repo = meeting_repo
        self._idempotency_locks: dict[str, asyncio.Lock] = {}

    def lock_for_idempotency_key(
        self,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
    ) -> asyncio.Lock:
        composite = f"{owner_user_id}:{operation.value}:{idempotency_key}"
        lock = self._idempotency_locks.get(composite)
        if lock is None:
            lock = asyncio.Lock()
            self._idempotency_locks[composite] = lock
        return lock

    async def try_replay_idempotent_result(
        self,
        *,
        owner_user_id: str,
        operation: BriefWorkflowOperation,
        idempotency_key: str,
        payload_fingerprint: str,
        request_id: str,
        trace_id: str,
    ) -> BriefWorkflowResult | None:
        if self._idempotency_repo is None:
            return None
        existing = await self._idempotency_repo.get(owner_user_id, operation, idempotency_key)
        if existing is None:
            return None
        if existing.payload_fingerprint != payload_fingerprint:
            raise ConflictError(
                f"Idempotency key '{idempotency_key}' was already used with a different "
                "meeting preparation request payload.",
                code="IDEMPOTENCY_KEY_CONFLICT",
            )

        replay_brief = await self._brief_repo.get_revision(
            owner_user_id,
            existing.brief_id,
            existing.brief_version,
        )
        if replay_brief is None:
            replay_brief = await self._brief_repo.get_for_owner(owner_user_id, existing.brief_id)
        replay_meeting = await self._meeting_repo.get_for_owner(owner_user_id, existing.meeting_id)
        if replay_brief is None or replay_meeting is None:
            return None

        previous_version = replay_brief.version - 1 if replay_brief.version > 1 else None
        diagnostics = BriefWorkflowDiagnostics(
            request_id=request_id,
            trace_id=trace_id,
            operation=operation,
            terminal_state=BriefWorkflowTerminalState.COMPLETED_IDEMPOTENT_REPLAY,
            attempt_count=0,
            regeneration_count=0,
            model_invocations=0,
            tool_invocations=0,
            replayed=True,
            quality_passed=True,
            degraded_sources=[],
            previous_version=previous_version,
        )
        logger.info(
            "Replayed deduplicated preparation brief workflow result",
            extra={
                "event_type": "workflow.brief.replayed",
                "request_id": request_id,
                "trace_id": trace_id,
            },
        )
        return BriefWorkflowResult(
            brief=replay_brief,
            meeting=replay_meeting,
            diagnostics=diagnostics,
        )
