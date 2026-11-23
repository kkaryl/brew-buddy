"""Firestore Emulator integration tests for repositories, user isolation, and ADK sessions."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.genai import types as genai_types
from pydantic import ConfigDict, PrivateAttr

from app.agent import build_adk_app, build_conversation_coach_agent
from app.application.memory_persistence_service import MemoryPersistenceService
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.application.services import BriefService, ContactService, MeetingService, MemoryService
from app.config import AppSettings
from app.domain.errors import (
    AuthorizationError,
    EntityNotFoundError,
    VersionConflictError,
)
from app.domain.models import AuthenticatedPrincipal, Meeting
from app.domain.types import (
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryEpistemicStatus,
    MemoryLifecycleState,
    ProposalStatus,
)
from app.fast_api_app import create_app
from app.infrastructure.adk_memory_extractor import AdkMemoryProposalAdapter
from app.infrastructure.container import build_firestore_service_container
from app.infrastructure.fakes import (
    FakeAuthenticator,
    FakeBriefCoachAgent,
    FakeMemoryProposalAgent,
    SequentialIdGenerator,
    UuidIdGenerator,
)
from app.infrastructure.firestore_repositories import (
    FirestoreBriefRepository,
    FirestoreContactRepository,
    FirestoreMeetingRepository,
    FirestoreMemoryProposalRepository,
    FirestoreMemoryRepository,
    FirestoreUserPreferencesRepository,
)
from app.infrastructure.session_service_factory import (
    SessionServiceFactory,
    create_adk_firestore_session_service,
    create_firestore_async_client,
)
from app.tools.coaching_tools import CoachingToolDependencies


class AdvancingEmulatorClock:
    """Deterministic UTC clock for Firestore emulator assertions."""

    def __init__(self) -> None:
        self._current = datetime(2026, 11, 22, 14, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        current = self._current
        self._current = self._current + timedelta(seconds=15)
        return current


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _locate_java_binary() -> str:
    preferred = Path("/usr/lib/jvm/java-25-openjdk-amd64/bin/java")
    if preferred.is_file() and os.access(preferred, os.X_OK):
        return str(preferred)
    resolved = shutil.which("java")
    if resolved:
        return resolved
    pytest.fail("Java runtime not found; required to run the Cloud Firestore Emulator.")


def _locate_firestore_emulator_jar() -> Path | None:
    env_jar = os.environ.get("FIRESTORE_EMULATOR_JAR")
    if env_jar and Path(env_jar).is_file():
        return Path(env_jar)

    home = Path.home()
    search_roots = [
        home / ".cache" / "firebase" / "emulators",
        Path("/usr/lib/google-cloud-sdk/platform/cloud-firestore-emulator"),
        Path("/tmp"),
    ]
    for root in search_roots:
        if not root.exists():
            continue
        matches = sorted(root.rglob("cloud-firestore-emulator*.jar"))
        if matches:
            return matches[-1]
    return None


def _wait_until_emulator_ready(
    host_port: str,
    proc: subprocess.Popen[str],
    log_path: Path,
) -> None:
    deadline = time.monotonic() + 30.0
    url = f"http://{host_port}/"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = log_path.read_text(encoding="utf-8", errors="replace")
            pytest.fail(
                f"Cloud Firestore Emulator exited prematurely ({proc.returncode}): {output}"
            )
        try:
            with urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except URLError:
            time.sleep(0.2)

    output = log_path.read_text(encoding="utf-8", errors="replace")
    pytest.fail(f"Timed out waiting for Cloud Firestore Emulator at {url}: {output}")


@pytest.fixture(scope="module")
def firestore_emulator_env(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[str, None, None]:
    """Ensure a live Cloud Firestore Emulator is running and configure environment vars."""
    preconfigured = os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip()
    if preconfigured:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "brew-emulator-test")
        yield preconfigured
        return

    jar_path = _locate_firestore_emulator_jar()
    if jar_path is None:
        pytest.fail(
            "Cloud Firestore Emulator is required for integration tests. Set "
            "FIRESTORE_EMULATOR_HOST or FIRESTORE_EMULATOR_JAR."
        )

    java_bin = _locate_java_binary()
    port = _find_free_local_port()
    host_port = f"127.0.0.1:{port}"
    log_path = tmp_path_factory.mktemp("firestore-emulator") / "emulator.log"

    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [
                java_bin,
                "-jar",
                str(jar_path),
                "--host=127.0.0.1",
                f"--port={port}",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    try:
        _wait_until_emulator_ready(host_port, proc, log_path)
        previous_host = os.environ.get("FIRESTORE_EMULATOR_HOST")
        previous_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        os.environ["FIRESTORE_EMULATOR_HOST"] = host_port
        os.environ["GOOGLE_CLOUD_PROJECT"] = "brew-emulator-test"
        try:
            yield host_port
        finally:
            if previous_host is None:
                os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
            else:
                os.environ["FIRESTORE_EMULATOR_HOST"] = previous_host
            if previous_project is None:
                os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            else:
                os.environ["GOOGLE_CLOUD_PROJECT"] = previous_project
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


@pytest.mark.asyncio
async def test_firestore_document_paths_optimistic_locking_and_multi_user_isolation(
    firestore_emulator_env: str,
) -> None:
    assert firestore_emulator_env
    raw_client = create_firestore_async_client(
        project="brew-emulator-paths",
        database="(default)",
    )
    with contextlib.closing(raw_client) as client:
        clock = AdvancingEmulatorClock()
        ids = SequentialIdGenerator()
        prefs_repo = FirestoreUserPreferencesRepository(client)
        contact_repo = FirestoreContactRepository(client)
        meeting_repo = FirestoreMeetingRepository(client)
        brief_repo = FirestoreBriefRepository(client)
        proposal_repo = FirestoreMemoryProposalRepository(client)
        memory_repo = FirestoreMemoryRepository(client)

        contact_service = ContactService(
            contact_repo=contact_repo,
            clock=clock,
            id_generator=ids,
        )
        meeting_service = MeetingService(
            meeting_repo=meeting_repo,
            contact_repo=contact_repo,
        )
        retrieval_service = MemoryRetrievalService(
            preferences_repo=prefs_repo,
            contact_repo=contact_repo,
            meeting_repo=meeting_repo,
            memory_repo=memory_repo,
        )
        persistence_service = MemoryPersistenceService(
            preferences_repo=prefs_repo,
            proposal_repo=proposal_repo,
            memory_repo=memory_repo,
            contact_repo=contact_repo,
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            proposal_agent=FakeMemoryProposalAgent(),
            clock=clock,
            id_generator=ids,
        )
        brief_service = BriefService(
            meeting_repo=meeting_repo,
            brief_repo=brief_repo,
            memory_retrieval=retrieval_service,
            memory_persistence=persistence_service,
            brief_agent=FakeBriefCoachAgent(),
            clock=clock,
            id_generator=ids,
        )

        alice = AuthenticatedPrincipal(user_id="uid_alice_fs")
        bob = AuthenticatedPrincipal(user_id="uid_bob_fs")

        # 1. Persist preferences -> users/{uid}/preferences/default
        saved_prefs = await persistence_service.upsert_user_preferences(
            principal=alice,
            preferred_question_count=4,
            communication_style_notes="Warm, concise coaching prompts.",
            focus_areas=["leadership", "architecture"],
        )
        raw_pref_snap = await client.document(f"users/{alice.user_id}/preferences/default").get()
        assert raw_pref_snap.exists
        raw_pref_dict = raw_pref_snap.to_dict()
        assert raw_pref_dict is not None
        assert raw_pref_dict["preferred_question_count"] == 4
        assert saved_prefs.version == 1

        # 2. Persist contact -> users/{uid}/contacts/{contactId}
        alice_contact = await contact_service.create_contact(
            principal=alice,
            name="Dr. Hannah Cho",
            title="Distinguished Engineer",
            organization="Aether Systems",
        )
        raw_contact_snap = await client.document(
            f"users/{alice.user_id}/contacts/{alice_contact.id}"
        ).get()
        assert raw_contact_snap.exists

        # 3. Generate brief -> users/{uid}/meetings/{meetingId} & users/{uid}/briefs/{briefId}
        brief_v1 = await brief_service.generate_brief(
            principal=alice,
            contact_id=alice_contact.id,
            purpose=MeetingPurpose.MENTORSHIP,
            tone=MeetingTone.WARM_CASUAL,
            meeting_objective="Discuss architecture review board practices.",
            duration_minutes=30,
        )
        raw_meeting_snap = await client.document(
            f"users/{alice.user_id}/meetings/{brief_v1.meeting_id}"
        ).get()
        raw_brief_snap = await client.document(f"users/{alice.user_id}/briefs/{brief_v1.id}").get()
        assert raw_meeting_snap.exists
        assert raw_brief_snap.exists

        # 4. Propose & approve -> users/{uid}/memoryProposals/{id} & memories/{id}
        proposals = await persistence_service.propose_memories(
            principal=alice,
            meeting_id=brief_v1.meeting_id,
            brief_id=brief_v1.id,
            notes=(
                "Hannah shares pre-read RFCs two days prior to architecture reviews. "
                "Follow up next month with our draft design doc."
            ),
        )
        assert len(proposals) == 2
        proposal_doc_snap = await client.document(
            f"users/{alice.user_id}/memoryProposals/{proposals[0].id}"
        ).get()
        assert proposal_doc_snap.exists
        proposal_doc_dict = proposal_doc_snap.to_dict()
        assert proposal_doc_dict is not None
        assert proposal_doc_dict["status"] == "pending"

        # Unapproved proposals do NOT exist in users/{uid}/memories
        assert await retrieval_service.list_memories(principal=alice) == []

        approved_mem = await persistence_service.approve_proposal(
            principal=alice,
            proposal_id=proposals[0].id,
            expected_version=1,
        )
        raw_mem_snap = await client.document(
            f"users/{alice.user_id}/memories/{approved_mem.id}"
        ).get()
        assert raw_mem_snap.exists
        raw_mem_dict = raw_mem_snap.to_dict()
        assert raw_mem_dict is not None
        assert raw_mem_dict["consent_status"] == "approved"

        # 5. Pre-brief retrieval loads preferences, contact, recent meeting, and approved memory
        assembled_ctx = await retrieval_service.build_brief_context(
            principal=alice,
            contact_id=alice_contact.id,
            purpose=MeetingPurpose.MENTORSHIP,
            objective="Prepare for architecture review follow-up.",
        )
        assert assembled_ctx.user_preferences is not None
        assert assembled_ctx.contact.id == alice_contact.id
        assert len(assembled_ctx.recent_meetings) == 1
        assert assembled_ctx.recent_meetings[0].meeting_id == brief_v1.meeting_id
        assert [m.memory_id for m in assembled_ctx.contact_memories] == [approved_mem.id]
        assert assembled_ctx.contact_memories[0].source.proposal_id == proposals[0].id

        # 6. Strict multi-tenant isolation for Bob against Firestore
        assert await contact_service.list_contacts(principal=bob) == []
        assert await meeting_service.list_meetings(principal=bob) == []
        assert await retrieval_service.list_memories(principal=bob) == []

        with pytest.raises(AuthorizationError):
            await brief_service.get_brief(principal=bob, brief_id=brief_v1.id)
        with pytest.raises(AuthorizationError):
            await retrieval_service.build_brief_context(
                principal=bob,
                contact_id=alice_contact.id,
            )
        with pytest.raises(AuthorizationError):
            await persistence_service.approve_proposal(
                principal=bob,
                proposal_id=proposals[1].id,
                expected_version=1,
            )
        with pytest.raises(AuthorizationError):
            await persistence_service.update_memory(
                principal=bob,
                memory_id=approved_mem.id,
                expected_version=1,
                text="Unauthorized write attempt.",
            )
        with pytest.raises(AuthorizationError):
            await persistence_service.delete_memory(
                principal=bob,
                memory_id=approved_mem.id,
            )

        # Non-existent IDs still raise EntityNotFoundError
        with pytest.raises(EntityNotFoundError):
            await brief_service.get_brief(principal=bob, brief_id="brf_nonexistent")

        # 7. Atomic Firestore transactional optimistic version checks
        updated_mem = await persistence_service.update_memory(
            principal=alice,
            memory_id=approved_mem.id,
            expected_version=1,
            text="Hannah shares 2-page pre-read RFCs 48h before reviews.",
        )
        assert updated_mem.version == 2

        with pytest.raises(VersionConflictError):
            await persistence_service.update_memory(
                principal=alice,
                memory_id=approved_mem.id,
                expected_version=1,
                text="Stale version write must fail in Firestore transaction.",
            )

        with pytest.raises(VersionConflictError):
            await persistence_service.delete_memory(
                principal=alice,
                memory_id=approved_mem.id,
                expected_version=1,
            )

        await persistence_service.delete_memory(
            principal=alice,
            memory_id=approved_mem.id,
            expected_version=2,
        )
        deleted_snap = await client.document(
            f"users/{alice.user_id}/memories/{approved_mem.id}"
        ).get()
        assert not deleted_snap.exists


@pytest.mark.asyncio
async def test_adk_firestore_session_service_persists_events_separately_from_domain_collections(
    firestore_emulator_env: str,
) -> None:
    assert firestore_emulator_env
    raw_client = create_firestore_async_client(
        project="brew-emulator-sessions",
        database="(default)",
    )
    with contextlib.closing(raw_client) as client:
        settings = AppSettings(
            environment="test",
            google_cloud_project="brew-emulator-sessions",
            persistence_backend="firestore",
            session_backend="firestore",
            adk_firestore_root_collection="adk-session",
            otel_to_cloud=False,
        )
        session_service = SessionServiceFactory(
            settings=settings,
            firestore_client=client,
        ).create()
        assert session_service.__class__.__name__ == "FirestoreSessionService"

        created_session = await session_service.create_session(
            app_name="brew",
            user_id="uid_session_alice",
            session_id="sess_001",
            state={"active_step": "brief_refinement", "user:theme": "warm"},
        )
        assert created_session.id == "sess_001"

        turn_event = Event(
            author="user",
            invocation_id="inv_001",
            content=genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text="Make the opener less formal.")],
            ),
            actions=EventActions(state_delta={"active_step": "brief_revised"}),
        )
        await session_service.append_event(created_session, turn_event)

        # Reload via a second FirestoreSessionService instance to prove durable persistence
        reloaded_service = create_adk_firestore_session_service(
            client=client,
            root_collection="adk-session",
        )
        reloaded = await reloaded_service.get_session(
            app_name="brew",
            user_id="uid_session_alice",
            session_id="sess_001",
        )
        assert reloaded is not None
        assert reloaded.state["active_step"] == "brief_revised"
        assert reloaded.state["user:theme"] == "warm"
        assert len(reloaded.events) == 1
        first_content = reloaded.events[0].content
        assert first_content is not None
        assert first_content.parts is not None
        assert first_content.parts[0].text == "Make the opener less formal."

        # Confirm ADK session writes did NOT create any documents under domain `users/{uid}/...`
        domain_memories = await (
            client.collection("users").document("uid_session_alice").collection("memories").get()
        )
        domain_proposals = await (
            client.collection("users")
            .document("uid_session_alice")
            .collection("memoryProposals")
            .get()
        )
        assert len(domain_memories) == 0
        assert len(domain_proposals) == 0


def test_fastapi_v1_endpoints_end_to_end_against_firestore_emulator(
    firestore_emulator_env: str,
    tmp_path: Path,
) -> None:
    assert firestore_emulator_env
    settings = AppSettings(
        environment="test",
        google_cloud_project="brew-emulator-http",
        persistence_backend="firestore",
        session_backend="firestore",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "missing-dist",
    )
    auth = FakeAuthenticator(
        {
            "fs-alice-token": AuthenticatedPrincipal(user_id="uid_http_alice"),
            "fs-bob-token": AuthenticatedPrincipal(user_id="uid_http_bob"),
        }
    )
    container = build_firestore_service_container(
        settings,
        clock=AdvancingEmulatorClock(),
        authenticator=auth,
    )
    fastapi_app = create_app(settings, service_container=container)

    alice_headers = {"Authorization": "Bearer fs-alice-token"}
    bob_headers = {"Authorization": "Bearer fs-bob-token"}

    with TestClient(fastapi_app) as client:
        contact_resp = client.post(
            "/api/v1/contacts",
            headers=alice_headers,
            json={"name": "Devon Brooks", "organization": "CloudScale"},
        )
        assert contact_resp.status_code == 201
        contact_id = contact_resp.json()["id"]

        brief_1 = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": contact_id,
                "purpose": "coffee_chat",
                "meeting_objective": "Get to know Devon's reliability engineering priorities.",
                "duration_minutes": 20,
            },
        ).json()

        propose_resp = client.post(
            "/api/v1/memories/propose",
            headers=alice_headers,
            json={
                "notes": "Devon is leading SLO automation across all core services.",
                "meeting_id": brief_1["meeting_id"],
            },
        )
        assert propose_resp.status_code == 201
        proposal_id = propose_resp.json()["proposals"][0]["id"]

        # Bob is blocked from approving Alice's Firestore proposal
        assert (
            client.post(
                f"/api/v1/memories/{proposal_id}/approve",
                headers=bob_headers,
                json={"expected_version": 1},
            ).status_code
            == 403
        )

        approve_resp = client.post(
            f"/api/v1/memories/{proposal_id}/approve",
            headers=alice_headers,
            json={"expected_version": 1},
        )
        assert approve_resp.status_code == 200
        memory_id = approve_resp.json()["id"]

        # Generating a second brief in a later session recalls the Firestore-persisted memory
        brief_2 = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": contact_id,
                "purpose": "coffee_chat",
                "meeting_objective": "Follow up on SLO automation rollout.",
                "duration_minutes": 25,
            },
        )
        assert brief_2.status_code == 201
        assert memory_id in brief_2.json()["referenced_memory_ids"]


class _ScriptedEmulatorLlm(BaseLlm):
    """Deterministic ADK ``BaseLlm`` for real Firestore multi-session integration testing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _responses: list[LlmResponse] = PrivateAttr(default_factory=list)
    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(self, responses: list[LlmResponse]) -> None:
        super().__init__(model="emulator-scripted-gemini")
        self._responses = list(responses)
        self._requests = []

    @property
    def requests(self) -> list[LlmRequest]:
        return self._requests

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        self._requests.append(llm_request.model_copy(deep=True))
        yield self._responses.pop(0)


