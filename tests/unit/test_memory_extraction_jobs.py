"""Background memory extraction: the request returns before the model finishes."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.application.memory_jobs import STALLED_ERROR_CODE, MemoryExtractionJobService
from app.application.memory_persistence_service import MemoryPersistenceService
from app.config import AppSettings
from app.domain.errors import EntityNotFoundError, ModelTimeoutError
from app.domain.models import (
    AuthenticatedPrincipal,
    Contact,
    Meeting,
    Memory,
    MemoryExtractionJob,
)
from app.domain.ports import ProposedMemoryCandidate
from app.domain.types import MemoryExtractionJobStatus, MemoryScope, MemoryType
from app.fast_api_app import create_app
from app.infrastructure.background_jobs import InProcessBackgroundJobRunner
from app.infrastructure.fakes import FakeAuthenticator, FakeServiceContainer

ALICE = {"Authorization": "Bearer tok_alice"}
BOB = {"Authorization": "Bearer tok_bob"}
NOTES = "We discussed his team's challenges adopting AI. He recommended evaluation pipelines."
POLL_DEADLINE_SECONDS = 5.0


class GatedProposalAgent:
    """Extractor stand-in that blocks until the test releases it, or fails on demand."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self._failure = failure

    async def propose_memories(
        self,
        *,
        notes: str,
        meeting: Meeting | None,
        contact: Contact | None,
        existing_memories: Sequence[Memory],
    ) -> list[ProposedMemoryCandidate]:
        del notes, meeting, existing_memories
        self.calls += 1
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        if self._failure is not None:
            raise self._failure
        return [
            ProposedMemoryCandidate(
                scope=MemoryScope.CONTACT,
                contact_id=contact.id if contact is not None else None,
                memory_type=MemoryType.COUNTERPART_BACKGROUND,
                text="Alex discussed his team's challenges adopting AI.",
                rationale="Useful context for the next conversation.",
                excerpt="We discussed his team's challenges adopting AI",
            )
        ]


def _build_client(tmp_path: Path, agent: GatedProposalAgent) -> TestClient:
    container = FakeServiceContainer(
        authenticator=FakeAuthenticator(
            {
                "tok_alice": AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice"),
                "tok_bob": AuthenticatedPrincipal(user_id="usr_bob", display_name="Bob"),
            }
        )
    )
    container.proposal_agent = agent
    settings = AppSettings(
        environment="test",
        persistence_backend="in_memory",
        session_backend="in_memory",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    return TestClient(create_app(settings, service_container=container))


def _create_contact(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post("/api/v1/contacts", headers=headers, json={"name": "Alex Morgan"})
    assert resp.status_code == 201
    contact_id: str = resp.json()["id"]
    return contact_id


def _poll_until_terminal(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = datetime.now(UTC) + timedelta(seconds=POLL_DEADLINE_SECONDS)
    while datetime.now(UTC) < deadline:
        resp = client.get(f"/api/v1/memories/extraction-jobs/{job_id}", headers=ALICE)
        assert resp.status_code == 200
        body: dict[str, Any] = resp.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
    pytest.fail("Memory extraction job did not reach a terminal status in time.")


def test_job_is_accepted_while_extraction_is_still_running_then_stages_pending_proposals(
    tmp_path: Path,
) -> None:
    agent = GatedProposalAgent()
    with _build_client(tmp_path, agent) as client:
        contact_id = _create_contact(client, ALICE)

        accepted = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=ALICE,
            json={"notes": NOTES, "contact_id": contact_id},
        )

        # The response is back although the extractor has not been released yet.
        assert accepted.status_code == 202
        job = accepted.json()
        assert job["status"] in {"queued", "running"}
        assert job["result"] is None
        assert job["error"] is None
        assert job["completed_at"] is None
        assert accepted.headers["Location"] == f"/api/v1/memories/extraction-jobs/{job['id']}"
        assert agent.release.is_set() is False

        assert agent.started.wait(timeout=POLL_DEADLINE_SECONDS)
        in_flight = client.get(f"/api/v1/memories/extraction-jobs/{job['id']}", headers=ALICE)
        assert in_flight.json()["status"] == "running"
        assert client.get("/api/v1/memories/proposals", headers=ALICE).json()["total"] == 0

        agent.release.set()
        finished = _poll_until_terminal(client, job["id"])

        assert finished["status"] == "succeeded"
        assert finished["error"] is None
        assert finished["completed_at"] is not None
        assert finished["result"]["total"] == 1
        staged = finished["result"]["proposals"][0]
        assert staged["status"] == "pending"
        assert staged["contact_id"] == contact_id
        # Human-in-the-loop is unchanged: a finished job stages proposals, never memories.
        assert client.get("/api/v1/memories", headers=ALICE).json()["total"] == 0
        assert agent.calls == 1


def test_failed_extraction_is_reported_on_the_job_and_stages_nothing(tmp_path: Path) -> None:
    agent = GatedProposalAgent(failure=ModelTimeoutError("The memory extraction model timed out."))
    agent.release.set()
    with _build_client(tmp_path, agent) as client:
        contact_id = _create_contact(client, ALICE)
        accepted = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=ALICE,
            json={"notes": NOTES, "contact_id": contact_id},
        )
        assert accepted.status_code == 202

        finished = _poll_until_terminal(client, accepted.json()["id"])

        assert finished["status"] == "failed"
        assert finished["result"] is None
        assert finished["error"] == {
            "code": "MODEL_TIMEOUT",
            "message": "The memory extraction model timed out.",
        }
        assert client.get("/api/v1/memories/proposals", headers=ALICE).json()["total"] == 0


def test_reference_errors_are_rejected_before_any_job_or_model_call(tmp_path: Path) -> None:
    agent = GatedProposalAgent()
    agent.release.set()
    with _build_client(tmp_path, agent) as client:
        alice_contact_id = _create_contact(client, ALICE)

        unauthenticated = client.post("/api/v1/memories/extraction-jobs", json={"notes": NOTES})
        foreign = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=BOB,
            json={"notes": NOTES, "contact_id": alice_contact_id},
        )
        unknown = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=ALICE,
            json={"notes": NOTES, "contact_id": "cnt_does_not_exist"},
        )
        spoofed = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=ALICE,
            json={"notes": NOTES, "user_id": "usr_bob"},
        )

    assert unauthenticated.status_code == 401
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "FORBIDDEN"
    assert unknown.status_code == 404
    assert spoofed.status_code == 422
    assert agent.calls == 0


