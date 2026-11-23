"""Deterministic unit, safety, and HTTP v1 tests for Brew's long-term memory lifecycle."""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ConfigDict, PrivateAttr

from app.application.memory_persistence_service import MemoryPersistenceService
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.application.services import ContactService, MemoryService
from app.config import REPO_ROOT, AppSettings
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
)
from app.domain.models import AuthenticatedPrincipal, Meeting
from app.domain.types import (
    MeetingPurpose,
    MeetingStatus,
    MeetingTone,
    MemoryEpistemicStatus,
    MemoryLifecycleState,
    MemoryScope,
    ProposalStatus,
)
from app.fast_api_app import create_app
from app.infrastructure.adk_memory_extractor import AdkMemoryProposalAdapter
from app.infrastructure.fakes import (
    FakeAuthenticator,
    FakeBriefCoachAgent,
    InMemoryBriefRepository,
    InMemoryContactRepository,
    InMemoryMeetingRepository,
    InMemoryMemoryProposalRepository,
    InMemoryMemoryRepository,
    InMemoryUserPreferencesRepository,
    InMemoryWorkflowIdempotencyRepository,
    SequentialIdGenerator,
    ServiceContainer,
)

ALEX_SCENARIO_NOTES = (
    "We discussed his team's challenges adopting AI. "
    "He recommended learning more about evaluation pipelines. "
    "I prefer having informal conversations with engineers."
)