@pytest.mark.asyncio
async def test_real_cross_session_memory_lifecycle_with_distinct_firestore_sessions(
    firestore_emulator_env: str,
) -> None:
    """Verify full long-term memory lifecycle across two distinct ADK session IDs in Firestore.

    Uses two completely independent ``FirestoreAsyncClient`` and ``FirestoreSessionService``
    instances (closing Session 1's client before opening Session 2's client) so zero state is
    shared through in-memory Python dictionaries.
    """
    assert firestore_emulator_env
    project_id = "brew-cross-session-memory-lifecycle"
    session_id_1 = "ses_alex_coffee_chat_001"
    session_id_2 = "ses_alex_followup_002"
    assert session_id_1 != session_id_2

    alice = AuthenticatedPrincipal(user_id="uid_cross_session_alice", display_name="Alice")
    shared_clock = AdvancingEmulatorClock()

    # =========================================================================
    # SESSION 1: Meet Alex, submit notes, review proposals (approve 2, reject 1)
    # =========================================================================
    raw_client_1 = create_firestore_async_client(project=project_id, database="(default)")
    with contextlib.closing(raw_client_1) as client_1:
        ids_1 = UuidIdGenerator()
        prefs_repo_1 = FirestoreUserPreferencesRepository(client_1)
        contact_repo_1 = FirestoreContactRepository(client_1)
        meeting_repo_1 = FirestoreMeetingRepository(client_1)
        brief_repo_1 = FirestoreBriefRepository(client_1)
        proposal_repo_1 = FirestoreMemoryProposalRepository(client_1)
        memory_repo_1 = FirestoreMemoryRepository(client_1)

        contact_svc_1 = ContactService(
            contact_repo=contact_repo_1,
            clock=shared_clock,
            id_generator=ids_1,
        )
        alex = await contact_svc_1.create_contact(
            principal=alice,
            name="Alex",
            title="Staff ML Engineer",
            organization="Kestrel AI",
        )
        alex_id = alex.id

        t_mtg = shared_clock.now_utc()
        meeting_1 = await meeting_repo_1.save(
            Meeting(
                id="mtg_alex_session_1",
                owner_user_id=alice.user_id,
                contact_id=alex_id,
                purpose=MeetingPurpose.COFFEE_CHAT,
                tone=MeetingTone.WARM_CASUAL,
                objective="Discuss ML evaluation practices with Alex.",
                duration_minutes=30,
                status=MeetingStatus.COMPLETED,
                created_at=t_mtg,
                updated_at=t_mtg,
            )
        )

        extractor_llm_1 = _ScriptedEmulatorLlm(
            [
                LlmResponse(
                    content=genai_types.Content(
                        role="model",
                        parts=[
                            genai_types.Part.from_text(
                                text=json.dumps(
                                    {
                                        "candidates": [
                                            {
                                                "scope": "contact",
                                                "contact_id": alex_id,
                                                "memory_type": "counterpart_background",
                                                "text": (
                                                    "Alex discussed his team's challenges "
                                                    "adopting AI."
                                                ),
                                                "rationale": (
                                                    "Grounds follow-up discussion on AI "
                                                    "adoption hurdles."
                                                ),
                                                "excerpt": (
                                                    "We discussed his team's challenges adopting AI"
                                                ),
                                                "supersedes_memory_id": None,
                                            },
                                            {
                                                "scope": "contact",
                                                "contact_id": alex_id,
                                                "memory_type": "follow_up_commitment",
                                                "text": (
                                                    "Alex recommended exploring evaluation "
                                                    "pipelines."
                                                ),
                                                "rationale": (
                                                    "Tracks Alex's learning recommendation."
                                                ),
                                                "excerpt": (
                                                    "He recommended learning more about "
                                                    "evaluation pipelines"
                                                ),
                                                "supersedes_memory_id": None,
                                            },
                                            {
                                                "scope": "user_preference",
                                                "contact_id": None,
                                                "memory_type": "communication_preference",
                                                "text": (
                                                    "Prefers having informal conversations "
                                                    "with engineers."
                                                ),
                                                "rationale": (
                                                    "Shapes tone for future engineering "
                                                    "coffee chats."
                                                ),
                                                "excerpt": (
                                                    "I prefer having informal conversations "
                                                    "with engineers"
                                                ),
                                                "supersedes_memory_id": None,
                                            },
                                        ]
                                    }
                                )
                            )
                        ],
                    )
                )
            ]
        )
        settings_1 = AppSettings(
            environment="test",
            persistence_backend="firestore",
            session_backend="firestore",
            google_cloud_project=project_id,
            adk_firestore_root_collection="adk-session-lifecycle",
            otel_to_cloud=False,
        )
        extractor_1 = AdkMemoryProposalAdapter(
            settings=settings_1,
            model_override=extractor_llm_1,
        )
        retrieval_1 = MemoryRetrievalService(
            preferences_repo=prefs_repo_1,
            contact_repo=contact_repo_1,
            meeting_repo=meeting_repo_1,
            memory_repo=memory_repo_1,
        )
        persistence_1 = MemoryPersistenceService(
            preferences_repo=prefs_repo_1,
            proposal_repo=proposal_repo_1,
            memory_repo=memory_repo_1,
            contact_repo=contact_repo_1,
            meeting_repo=meeting_repo_1,
            brief_repo=brief_repo_1,
            proposal_agent=extractor_1,
            clock=shared_clock,
            id_generator=ids_1,
        )
        memory_svc_1 = MemoryService(retrieval=retrieval_1, persistence=persistence_1)

        # Persist Session 1 in ADK FirestoreSessionService
        session_svc_1 = create_adk_firestore_session_service(
            client=client_1,
            project=project_id,
            root_collection=settings_1.adk_firestore_root_collection,
        )
        created_ses_1 = await session_svc_1.create_session(
            app_name="app",
            user_id=alice.user_id,
            session_id=session_id_1,
            state={"active_contact_id": alex_id},
        )
        assert created_ses_1.id == session_id_1

        # Submit exact user scenario notes
        scenario_notes = (
            "We discussed his team's challenges adopting AI. "
            "He recommended learning more about evaluation pipelines. "
            "I prefer having informal conversations with engineers."
        )
        staged = await memory_svc_1.propose_memories_batch(
            principal=alice,
            notes=scenario_notes,
            meeting_id=meeting_1.id,
        )
        assert len(staged.proposals) == 3
        p_ai, p_eval, p_pref = staged.proposals
        assert p_ai.lifecycle_state is MemoryLifecycleState.PROPOSED
        assert p_eval.lifecycle_state is MemoryLifecycleState.PROPOSED
        assert p_pref.lifecycle_state is MemoryLifecycleState.PROPOSED

        # Verify zero automatic writes occurred in Firestore `memories` before human review
        assert await memory_svc_1.list_memories(principal=alice) == []

        # Human review: approve p_ai & p_pref, reject p_eval
        approved_ai_mem = await memory_svc_1.approve_proposal(
            principal=alice,
            proposal_id=p_ai.id,
            expected_version=1,
        )
        rejected_eval_prop = await memory_svc_1.reject_proposal(
            principal=alice,
            proposal_id=p_eval.id,
            expected_version=1,
            reason="Do not save evaluation pipelines note yet.",
        )
        approved_pref_mem = await memory_svc_1.approve_proposal(
            principal=alice,
            proposal_id=p_pref.id,
            expected_version=1,
        )
        approved_ai_id = approved_ai_mem.id
        approved_pref_id = approved_pref_mem.id
        rejected_prop_id = rejected_eval_prop.id
        assert rejected_eval_prop.status is ProposalStatus.REJECTED

    # =========================================================================
    # SESSION 2: Fresh Firestore client + distinct ADK session_id_2 recalls only
    # approved memories, resolves contradiction (SUPERSEDED), and deletes cleanly
    # =========================================================================
    raw_client_2 = create_firestore_async_client(project=project_id, database="(default)")
    with contextlib.closing(raw_client_2) as client_2:
        ids_2 = UuidIdGenerator()
        prefs_repo_2 = FirestoreUserPreferencesRepository(client_2)
        contact_repo_2 = FirestoreContactRepository(client_2)
        meeting_repo_2 = FirestoreMeetingRepository(client_2)
        brief_repo_2 = FirestoreBriefRepository(client_2)
        proposal_repo_2 = FirestoreMemoryProposalRepository(client_2)
        memory_repo_2 = FirestoreMemoryRepository(client_2)

        settings_2 = AppSettings(
            environment="test",
            persistence_backend="firestore",
            session_backend="firestore",
            google_cloud_project=project_id,
            adk_firestore_root_collection="adk-session-lifecycle",
            otel_to_cloud=False,
        )
        session_svc_2 = create_adk_firestore_session_service(
            client=client_2,
            project=project_id,
            root_collection=settings_2.adk_firestore_root_collection,
        )
        # Verify Session 1 was persisted in Firestore, and create distinct Session 2
        persisted_ses_1 = await session_svc_2.get_session(
            app_name="app",
            user_id=alice.user_id,
            session_id=session_id_1,
        )
        assert persisted_ses_1 is not None
        assert persisted_ses_1.id == session_id_1

        created_ses_2 = await session_svc_2.create_session(
            app_name="app",
            user_id=alice.user_id,
            session_id=session_id_2,
        )
        assert created_ses_2.id == session_id_2
        assert created_ses_2.id != persisted_ses_1.id

        # Run ADK `conversation_coach` on session_id_2 calling real tools against Firestore
        coach_llm_2 = _ScriptedEmulatorLlm(
            [
                LlmResponse(
                    content=genai_types.Content(
                        role="model",
                        parts=[
                            genai_types.Part(
                                function_call=genai_types.FunctionCall(
                                    id="fc_ses2_prefs",
                                    name="get_user_preferences",
                                    args={"max_preference_memories": 5},
                                )
                            ),
                            genai_types.Part(
                                function_call=genai_types.FunctionCall(
                                    id="fc_ses2_contact",
                                    name="get_contact_context",
                                    args={"contact_id": alex_id, "max_memories": 5},
                                )
                            ),
                        ],
                    )
                ),
                LlmResponse(
                    content=genai_types.Content(
                        role="model",
                        parts=[
                            genai_types.Part.from_text(
                                text="Prepared follow-up questions grounded in Session 1 memories."
                            )
                        ],
                    )
                ),
            ]
        )
        tool_deps_2 = CoachingToolDependencies(
            preferences_reader=prefs_repo_2,
            contact_reader=contact_repo_2,
            meeting_reader=meeting_repo_2,
            memory_reader=memory_repo_2,
            proposal_stager=proposal_repo_2,
            proposal_agent=FakeMemoryProposalAgent(),
            clock=shared_clock,
            id_generator=ids_2,
        )
        coach_agent_2 = build_conversation_coach_agent(
            settings_2,
            tool_dependencies=tool_deps_2,
            model_override=coach_llm_2,
        )
        adk_app_2 = build_adk_app(
            settings_2,
            tool_dependencies=tool_deps_2,
            root_agent_override=coach_agent_2,
        )
        runner_2 = Runner(
            app=adk_app_2,
            session_service=session_svc_2,
        )

        tool_results_by_name: dict[str, dict[str, Any]] = {}
        async for event in runner_2.run_async(
            user_id=alice.user_id,
            session_id=session_id_2,
            new_message=genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_text(text=f"Help me prepare to meet {alex_id} again.")
                ],
            ),
        ):
            for fn_resp in event.get_function_responses():
                if fn_resp.name and isinstance(fn_resp.response, dict):
                    tool_results_by_name[fn_resp.name] = dict(fn_resp.response)

        # Verify Session 2 retrieved BOTH approved memories from Firestore and excluded rejected one
        contact_tool_data = tool_results_by_name["get_contact_context"]["data"]
        retrieved_contact_mems = contact_tool_data["approved_memories"]
        assert [m["memory_id"] for m in retrieved_contact_mems] == [approved_ai_id]
        assert "challenges adopting AI" in retrieved_contact_mems[0]["text"]
        assert all("evaluation pipelines" not in m["text"] for m in retrieved_contact_mems)

        prefs_tool_data = tool_results_by_name["get_user_preferences"]["data"]
        retrieved_pref_mems = prefs_tool_data["approved_preference_memories"]
        assert [m["memory_id"] for m in retrieved_pref_mems] == [approved_pref_id]
        assert "informal conversations with engineers" in retrieved_pref_mems[0]["text"]

        # Verify preserved provenance, epistemic status, and rejected proposal state in Firestore
        persisted_rejected = await proposal_repo_2.get_for_owner(alice.user_id, rejected_prop_id)
        assert persisted_rejected is not None
        assert persisted_rejected.lifecycle_state is MemoryLifecycleState.REJECTED
        assert persisted_rejected.approved_memory_id is None

        persisted_ai_mem = await memory_repo_2.get_for_owner(alice.user_id, approved_ai_id)
        assert persisted_ai_mem is not None
        assert persisted_ai_mem.epistemic_status is MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
        assert persisted_ai_mem.source.meeting_id == "mtg_alex_session_1"
        assert persisted_ai_mem.source.excerpt == "We discussed his team's challenges adopting AI"

        # Supersede preference in Session 2, then delete contact memory and verify removal
        extractor_llm_2 = _ScriptedEmulatorLlm(
            [
                LlmResponse(
                    content=genai_types.Content(
                        role="model",
                        parts=[
                            genai_types.Part.from_text(
                                text=json.dumps(
                                    {
                                        "candidates": [
                                            {
                                                "scope": "user_preference",
                                                "contact_id": None,
                                                "memory_type": "communication_preference",
                                                "text": (
                                                    "Prefers structured formal agendas with "
                                                    "engineers instead of informal conversations."
                                                ),
                                                "rationale": "Updated user preference.",
                                                "excerpt": (
                                                    "I now prefer structured formal agendas "
                                                    "with engineers"
                                                ),
                                                "supersedes_memory_id": None,
                                            }
                                        ]
                                    }
                                )
                            )
                        ],
                    )
                )
            ]
        )
        retrieval_2 = MemoryRetrievalService(
            preferences_repo=prefs_repo_2,
            contact_repo=contact_repo_2,
            meeting_repo=meeting_repo_2,
            memory_repo=memory_repo_2,
        )
        persistence_2 = MemoryPersistenceService(
            preferences_repo=prefs_repo_2,
            proposal_repo=proposal_repo_2,
            memory_repo=memory_repo_2,
            contact_repo=contact_repo_2,
            meeting_repo=meeting_repo_2,
            brief_repo=brief_repo_2,
            proposal_agent=AdkMemoryProposalAdapter(
                settings=settings_2,
                model_override=extractor_llm_2,
            ),
            clock=shared_clock,
            id_generator=ids_2,
        )
        memory_svc_2 = MemoryService(retrieval=retrieval_2, persistence=persistence_2)

        update_batch = await memory_svc_2.propose_memories_batch(
            principal=alice,
            contact_id=alex_id,
            notes=(
                "Actually, I now prefer structured formal agendas with engineers instead of "
                "informal conversations."
            ),
        )
        assert len(update_batch.proposals) == 1
        assert update_batch.proposals[0].supersedes_memory_id == approved_pref_id
        new_pref_mem = await memory_svc_2.approve_proposal(
            principal=alice,
            proposal_id=update_batch.proposals[0].id,
            expected_version=1,
        )

        superseded_snap = await memory_repo_2.get_for_owner(alice.user_id, approved_pref_id)
        assert superseded_snap is not None
        assert superseded_snap.lifecycle_state is MemoryLifecycleState.SUPERSEDED
        assert superseded_snap.superseded_by_memory_id == new_pref_mem.id

        # Delete the contact memory and confirm it disappears from active retrieval
        await memory_svc_2.delete_memory(
            principal=alice,
            memory_id=approved_ai_id,
            expected_version=1,
        )
        deleted_tombstone = await memory_repo_2.get_deleted_for_owner(
            alice.user_id,
            approved_ai_id,
        )
        assert deleted_tombstone is not None
        assert deleted_tombstone.lifecycle_state is MemoryLifecycleState.DELETED
        assert deleted_tombstone.deleted_at is not None
        assert deleted_tombstone.source.meeting_id == "mtg_alex_session_1"

        final_active = await memory_svc_2.list_memories(principal=alice)
        assert [m.id for m in final_active] == [new_pref_mem.id]