def test_a_job_is_visible_only_to_its_owner(tmp_path: Path) -> None:
    agent = GatedProposalAgent()
    agent.release.set()
    with _build_client(tmp_path, agent) as client:
        contact_id = _create_contact(client, ALICE)
        job_id = client.post(
            "/api/v1/memories/extraction-jobs",
            headers=ALICE,
            json={"notes": NOTES, "contact_id": contact_id},
        ).json()["id"]
        _poll_until_terminal(client, job_id)

        as_bob = client.get(f"/api/v1/memories/extraction-jobs/{job_id}", headers=BOB)
        missing = client.get("/api/v1/memories/extraction-jobs/mjob_missing", headers=ALICE)

    assert as_bob.status_code == 404
    assert missing.status_code == 404


def test_job_record_never_stores_the_raw_notes() -> None:
    assert "notes" not in MemoryExtractionJob.model_fields
    job = MemoryExtractionJob(
        id="mjob_1",
        owner_user_id="usr_alice",
        created_at=datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
    )
    assert NOTES not in job.model_dump_json()


class _ManualClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 25, 9, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        return self.current


def _job_service(
    container: FakeServiceContainer,
    clock: _ManualClock,
    runner: InProcessBackgroundJobRunner,
) -> MemoryExtractionJobService:
    return MemoryExtractionJobService(
        persistence=MemoryPersistenceService(
            preferences_repo=container.preferences_repo,
            proposal_repo=container.proposal_repo,
            memory_repo=container.memory_repo,
            contact_repo=container.contact_repo,
            meeting_repo=container.meeting_repo,
            brief_repo=container.brief_repo,
            proposal_agent=container.proposal_agent,
            clock=clock,
            id_generator=container.id_generator,
        ),
        job_repo=container.job_repo,
        proposal_repo=container.proposal_repo,
        job_runner=runner,
        clock=clock,
        id_generator=container.id_generator,
        stale_after_seconds=300.0,
    )


@pytest.mark.asyncio
async def test_a_job_abandoned_by_its_instance_is_closed_as_stalled_on_read() -> None:
    container = FakeServiceContainer()
    clock = _ManualClock()
    alice = AuthenticatedPrincipal(user_id="usr_alice")
    orphan = MemoryExtractionJob(
        id="mjob_orphan",
        owner_user_id=alice.user_id,
        status=MemoryExtractionJobStatus.RUNNING,
        created_at=clock.current,
        updated_at=clock.current,
    )
    await container.job_repo.save(orphan)
    service = _job_service(container, clock, InProcessBackgroundJobRunner())

    clock.current += timedelta(seconds=299)
    still_running = await service.get(principal=alice, job_id=orphan.id)
    clock.current += timedelta(seconds=2)
    stalled = await service.get(principal=alice, job_id=orphan.id)

    assert still_running.job.status is MemoryExtractionJobStatus.RUNNING
    assert stalled.job.status is MemoryExtractionJobStatus.FAILED
    assert stalled.job.error_code == STALLED_ERROR_CODE
    stored = await container.job_repo.get_for_owner(alice.user_id, orphan.id)
    assert stored is not None
    assert stored.status is MemoryExtractionJobStatus.FAILED
    with pytest.raises(EntityNotFoundError):
        await service.get(principal=AuthenticatedPrincipal(user_id="usr_bob"), job_id=orphan.id)


@pytest.mark.asyncio
async def test_runner_bounds_concurrency_and_survives_a_crashing_job() -> None:
    runner = InProcessBackgroundJobRunner(max_concurrency=2)
    running = 0
    peak = 0
    completed: list[int] = []

    def make_job(index: int) -> Any:
        async def _job() -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            if index == 1:
                msg = "boom"
                raise RuntimeError(msg)
            completed.append(index)

        return _job

    for index in range(5):
        runner.submit(make_job(index), name=f"test.job:{index}")
    assert runner.pending_count == 5

    await runner.drain(timeout_seconds=5.0)

    assert peak == 2
    assert sorted(completed) == [0, 2, 3, 4]
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_runner_drain_cancels_jobs_that_outlive_the_grace_period() -> None:
    runner = InProcessBackgroundJobRunner()
    cancelled = asyncio.Event()

    async def _never_finishes() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runner.submit(_never_finishes, name="test.job:slow")

    await runner.drain(timeout_seconds=0.05)

    assert cancelled.is_set()
    assert runner.pending_count == 0