class StepClock:
    """Deterministic UTC clock advancing one minute per read."""

    def __init__(self) -> None:
        self._now = datetime(2026, 11, 23, 16, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        current = self._now
        self._now = self._now + timedelta(minutes=1)
        return current


class ScriptedMemoryExtractorLlm(BaseLlm):
    """Deterministic ADK ``BaseLlm`` returning scripted JSON candidate batches."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _payloads: list[dict[str, Any] | str] = PrivateAttr(default_factory=list)
    _requests: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(self, payloads: list[dict[str, Any] | str]) -> None:
        super().__init__(model="deterministic-memory-extractor")
        self._payloads = list(payloads)
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
        item = self._payloads.pop(0)
        raw_text = item if isinstance(item, str) else json.dumps(item)
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=raw_text)],
            )
        )


def _alex_extractor_json(contact_id: str) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "scope": "contact",
                "contact_id": contact_id,
                "memory_type": "counterpart_background",
                "text": "Alex discussed his team's challenges adopting AI.",
                "rationale": "Frames relevant follow-up questions around AI adoption hurdles.",
                "excerpt": "We discussed his team's challenges adopting AI",
                "supersedes_memory_id": None,
            },
            {
                "scope": "contact",
                "contact_id": contact_id,
                "memory_type": "follow_up_commitment",
                "text": "Alex recommended exploring evaluation pipelines.",
                "rationale": "Captures a concrete learning recommendation for the next chat.",
                "excerpt": "He recommended learning more about evaluation pipelines",
                "supersedes_memory_id": None,
            },
            {
                "scope": "user_preference",
                "contact_id": None,
                "memory_type": "communication_preference",
                "text": "Prefers having informal conversations with engineers.",
                "rationale": "Tailors future engineering coffee chat tone and openers.",
                "excerpt": "I prefer having informal conversations with engineers",
                "supersedes_memory_id": None,
            },
        ]
    }


def _build_memory_test_bundle(
    extractor_llm: ScriptedMemoryExtractorLlm,
) -> tuple[
    StepClock,
    ContactService,
    MemoryService,
    MemoryRetrievalService,
    MemoryPersistenceService,
    InMemoryMeetingRepository,
    InMemoryMemoryProposalRepository,
    InMemoryMemoryRepository,
]:
    clock = StepClock()
    ids = SequentialIdGenerator()
    prefs_repo = InMemoryUserPreferencesRepository()
    contact_repo = InMemoryContactRepository()
    meeting_repo = InMemoryMeetingRepository()
    brief_repo = InMemoryBriefRepository()
    proposal_repo = InMemoryMemoryProposalRepository()
    memory_repo = InMemoryMemoryRepository()

    settings = AppSettings(environment="test", otel_to_cloud=False)
    extractor = AdkMemoryProposalAdapter(settings=settings, model_override=extractor_llm)

    contact_service = ContactService(
        contact_repo=contact_repo,
        clock=clock,
        id_generator=ids,
    )
    retrieval = MemoryRetrievalService(
        preferences_repo=prefs_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        memory_repo=memory_repo,
    )
    persistence = MemoryPersistenceService(
        preferences_repo=prefs_repo,
        proposal_repo=proposal_repo,
        memory_repo=memory_repo,
        contact_repo=contact_repo,
        meeting_repo=meeting_repo,
        brief_repo=brief_repo,
        proposal_agent=extractor,
        clock=clock,
        id_generator=ids,
    )
    memory_service = MemoryService(retrieval=retrieval, persistence=persistence)
    return (
        clock,
        contact_service,
        memory_service,
        retrieval,
        persistence,
        meeting_repo,
        proposal_repo,
        memory_repo,
    )


@pytest.mark.asyncio
async def test_alex_scenario_states_deduplication_contradiction_and_deletion() -> None:
    llm = ScriptedMemoryExtractorLlm(
        [
            # 1. Alex initial meeting notes
            _alex_extractor_json("cnt_0001"),
            # 2. Duplicate re-submission + contradicting preference update
            {
                "candidates": [
                    {
                        "scope": "contact",
                        "contact_id": "cnt_0001",
                        "memory_type": "counterpart_background",
                        "text": "Alex discussed his team's challenges adopting AI.",
                        "rationale": "Duplicate check.",
                        "excerpt": "We discussed his team's challenges adopting AI",
                        "supersedes_memory_id": None,
                    },
                    {
                        "scope": "user_preference",
                        "contact_id": None,
                        "memory_type": "communication_preference",
                        "text": (
                            "Prefers structured formal agendas with engineers instead of "
                            "informal conversations."
                        ),
                        "rationale": "Updated coaching style preference.",
                        "excerpt": (
                            "Actually, I now prefer structured formal agendas with engineers "
                            "instead of informal conversations"
                        ),
                        "supersedes_memory_id": None,
                    },
                ]
            },
        ]
    )
    (
        clock,
        contact_service,
        memory_service,
        retrieval,
        _persistence,
        meeting_repo,
        proposal_repo,
        memory_repo,
    ) = _build_memory_test_bundle(llm)

    alice = AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")
    bob = AuthenticatedPrincipal(user_id="usr_bob", display_name="Bob")

    alex = await contact_service.create_contact(
        principal=alice,
        name="Alex Chen",
        title="Staff ML Engineer",
        organization="Kestrel AI",
    )
    t0 = clock.now_utc()
    meeting = await meeting_repo.save(
        Meeting(
            id="mtg_alex_01",
            owner_user_id=alice.user_id,
            contact_id=alex.id,
            purpose=MeetingPurpose.COFFEE_CHAT,
            tone=MeetingTone.WARM_CASUAL,
            objective="Learn how Alex's team approaches ML evaluation.",
            duration_minutes=30,
            status=MeetingStatus.COMPLETED,
            created_at=t0,
            updated_at=t0,
        )
    )

    # Step 1-4: Propose memories from Alex notes -> staged as PROPOSED, zero active memories
    batch_1 = await memory_service.propose_memories_batch(
        principal=alice,
        notes=ALEX_SCENARIO_NOTES,
        meeting_id=meeting.id,
    )
    assert len(batch_1.proposals) == 3
    assert all(p.lifecycle_state is MemoryLifecycleState.PROPOSED for p in batch_1.proposals)
    assert all(p.status is ProposalStatus.PENDING for p in batch_1.proposals)
    assert await memory_service.list_memories(principal=alice) == []

    # Epistemic & provenance checks: attributed context, never verified world facts
    p_ai, p_eval, p_pref = batch_1.proposals
    assert p_ai.scope is MemoryScope.CONTACT and p_ai.contact_id == alex.id
    assert p_ai.epistemic_status is MemoryEpistemicStatus.USER_REPORTED_OBSERVATION
    assert p_ai.source.meeting_id == meeting.id
    assert p_ai.source.excerpt == "We discussed his team's challenges adopting AI"

    assert p_eval.scope is MemoryScope.CONTACT and p_eval.contact_id == alex.id
    assert p_pref.scope is MemoryScope.USER_PREFERENCE and p_pref.contact_id is None
    assert p_pref.epistemic_status is MemoryEpistemicStatus.USER_STATED_PREFERENCE

    # Step 4: Display proposals for human review
    listed_pending = await memory_service.list_proposals(
        principal=alice,
        status=ProposalStatus.PENDING,
    )
    assert [p.id for p in listed_pending] == [p_ai.id, p_eval.id, p_pref.id]

    # Step 5-6: Approve p_ai and p_pref; Reject p_eval
    mem_ai = await memory_service.approve_proposal(
        principal=alice,
        proposal_id=p_ai.id,
        expected_version=1,
    )
    rejected_eval = await memory_service.reject_proposal(
        principal=alice,
        proposal_id=p_eval.id,
        expected_version=1,
        reason="Already covered evaluation pipelines offline.",
    )
    mem_pref_v1 = await memory_service.approve_proposal(
        principal=alice,
        proposal_id=p_pref.id,
        expected_version=1,
    )

    assert mem_ai.lifecycle_state is MemoryLifecycleState.APPROVED
    assert mem_ai.source.proposal_id == p_ai.id
    assert mem_ai.source.meeting_id == meeting.id
    assert rejected_eval.lifecycle_state is MemoryLifecycleState.REJECTED
    assert rejected_eval.approved_memory_id is None

    # Rejected proposal cannot subsequently be approved and is NEVER in active memories
    with pytest.raises(ConflictError) as reject_conflict:
        await memory_service.approve_proposal(
            principal=alice,
            proposal_id=p_eval.id,
            expected_version=2,
        )
    assert reject_conflict.value.code == "PROPOSAL_NOT_PENDING"

    active_after_review = await memory_service.list_memories(principal=alice)
    assert [m.id for m in active_after_review] == [mem_ai.id, mem_pref_v1.id]

    # Step 7-8: Deduplicate duplicate note AND resolve contradicting preference explicitly
    batch_2 = await memory_service.propose_memories_batch(
        principal=alice,
        notes=(
            "We discussed his team's challenges adopting AI. "
            "Actually, I now prefer structured formal agendas with engineers instead of "
            "informal conversations."
        ),
        meeting_id=meeting.id,
    )
    assert batch_2.skipped_duplicates == 1
    assert len(batch_2.proposals) == 1
    contradicting_prop = batch_2.proposals[0]
    assert contradicting_prop.supersedes_memory_id == mem_pref_v1.id
    assert contradicting_prop.conflict_summary is not None

    mem_pref_v2 = await memory_service.approve_proposal(
        principal=alice,
        proposal_id=contradicting_prop.id,
        expected_version=1,
    )
    assert mem_pref_v2.lifecycle_state is MemoryLifecycleState.APPROVED
    assert mem_pref_v2.supersedes_memory_id == mem_pref_v1.id

    old_pref_record = await memory_repo.get_for_owner(alice.user_id, mem_pref_v1.id)
    assert old_pref_record is not None
    assert old_pref_record.lifecycle_state is MemoryLifecycleState.SUPERSEDED
    assert old_pref_record.superseded_by_memory_id == mem_pref_v2.id
    assert old_pref_record.superseded_at is not None

    # Active retrieval returns ONLY mem_ai and mem_pref_v2 (old superseded item excluded)
    active_memories = await memory_service.list_memories(principal=alice)
    assert {m.id for m in active_memories} == {mem_ai.id, mem_pref_v2.id}
    with_superseded = await memory_service.list_memories(
        principal=alice,
        include_superseded=True,
    )
    assert {m.id for m in with_superseded} == {mem_ai.id, mem_pref_v1.id, mem_pref_v2.id}

    # Pre-brief context assembly only includes active memories
    prep_ctx = await retrieval.build_brief_context(
        principal=alice,
        contact_id=alex.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        objective="Follow up on AI adoption.",
    )
    assert set(prep_ctx.referenced_memory_ids) == {mem_ai.id, mem_pref_v2.id}

    # Cross-user ownership enforcement across operations
    with pytest.raises(AuthorizationError):
        await memory_service.reject_proposal(principal=bob, proposal_id=p_ai.id)
    with pytest.raises(AuthorizationError):
        await memory_service.delete_memory(principal=bob, memory_id=mem_ai.id)
    assert await proposal_repo.list_by_owner(bob.user_id) == []

    # Delete removes memory from future retrieval while archiving DELETED tombstone
    await memory_service.delete_memory(
        principal=alice,
        memory_id=mem_ai.id,
        expected_version=1,
    )
    tombstone = await memory_repo.get_deleted_for_owner(alice.user_id, mem_ai.id)
    assert tombstone is not None
    assert tombstone.lifecycle_state is MemoryLifecycleState.DELETED
    assert tombstone.deleted_at is not None
    assert tombstone.source.proposal_id == p_ai.id

    post_delete_ctx = await retrieval.build_brief_context(
        principal=alice,
        contact_id=alex.id,
        purpose=MeetingPurpose.COFFEE_CHAT,
        objective="Follow up after deleting AI memory.",
    )
    assert mem_ai.id not in post_delete_ctx.referenced_memory_ids
    assert post_delete_ctx.referenced_memory_ids == [mem_pref_v2.id]

    with pytest.raises(EntityNotFoundError):
        await memory_service.delete_memory(principal=alice, memory_id=mem_ai.id)


@pytest.mark.asyncio
async def test_sensitive_third_party_assumptions_and_callback_write_prohibition() -> None:
    # 1. Static & runtime check: ADK plugins/callbacks hold zero repository write methods
    for plugin_rel in (
        "app/plugins/coach_guardrails.py",
        "app/plugins/workflow_safeguards.py",
        "app/infrastructure/adk_memory_extractor.py",
    ):
        tree = ast.parse((REPO_ROOT / plugin_rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {
                    "approve_proposal",
                    "upsert_user_preferences",
                }, f"Forbidden persistence call '{node.attr}' in {plugin_rel}"

    # 2. Sensitive personal & third-party speculative assumptions are dropped & rejected
    llm = ScriptedMemoryExtractorLlm(
        [
            {
                "candidates": [
                    {
                        "scope": "contact",
                        "contact_id": "cnt_0001",
                        "memory_type": "counterpart_background",
                        "text": "Alex discussed evaluation dataset versioning.",
                        "rationale": "Useful technical context.",
                        "excerpt": "Alex discussed evaluation dataset versioning",
                        "supersedes_memory_id": None,
                    },
                    {
                        "scope": "contact",
                        "contact_id": "cnt_0001",
                        "memory_type": "relationship_note",
                        "text": "Coworker Jordan is getting fired after a failed review.",
                        "rationale": "Unsafe rumor that must be dropped.",
                        "excerpt": "rumor is coworker Jordan is getting fired",
                        "supersedes_memory_id": None,
                    },
                ]
            }
        ]
    )
    (
        _clock,
        contact_service,
        memory_service,
        _retrieval,
        _persistence,
        _meeting_repo,
        _proposal_repo,
        memory_repo,
    ) = _build_memory_test_bundle(llm)

    alice = AuthenticatedPrincipal(user_id="usr_alice")
    alex = await contact_service.create_contact(principal=alice, name="Alex Chen")

    batch = await memory_service.propose_memories_batch(
        principal=alice,
        contact_id=alex.id,
        notes=(
            "Alex discussed evaluation dataset versioning. "
            "I assume his coworker Jordan is getting fired soon. "
            "Alex seems burned out and struggling with anxiety."
        ),
    )
    # 2 raw sensitive segments + 1 unsafe LLM candidate filtered; only safe technical item staged
    assert batch.filtered_sensitive_count >= 2
    assert len(batch.proposals) == 1
    assert "evaluation dataset versioning" in batch.proposals[0].text
    assert await memory_repo.list_by_owner(alice.user_id, include_revoked=True) == []

    # Attempting to sneak sensitive assumptions through edited_text on approval is rejected
    with pytest.raises(DomainValidationError) as edit_exc:
        await memory_service.approve_proposal(
            principal=alice,
            proposal_id=batch.proposals[0].id,
            expected_version=1,
            edited_text="I assume his manager is about to be laid off.",
        )
    assert edit_exc.value.code == "SENSITIVE_MEMORY_REJECTED"


def test_http_memory_review_reject_proposals_list_and_supersede_endpoints(
    tmp_path: Path,
) -> None:
    llm = ScriptedMemoryExtractorLlm(
        [
            _alex_extractor_json("cnt_0001"),
            {
                "candidates": [
                    {
                        "scope": "user_preference",
                        "contact_id": None,
                        "memory_type": "communication_preference",
                        "text": (
                            "Prefers structured executive agendas with engineers instead of "
                            "informal conversations."
                        ),
                        "rationale": "Updated user preference.",
                        "excerpt": "I now prefer structured executive agendas with engineers",
                        "supersedes_memory_id": None,
                    }
                ]
            },
        ]
    )
    clock = StepClock()
    ids = SequentialIdGenerator()
    settings = AppSettings(
        environment="test",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    container = ServiceContainer(
        clock=clock,
        id_generator=ids,
        authenticator=FakeAuthenticator(
            {"tok-alice": AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")}
        ),
        preferences_repo=InMemoryUserPreferencesRepository(),
        contact_repo=InMemoryContactRepository(),
        meeting_repo=InMemoryMeetingRepository(),
        brief_repo=InMemoryBriefRepository(),
        proposal_repo=InMemoryMemoryProposalRepository(),
        memory_repo=InMemoryMemoryRepository(),
        brief_agent=FakeBriefCoachAgent(),
        proposal_agent=AdkMemoryProposalAdapter(settings=settings, model_override=llm),
        idempotency_repo=InMemoryWorkflowIdempotencyRepository(),
    )

    with TestClient(create_app(settings, service_container=container)) as client:
        headers = {"Authorization": "Bearer tok-alice"}
        alex_id = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={"name": "Alex Chen", "organization": "Kestrel AI"},
        ).json()["id"]

        prop_resp = client.post(
            "/api/v1/memories/propose",
            headers=headers,
            json={"notes": ALEX_SCENARIO_NOTES, "contact_id": alex_id},
        )
        assert prop_resp.status_code == 201
        proposals = prop_resp.json()["proposals"]
        assert len(proposals) == 3
        assert all(p["lifecycle_state"] == "proposed" for p in proposals)

        # GET /api/v1/memories/proposals lists pending items for human review
        pending_list = client.get(
            "/api/v1/memories/proposals?status=pending",
            headers=headers,
        ).json()
        assert pending_list["total"] == 3

        # Reject second proposal via POST /api/v1/memories/{id}/reject
        rej_resp = client.post(
            f"/api/v1/memories/{proposals[1]['id']}/reject",
            headers=headers,
            json={"expected_version": 1, "reason": "Skip saving this recommendation."},
        )
        assert rej_resp.status_code == 200
        assert rej_resp.json()["lifecycle_state"] == "rejected"
        assert rej_resp.json()["rejection_reason"] == "Skip saving this recommendation."

        # Approve first and third proposals
        mem_1 = client.post(
            f"/api/v1/memories/{proposals[0]['id']}/approve",
            headers=headers,
            json={"expected_version": 1},
        ).json()
        mem_pref_1 = client.post(
            f"/api/v1/memories/{proposals[2]['id']}/approve",
            headers=headers,
            json={"expected_version": 1},
        ).json()
        assert mem_1["lifecycle_state"] == "approved"
        assert mem_pref_1["lifecycle_state"] == "approved"

        # Propose & approve contradicting preference -> supersedes mem_pref_1
        contradict_prop = client.post(
            "/api/v1/memories/propose",
            headers=headers,
            json={
                "notes": (
                    "Actually, I now prefer structured executive agendas with engineers "
                    "instead of informal conversations."
                ),
                "contact_id": alex_id,
            },
        ).json()["proposals"][0]
        assert contradict_prop["supersedes_memory_id"] == mem_pref_1["id"]

        mem_pref_2 = client.post(
            f"/api/v1/memories/{contradict_prop['id']}/approve",
            headers=headers,
            json={"expected_version": 1},
        ).json()
        assert mem_pref_2["supersedes_memory_id"] == mem_pref_1["id"]

        active_only = client.get("/api/v1/memories", headers=headers).json()["items"]
        assert {m["id"] for m in active_only} == {mem_1["id"], mem_pref_2["id"]}

        all_hist = client.get(
            "/api/v1/memories?include_superseded=true",
            headers=headers,
        ).json()["items"]
        by_id = {m["id"]: m for m in all_hist}
        assert by_id[mem_pref_1["id"]]["lifecycle_state"] == "superseded"
        assert by_id[mem_pref_1["id"]]["superseded_by_memory_id"] == mem_pref_2["id"]
