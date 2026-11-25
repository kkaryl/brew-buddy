"""Local OpenTelemetry tracing, privacy lockdown, and structured JSON logging test suite.

Covers all five required production observability scenarios end-to-end (HTTP -> Workflow ->
Context/Memory Retrieval -> ADK Agent -> Tool -> Gemini Model -> Output Validation ->
Optional Corrective Regeneration -> Firestore Persistence):
1. Successful brief generation
2. Memory retrieval
3. Tool timeout or failure
4. Validation retry (single corrective regeneration & unrecoverable validation failure)
5. Memory approval (proposal staging + HITL durable promotion)
Plus privacy defaults, completion-upload suppression, Cloud Trace exporter wiring,
W3C / X-Cloud-Trace-Context header propagation, log/trace correlation, and zero-print AST checks.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import logging
import os
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.cloud import firestore
from google.genai import types
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import ConfigDict, PrivateAttr

import app.infrastructure.observability as obs_module
from app.application.telemetry import (
    ATTR_AGENT_NAME,
    ATTR_AGENT_VERSION,
    ATTR_DURATION_MS,
    ATTR_ERROR_CLASSIFICATION,
    ATTR_INPUT_TOKENS,
    ATTR_MEMORY_RETRIEVED_COUNT,
    ATTR_MEMORY_SAVED_COUNT,
    ATTR_MODEL_NAME,
    ATTR_OPERATION_NAME,
    ATTR_OUTPUT_TOKENS,
    ATTR_REGENERATION_ATTEMPT,
    ATTR_REGENERATION_COUNT,
    ATTR_REQUEST_ID,
    ATTR_RESULT_STATUS,
    ATTR_TOOL_NAME,
    ATTR_TOTAL_TOKENS,
    ATTR_TRACE_ID,
    ATTR_VALIDATION_PASSED,
    scrub_sensitive_telemetry_text,
)
from app.config import REPO_ROOT, AppSettings
from app.domain.models import (
    AuthenticatedPrincipal,
    Memory,
    MemorySource,
)
from app.domain.types import (
    ConsentStatus,
    MemoryLifecycleState,
    MemoryScope,
    MemorySourceType,
    MemoryType,
)
from app.fast_api_app import create_app
from app.infrastructure.adk_brief_coach import AdkConversationCoachBriefAdapter
from app.infrastructure.adk_memory_extractor import AdkMemoryProposalAdapter
from app.infrastructure.container import build_firestore_service_container
from app.infrastructure.fakes import FakeAuthenticator, SequentialIdGenerator
from app.infrastructure.observability import (
    StructuredJsonFormatter,
    build_adk_telemetry_config,
    capture_traces,
    enforce_telemetry_privacy_defaults,
    ensure_tracer_provider,
)
from app.tools.coaching_tools import CoachingToolDependencies


class DeterministicStepClock:
    """Deterministic UTC clock advancing 30 seconds per read."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 23, 15, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        value = self._now
        self._now = self._now + timedelta(seconds=30)
        return value


@dataclass(frozen=True)
class DelayedTimeoutStep:
    """Simulated slow model turn exceeding the configured deadline."""

    sleep_seconds: float


class DeterministicMockCoachLlm(BaseLlm):
    """Deterministic ADK ``BaseLlm`` test double driving tool calls and JSON turns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _steps: list[Any] = PrivateAttr(default_factory=list)

    def __init__(self, steps: list[Any]) -> None:
        super().__init__(model="deterministic-mock-gemini")
        self._steps = list(steps)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        del llm_request, stream
        if not self._steps:
            raise RuntimeError("DeterministicMockCoachLlm ran out of scripted steps.")
        step = self._steps.pop(0)
        if isinstance(step, DelayedTimeoutStep):
            await asyncio.sleep(step.sleep_seconds)
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part.from_text(text="{}")])
            )
            return
        if isinstance(step, Exception):
            raise step
        assert isinstance(step, LlmResponse)
        yield step


def _tool_call_response(*calls: tuple[str, dict[str, Any]]) -> LlmResponse:
    parts = [
        types.Part(
            function_call=types.FunctionCall(
                id=f"fc_{idx + 1}_{name}",
                name=name,
                args=args,
            )
        )
        for idx, (name, args) in enumerate(calls)
    ]
    return LlmResponse(content=types.Content(role="model", parts=parts))


def _valid_brief_json_payload(
    *,
    contact_name: str = "Priya Nair",
    contact_org: str = "Nimbus Cloud",
    objective: str = "Understand distributed platform reliability trade-offs.",
    duration_minutes: int = 30,
    referenced_memory_ids: list[str] | None = None,
    opener_style: str = "casual",
) -> dict[str, Any]:
    del contact_org, opener_style
    warmup = max(2, duration_minutes // 5)
    wrap = max(2, duration_minutes // 5)
    core = duration_minutes - warmup - wrap
    questions_bank = [
        (
            "q_1",
            "Looking at platform reliability trade-offs, what signal mattered most in practice?",
            "Anchors the coffee chat objective in real operational decisions.",
            "core_objective",
        ),
        (
            "q_2",
            f"What metric tells you a reliability initiative is on track, {contact_name}?",
            "Surfaces concrete evaluation criteria aligned with our meeting objective.",
            "perspective",
        ),
        (
            "q_3",
            "What common misconception do engineers bring when scaling service meshes?",
            "Invites candid technical nuance relevant to our discussion goal.",
            "nuance",
        ),
        (
            "q_4",
            "Where do you see the biggest infrastructure shift over the next two quarters?",
            "Opens forward-looking roadmap context for follow-up conversations.",
            "outlook",
        ),
        (
            "q_5",
            "Which operating cadence helped your team navigate multi-region complexity?",
            "Connects practical execution lessons directly to our reliability objective.",
            "execution",
        ),
        (
            "q_6",
            "When reliability and feature velocity collide, how do you decide what to defer?",
            "Highlights concrete prioritization trade-offs tied to the meeting purpose.",
            "prioritization",
        ),
    ]
    return {
        "contact_context": (
            f"{contact_name} works on infrastructure reliability and service meshes."
        ),
        "meeting_objective": objective,
        "conversation_openers": [
            f"Hey {contact_name}, thanks so much for making {duration_minutes} minutes today!",
            f"Before we jump into {objective.lower()[:80]}, how has your week been going?",
        ],
        "time_boxed_agenda": [
            {
                "title": "Warm Check-In",
                "duration_minutes": warmup,
                "description": "Reconnect and confirm timebox.",
            },
            {
                "title": "Core Reliability Discussion",
                "duration_minutes": core,
                "description": "Explore prioritized reliability trade-off questions.",
            },
            {
                "title": "Wrap-Up & Follow-Ups",
                "duration_minutes": wrap,
                "description": "Capture next steps and express thanks.",
            },
        ],
        "suggested_questions": [
            {"id": qid, "question": q, "rationale": r, "category": c}
            for qid, q, r, c in questions_bank
        ],
        "suggested_follow_up_topics": [
            f"Share concise takeaways with {contact_name}.",
            "Follow up on reliability benchmarks discussed.",
        ],
        "referenced_memory_ids": referenced_memory_ids or [],
        "revision_summary": None,
    }


# ---------------------------------------------------------------------------
# Deterministic In-Memory Firestore AsyncClient Double (Exercises Real Firestore Spans)
# ---------------------------------------------------------------------------


@dataclass
class _FakeDocSnapshot:
    doc_id: str
    data: dict[str, Any] | None

    @property
    def id(self) -> str:
        return self.doc_id

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.data) if self.data is not None else None


class _FakeAsyncDocumentRef:
    def __init__(self, store: dict[str, dict[str, Any]], path: str) -> None:
        self._store = store
        self.path = path
        self.id = path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> _FakeAsyncCollectionRef:
        return _FakeAsyncCollectionRef(self._store, f"{self.path}/{name}")

    async def get(self, transaction: Any = None) -> _FakeDocSnapshot:
        del transaction
        raw = self._store.get(self.path)
        return _FakeDocSnapshot(self.id, copy.deepcopy(raw) if raw is not None else None)

    async def set(self, payload: dict[str, Any]) -> None:
        self._store[self.path] = copy.deepcopy(payload)

    async def delete(self) -> None:
        self._store.pop(self.path, None)


class _FakeAsyncQuery:
    def __init__(
        self,
        store: dict[str, dict[str, Any]],
        prefix: str | None,
        subcollection: str | None = None,
        predicates: list[tuple[str, str, Any]] | None = None,
        limit_count: int | None = None,
    ) -> None:
        self._store = store
        self._prefix = prefix
        self._subcollection = subcollection
        self._predicates = list(predicates or [])
        self._limit_count = limit_count

    def where(self, *, filter: Any = None) -> _FakeAsyncQuery:
        preds = list(self._predicates)
        if filter is not None:
            preds.append((filter.field_path, filter.op_string, filter.value))
        return _FakeAsyncQuery(
            self._store,
            self._prefix,
            subcollection=self._subcollection,
            predicates=preds,
            limit_count=self._limit_count,
        )

    def select(self, _fields: list[str]) -> _FakeAsyncQuery:
        return self

    def limit(self, count: int) -> _FakeAsyncQuery:
        return _FakeAsyncQuery(
            self._store,
            self._prefix,
            subcollection=self._subcollection,
            predicates=self._predicates,
            limit_count=count,
        )

    async def get(self) -> list[_FakeDocSnapshot]:
        matched: list[_FakeDocSnapshot] = []
        for path, doc in sorted(self._store.items()):
            parts = path.split("/")
            if self._prefix is not None:
                prefix_parts = self._prefix.split("/")
                if len(parts) != len(prefix_parts) + 1 or parts[:-1] != prefix_parts:
                    continue
            elif self._subcollection is not None and (
                len(parts) < 2 or parts[-2] != self._subcollection
            ):
                continue

            ok = True
            for field_name, op, expected in self._predicates:
                if op == "==" and doc.get(field_name) != expected:
                    ok = False
                    break
            if not ok:
                continue
            matched.append(_FakeDocSnapshot(parts[-1], copy.deepcopy(doc)))
            if self._limit_count is not None and len(matched) >= self._limit_count:
                break
        return matched


class _FakeAsyncCollectionRef(_FakeAsyncQuery):
    def __init__(self, store: dict[str, dict[str, Any]], path: str) -> None:
        super().__init__(store, prefix=path)
        self._coll_path = path

    def document(self, doc_id: str) -> _FakeAsyncDocumentRef:
        return _FakeAsyncDocumentRef(self._store, f"{self._coll_path}/{doc_id}")


class _FakeAsyncTransaction:
    """Minimal transaction double compatible with ``@firestore.async_transactional``."""

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._staged_sets: list[tuple[str, dict[str, Any]]] = []
        self._staged_deletes: list[str] = []
        self._max_attempts = 1
        self._read_only = False
        self._id: bytes | None = None

    def _clean_up(self) -> None:
        self._staged_sets.clear()
        self._staged_deletes.clear()
        self._id = None

    async def _begin(self, retry_id: bytes | None = None) -> None:
        self._id = retry_id or b"fake_txn_001"

    def set(self, doc_ref: _FakeAsyncDocumentRef, payload: dict[str, Any]) -> None:
        self._staged_sets.append((doc_ref.path, copy.deepcopy(payload)))

    def delete(self, doc_ref: _FakeAsyncDocumentRef) -> None:
        self._staged_deletes.append(doc_ref.path)

    async def _commit(self) -> list[Any]:
        for path, payload in self._staged_sets:
            self._store[path] = payload
        for path in self._staged_deletes:
            self._store.pop(path, None)
        self._clean_up()
        return []

    async def _rollback(self) -> None:
        self._clean_up()


class _InMemoryFirestoreAsyncClient:
    """Deterministic in-memory ``firestore.AsyncClient`` double exercising real repo spans."""

    def __init__(self) -> None:
        self._credentials: None = None
        self.store: dict[str, dict[str, Any]] = {}
        self.injected_failure: Callable[[str], BaseException | None] | None = None

    def collection(self, name: str) -> _FakeAsyncCollectionRef:
        if self.injected_failure is not None:
            err = self.injected_failure(name)
            if err is not None:
                raise err
        return _FakeAsyncCollectionRef(self.store, name)

    def collection_group(self, subcollection: str) -> _FakeAsyncQuery:
        return _FakeAsyncQuery(self.store, prefix=None, subcollection=subcollection)

    def transaction(self) -> _FakeAsyncTransaction:
        return _FakeAsyncTransaction(self.store)


class _SlowTimeoutMeetingReader:
    """Meeting reader wrapper sleeping past the tool timeout to trigger ``TIMEOUT``."""

    def __init__(self, inner: Any, *, delay_seconds: float) -> None:
        self._inner = inner
        self._delay_seconds = delay_seconds
        self.calls = 0

    async def get_for_owner(self, owner_user_id: str, meeting_id: str) -> Any:
        return await self._inner.get_for_owner(owner_user_id, meeting_id)

    async def exists_for_any_owner(self, meeting_id: str) -> bool:
        return bool(await self._inner.exists_for_any_owner(meeting_id))

    async def list_by_owner(
        self,
        owner_user_id: str,
        *,
        contact_id: str | None = None,
    ) -> list[Any]:
        self.calls += 1
        await asyncio.sleep(self._delay_seconds)
        return list(await self._inner.list_by_owner(owner_user_id, contact_id=contact_id))


def _llm_json_with_tokens(
    payload: dict[str, Any] | str,
    *,
    input_tokens: int = 420,
    output_tokens: int = 280,
) -> LlmResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
            total_token_count=input_tokens + output_tokens,
        ),
    )


def _tool_call_with_tokens(
    *calls: tuple[str, dict[str, Any]],
    input_tokens: int = 310,
    output_tokens: int = 65,
) -> LlmResponse:
    base = _tool_call_response(*calls)
    return LlmResponse(
        content=base.content,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
            total_token_count=input_tokens + output_tokens,
        ),
    )


def _build_traced_firestore_app(
    tmp_path: Path,
    *,
    coach_steps: list[Any],
    extractor_steps: list[Any] | None = None,
    model_timeout_seconds: float = 2.0,
    tool_io_timeout_seconds: float = 1.0,
    slow_tool_meeting_delay_seconds: float | None = None,
) -> tuple[Any, _InMemoryFirestoreAsyncClient, DeterministicMockCoachLlm]:
    fs_client = _InMemoryFirestoreAsyncClient()
    clock = DeterministicStepClock()
    ids = SequentialIdGenerator()
    settings = AppSettings(
        environment="test",
        google_cloud_project="brew-obs-test-proj",
        otel_to_cloud=False,
        persistence_backend="firestore",
        web_dist_dir=tmp_path / "no-dist",
    )
    coach_llm = DeterministicMockCoachLlm(coach_steps)
    ext_llm = DeterministicMockCoachLlm(extractor_steps or [])

    base_container = build_firestore_service_container(
        settings,
        client=cast(firestore.AsyncClient, fs_client),
        clock=clock,
        id_generator=ids,
        authenticator=FakeAuthenticator(
            {"tok-alice": AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice")}
        ),
    )
    extractor_adapter = AdkMemoryProposalAdapter(
        settings=settings,
        model_override=ext_llm,
        model_timeout_seconds=model_timeout_seconds,
    )
    tool_meeting_reader: Any = (
        _SlowTimeoutMeetingReader(
            base_container.meeting_repo,
            delay_seconds=slow_tool_meeting_delay_seconds,
        )
        if slow_tool_meeting_delay_seconds is not None
        else base_container.meeting_repo
    )
    coach_adapter = AdkConversationCoachBriefAdapter(
        tool_dependencies=CoachingToolDependencies(
            preferences_reader=base_container.preferences_repo,
            contact_reader=base_container.contact_repo,
            meeting_reader=tool_meeting_reader,
            memory_reader=base_container.memory_repo,
            proposal_stager=base_container.proposal_repo,
            proposal_agent=extractor_adapter,
            clock=clock,
            id_generator=ids,
            io_timeout_seconds=tool_io_timeout_seconds,
        ),
        settings=settings,
        model_override=coach_llm,
        model_timeout_seconds=model_timeout_seconds,
    )
    base_container.brief_agent = coach_adapter
    base_container.proposal_agent = extractor_adapter
    return create_app(settings, service_container=base_container), fs_client, coach_llm


def _assert_all_spans_linked_to_root(
    spans: tuple[ReadableSpan, ...],
    root_span: ReadableSpan,
) -> None:
    span_ids = {s.context.span_id for s in spans if s.context is not None}
    expected_trace = root_span.context.trace_id
    for sp in spans:
        assert sp.context is not None
        assert sp.context.trace_id == expected_trace, (
            f"Span '{sp.name}' trace_id {sp.context.trace_id:032x} != "
            f"root trace_id {expected_trace:032x}"
        )
        if sp is not root_span:
            assert sp.parent is not None, f"Child span '{sp.name}' is missing parent context"
            assert sp.parent.span_id in span_ids, (
                f"Span '{sp.name}' parent {sp.parent.span_id:016x} not found in captured trace"
            )


# ---------------------------------------------------------------------------
# Scenario 1: Successful Brief Generation + Privacy Sentinel Verification
# ---------------------------------------------------------------------------


def test_scenario_1_successful_brief_generation_full_correlated_trace_and_privacy(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_bio_sentinel = "PRIVATE_BIO_SENTINEL_DO_NOT_CAPTURE_9921"
    raw_note_sentinel = "RAW_MEETING_NOTE_SENTINEL_DO_NOT_CAPTURE_8842"

    brief_payload = _valid_brief_json_payload(
        contact_name="Priya Nair",
        contact_org="Nimbus Cloud",
        duration_minutes=30,
        referenced_memory_ids=["mem_seed_01"],
        opener_style="casual",
    )
    fastapi_app, fs_client, _ = _build_traced_firestore_app(
        tmp_path,
        coach_steps=[
            _tool_call_with_tokens(
                ("get_meeting_history", {"contact_id": "cnt_0001", "limit": 3}),
                input_tokens=310,
                output_tokens=55,
            ),
            _llm_json_with_tokens(brief_payload, input_tokens=540, output_tokens=320),
        ],
    )

    now = datetime(2026, 11, 23, 14, 0, 0, tzinfo=UTC)
    seeded_memory = Memory(
        id="mem_seed_01",
        owner_user_id="usr_alice",
        scope=MemoryScope.CONTACT,
        contact_id="cnt_0001",
        memory_type=MemoryType.COUNTERPART_BACKGROUND,
        text="Priya shared that her platform team migrated multi-region service meshes.",
        source=MemorySource(
            source_type=MemorySourceType.MEETING_NOTES,
            excerpt="Platform team migrated service meshes",
            recorded_at=now,
        ),
        consent_status=ConsentStatus.APPROVED,
        lifecycle_state=MemoryLifecycleState.APPROVED,
        created_at=now,
        updated_at=now,
    )
    fs_client.store["users/usr_alice/memories/mem_seed_01"] = seeded_memory.model_dump(
        mode="python"
    )

    with TestClient(fastapi_app) as client:
        headers = {"Authorization": "Bearer tok-alice"}
        contact_resp = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={
                "name": "Priya Nair",
                "title": "Staff Infrastructure Engineer",
                "organization": "Nimbus Cloud",
                "context_notes": (
                    f"{private_bio_sentinel} Reach her at priya.secret@example.com "
                    "or +1 (415) 555-0199."
                ),
            },
        )
        assert contact_resp.status_code == 201
        contact_id = contact_resp.json()["id"]

        caplog.clear()
        with caplog.at_level(logging.INFO), capture_traces() as recorder:
            resp = client.post(
                "/api/v1/briefs/generate",
                headers=headers,
                json={
                    "contact_id": contact_id,
                    "purpose": "coffee_chat",
                    "tone": "warm_casual",
                    "meeting_objective": "Understand distributed platform reliability trade-offs.",
                    "duration_minutes": 30,
                    "meeting_notes": raw_note_sentinel,
                },
            )

    assert resp.status_code == 201
    otel_trace_header = resp.headers["X-Trace-ID"]
    assert len(otel_trace_header) == 32
    assert resp.headers["X-Request-ID"] == otel_trace_header
    assert resp.json()["workflow"]["trace_id"] == otel_trace_header

    spans = recorder.get_finished_spans()
    span_names = [s.name for s in spans]

    # 1. HTTP Request root span
    http_spans = [s for s in spans if s.name == "POST /api/v1/briefs/generate"]
    assert len(http_spans) == 1
    http_root = http_spans[0]
    assert http_root.kind is SpanKind.SERVER
    assert http_root.status.status_code is StatusCode.OK
    assert format(http_root.context.trace_id, "032x") == otel_trace_header
    http_attrs = dict(http_root.attributes or {})
    assert http_attrs[ATTR_OPERATION_NAME] == "http.request"
    assert http_attrs[ATTR_REQUEST_ID] == otel_trace_header
    assert http_attrs[ATTR_TRACE_ID] == otel_trace_header
    assert http_attrs["http.response.status_code"] == 201
    assert isinstance(http_attrs[ATTR_DURATION_MS], float)

    # Every span in the request shares one trace_id and unbroken parent links
    _assert_all_spans_linked_to_root(spans, http_root)

    # 2. Workflow, Context & Memory Retrieval, Agent, Tool, Model, Validation, Firestore
    assert "brew.workflow.generate_brief" in span_names
    assert "brew.context.retrieve" in span_names
    assert "invoke_agent brief_synthesizer" in span_names
    assert "execute_tool get_meeting_history" in span_names
    assert "generate_content deterministic-mock-gemini" in span_names
    assert "brew.output.validate" in span_names
    assert "firestore.contacts.get" in span_names
    assert "firestore.memories.list" in span_names
    assert "firestore.meetings.save" in span_names
    assert "firestore.briefs.save" in span_names

    # Non-duplication guarantee: ADK's execute_tool is enriched, NOT duplicated by coach.tool.*
    assert "coach.tool.get_meeting_history" not in span_names

    ctx_span = next(s for s in spans if s.name == "brew.context.retrieve")
    assert dict(ctx_span.attributes or {})[ATTR_MEMORY_RETRIEVED_COUNT] == 1

    agent_span = next(s for s in spans if s.name == "invoke_agent brief_synthesizer")
    agent_attrs = dict(agent_span.attributes or {})
    assert agent_attrs[ATTR_AGENT_NAME] == "brief_synthesizer"
    assert agent_attrs[ATTR_AGENT_VERSION] == "1.0.0"
    assert agent_attrs[ATTR_MODEL_NAME] == "deterministic-mock-gemini"
    assert isinstance(agent_attrs[ATTR_DURATION_MS], float)

    tool_span = next(s for s in spans if s.name == "execute_tool get_meeting_history")
    tool_attrs = dict(tool_span.attributes or {})
    assert tool_attrs[ATTR_TOOL_NAME] == "get_meeting_history"
    assert tool_attrs[ATTR_RESULT_STATUS] in {"empty", "success"}
    assert isinstance(tool_attrs[ATTR_DURATION_MS], float)

    model_spans = [s for s in spans if s.name == "generate_content deterministic-mock-gemini"]
    assert len(model_spans) == 2
    second_model_attrs = dict(model_spans[1].attributes or {})
    assert second_model_attrs["gen_ai.usage.input_tokens"] == 540
    assert second_model_attrs["gen_ai.usage.output_tokens"] == 320

    wf_span = next(s for s in spans if s.name == "brew.workflow.generate_brief")
    wf_attrs = dict(wf_span.attributes or {})
    assert wf_attrs[ATTR_INPUT_TOKENS] == 850
    assert wf_attrs[ATTR_OUTPUT_TOKENS] == 375
    assert wf_attrs[ATTR_TOTAL_TOKENS] == 1225
    assert wf_attrs[ATTR_MEMORY_RETRIEVED_COUNT] == 1
    assert wf_attrs[ATTR_MEMORY_SAVED_COUNT] == 0

    val_spans = [s for s in spans if s.name == "brew.output.validate"]
    assert len(val_spans) == 2
    assert all(dict(vs.attributes or {})[ATTR_VALIDATION_PASSED] is True for vs in val_spans)

    # Privacy verification: zero raw contact notes, meeting notes, emails, phones, or full prompts
    forbidden_substrings = (
        private_bio_sentinel,
        raw_note_sentinel,
        "priya.secret@example.com",
        "415",
        "REQUEST_PAYLOAD_JSON",
        "tok-alice",
    )
    for sp in spans:
        serialized_attrs = json.dumps(dict(sp.attributes or {}), default=str)
        for secret in forbidden_substrings:
            assert secret not in serialized_attrs, (
                f"Sensitive substring '{secret}' leaked into span '{sp.name}'"
            )
        for ev in sp.events:
            ev_attrs = json.dumps(dict(ev.attributes or {}), default=str)
            for secret in forbidden_substrings:
                assert secret not in ev_attrs

    formatter = StructuredJsonFormatter(gcp_project_id="brew-obs-test-proj")
    formatted_logs = [
        json.loads(formatter.format(rec)) for rec in caplog.records if rec.name.startswith("app.")
    ]
    assert formatted_logs
    for log_entry in formatted_logs:
        assert log_entry["trace_id"] == otel_trace_header
        assert (
            log_entry["logging.googleapis.com/trace"]
            == f"projects/brew-obs-test-proj/traces/{otel_trace_header}"
        )
        assert "span_id" in log_entry
        serialized_log = json.dumps(log_entry)
        for secret in forbidden_substrings:
            assert secret not in serialized_log


# ---------------------------------------------------------------------------
# Scenario 2: Memory Retrieval Trace & Counts
# ---------------------------------------------------------------------------


def test_scenario_2_memory_retrieval_endpoint_trace_and_counts(tmp_path: Path) -> None:
    fastapi_app, fs_client, _ = _build_traced_firestore_app(tmp_path, coach_steps=[])
    now = datetime(2026, 11, 23, 15, 0, 0, tzinfo=UTC)

    for idx in (1, 2):
        mem = Memory(
            id=f"mem_ret_{idx}",
            owner_user_id="usr_alice",
            scope=MemoryScope.USER_PREFERENCE,
            contact_id=None,
            memory_type=MemoryType.COMMUNICATION_PREFERENCE,
            text=f"SENSITIVE_MEMORY_BODY_{idx}: Prefers concise 20-minute coaching agendas.",
            source=MemorySource(
                source_type=MemorySourceType.DIRECT_USER_INPUT,
                excerpt="Prefers concise agendas",
                recorded_at=now,
            ),
            consent_status=ConsentStatus.APPROVED,
            lifecycle_state=MemoryLifecycleState.APPROVED,
            created_at=now,
            updated_at=now,
        )
        fs_client.store[f"users/usr_alice/memories/mem_ret_{idx}"] = mem.model_dump(mode="python")

    with TestClient(fastapi_app) as client, capture_traces() as recorder:
        resp = client.get(
            "/api/v1/memories?scope=user_preference",
            headers={"Authorization": "Bearer tok-alice"},
        )

    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    spans = recorder.get_finished_spans()
    http_root = next(s for s in spans if s.name == "GET /api/v1/memories")
    _assert_all_spans_linked_to_root(spans, http_root)

    mem_span = next(s for s in spans if s.name == "brew.memory.retrieve")
    fs_mem_span = next(s for s in spans if s.name == "firestore.memories.list")
    assert dict(mem_span.attributes or {})[ATTR_MEMORY_RETRIEVED_COUNT] == 2
    assert dict(fs_mem_span.attributes or {})[ATTR_MEMORY_RETRIEVED_COUNT] == 2

    for sp in spans:
        assert "SENSITIVE_MEMORY_BODY_" not in json.dumps(dict(sp.attributes or {}), default=str)


# ---------------------------------------------------------------------------
# Scenario 3: Tool Timeout / Failure & Model Timeout Error Classification
# ---------------------------------------------------------------------------


def test_scenario_3_tool_timeout_and_model_timeout_traces_and_error_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    valid_payload = _valid_brief_json_payload(opener_style="casual")
    fastapi_app, _, _ = _build_traced_firestore_app(
        tmp_path,
        coach_steps=[
            # Request 1: tool times out twice + retry cap triggers, coach recovers
            _tool_call_with_tokens(("get_meeting_history", {"contact_id": "cnt_0001"})),
            _tool_call_with_tokens(("get_meeting_history", {"contact_id": "cnt_0001"})),
            _tool_call_with_tokens(("get_meeting_history", {"contact_id": "cnt_0001"})),
            _llm_json_with_tokens(valid_payload),
            # Request 2: Gemini model call itself exceeds deadline -> HTTP 504 MODEL_TIMEOUT
            DelayedTimeoutStep(sleep_seconds=0.35),
        ],
        model_timeout_seconds=0.20,
        tool_io_timeout_seconds=0.03,
        slow_tool_meeting_delay_seconds=0.08,
    )

    with TestClient(fastapi_app) as client:
        headers = {"Authorization": "Bearer tok-alice"}
        contact_id = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={"name": "Priya Nair", "organization": "Nimbus Cloud"},
        ).json()["id"]
        gen_payload = {
            "contact_id": contact_id,
            "purpose": "coffee_chat",
            "tone": "warm_casual",
            "meeting_objective": "Understand distributed platform reliability trade-offs.",
            "duration_minutes": 30,
        }

        # 3a. Tool timeout + retry cap inside ADK Runner
        caplog.clear()
        with caplog.at_level(logging.INFO), capture_traces() as tool_recorder:
            ok_resp = client.post("/api/v1/briefs/generate", headers=headers, json=gen_payload)

        assert ok_resp.status_code == 201
        assert "get_meeting_history" in ok_resp.json()["workflow"]["degraded_sources"]

        tool_spans = [
            s
            for s in tool_recorder.get_finished_spans()
            if s.name == "execute_tool get_meeting_history"
        ]
        assert len(tool_spans) == 3
        first_tool_attrs = dict(tool_spans[0].attributes or {})
        assert tool_spans[0].status.status_code is StatusCode.ERROR
        assert first_tool_attrs[ATTR_RESULT_STATUS] == "error"
        assert first_tool_attrs[ATTR_ERROR_CLASSIFICATION] == "TIMEOUT"

        capped_tool_attrs = dict(tool_spans[2].attributes or {})
        assert tool_spans[2].status.status_code is StatusCode.ERROR
        assert capped_tool_attrs[ATTR_ERROR_CLASSIFICATION] == "TOOL_RETRY_LIMIT_EXCEEDED"

        # 3b. Model timeout -> HTTP 504 correlated across spans and JSON error logs
        caplog.clear()
        with caplog.at_level(logging.INFO), capture_traces() as timeout_recorder:
            timeout_resp = client.post(
                "/api/v1/briefs/generate",
                headers=headers,
                json=gen_payload,
            )

        assert timeout_resp.status_code == 504
        err_trace_id = timeout_resp.headers["X-Trace-ID"]
        assert timeout_resp.json()["error"]["code"] == "MODEL_TIMEOUT"
        assert timeout_resp.json()["error"]["trace_id"] == err_trace_id

        t_spans = timeout_recorder.get_finished_spans()
        http_err_span = next(s for s in t_spans if s.name == "POST /api/v1/briefs/generate")
        wf_err_span = next(s for s in t_spans if s.name == "brew.workflow.generate_brief")
        assert http_err_span.status.status_code is StatusCode.ERROR
        assert dict(http_err_span.attributes or {})[ATTR_ERROR_CLASSIFICATION] == "MODEL_TIMEOUT"
        assert wf_err_span.status.status_code is StatusCode.ERROR
        assert dict(wf_err_span.attributes or {})[ATTR_ERROR_CLASSIFICATION] == "MODEL_TIMEOUT"

        formatter = StructuredJsonFormatter(gcp_project_id="brew-obs-test-proj")
        err_logs = [
            json.loads(formatter.format(r))
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name.startswith("app.")
        ]
        assert any(
            entry.get("error_classification") == "MODEL_TIMEOUT"
            and entry.get("trace_id") == err_trace_id
            for entry in err_logs
        )


# ---------------------------------------------------------------------------
# Scenario 4: Validation Retry (Optional Corrective Regeneration)
# ---------------------------------------------------------------------------


def test_scenario_4_validation_retry_and_corrective_regeneration_trace(tmp_path: Path) -> None:
    bad_agenda_payload = _valid_brief_json_payload(duration_minutes=30, opener_style="casual")
    # Break agenda sum so json_schema passes OR fails? Let's test quality/domain invariant repair:
    # First attempt uses forbidden em-dash / cliché so evaluate_brief_quality triggers repair;
    # Request 2 fails JSON parsing on both attempts -> 422 MODEL_OUTPUT_VALIDATION_ERROR.
    bad_agenda_payload["conversation_openers"] = [
        "Can I pick your brain about everything keeping you up at night?",
        "Let us touch base — really excited.",
    ]
    repaired_payload = _valid_brief_json_payload(duration_minutes=30, opener_style="casual")

    fastapi_app, _, _ = _build_traced_firestore_app(
        tmp_path,
        coach_steps=[
            # Run 1: Attempt 1 fails quality check -> Corrective Regeneration succeeds
            _llm_json_with_tokens(bad_agenda_payload, input_tokens=400, output_tokens=210),
            _llm_json_with_tokens(repaired_payload, input_tokens=620, output_tokens=290),
            # Run 2: Both attempts return malformed JSON -> HTTP 422
            _llm_json_with_tokens("not-json-attempt-1", input_tokens=300, output_tokens=20),
            _llm_json_with_tokens("not-json-attempt-2", input_tokens=380, output_tokens=25),
        ],
    )

    with TestClient(fastapi_app) as client:
        headers = {"Authorization": "Bearer tok-alice"}
        contact_id = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={"name": "Priya Nair", "organization": "Nimbus Cloud"},
        ).json()["id"]
        gen_payload = {
            "contact_id": contact_id,
            "purpose": "coffee_chat",
            "tone": "warm_casual",
            "meeting_objective": "Understand distributed platform reliability trade-offs.",
            "duration_minutes": 30,
        }

        # 4a. Recoverable validation failure -> single corrective regeneration -> 201
        with capture_traces() as repair_recorder:
            repaired_resp = client.post(
                "/api/v1/briefs/generate",
                headers=headers,
                json=gen_payload,
            )

        assert repaired_resp.status_code == 201
        assert repaired_resp.json()["workflow"]["terminal_state"] == "completed_repaired"
        assert repaired_resp.json()["workflow"]["regeneration_count"] == 1

        r_spans = repair_recorder.get_finished_spans()
        http_root = next(s for s in r_spans if s.name == "POST /api/v1/briefs/generate")
        _assert_all_spans_linked_to_root(r_spans, http_root)

        regen_spans = [s for s in r_spans if s.name == "brew.workflow.corrective_regeneration"]
        assert len(regen_spans) == 1
        regen_span = regen_spans[0]
        assert regen_span.status.status_code is StatusCode.OK
        regen_attrs = dict(regen_span.attributes or {})
        assert regen_attrs[ATTR_REGENERATION_ATTEMPT] == 1
        assert regen_attrs[ATTR_RESULT_STATUS] == "repaired"

        failed_vals = [
            s
            for s in r_spans
            if s.name == "brew.output.validate"
            and dict(s.attributes or {}).get(ATTR_VALIDATION_PASSED) is False
        ]
        passed_vals = [
            s
            for s in r_spans
            if s.name == "brew.output.validate"
            and dict(s.attributes or {}).get(ATTR_VALIDATION_PASSED) is True
        ]
        assert len(failed_vals) == 1
        assert failed_vals[0].status.status_code is StatusCode.ERROR
        assert dict(failed_vals[0].attributes or {})[ATTR_ERROR_CLASSIFICATION] == (
            "OUTPUT_VALIDATION_ERROR"
        )
        assert len(passed_vals) >= 2

        wf_span = next(s for s in r_spans if s.name == "brew.workflow.generate_brief")
        wf_attrs = dict(wf_span.attributes or {})
        assert wf_attrs[ATTR_REGENERATION_COUNT] == 1
        assert wf_attrs[ATTR_TOTAL_TOKENS] == (400 + 210 + 620 + 290)

        # 4b. Unrecoverable validation failure after single repair -> 422
        with capture_traces() as fail_recorder:
            fail_resp = client.post(
                "/api/v1/briefs/generate",
                headers=headers,
                json=gen_payload,
            )

        assert fail_resp.status_code == 422
        assert fail_resp.json()["error"]["code"] == "MODEL_OUTPUT_VALIDATION_ERROR"
        f_spans = fail_recorder.get_finished_spans()
        failed_regen = next(s for s in f_spans if s.name == "brew.workflow.corrective_regeneration")
        assert failed_regen.status.status_code is StatusCode.ERROR
        assert dict(failed_regen.attributes or {})[ATTR_ERROR_CLASSIFICATION] == (
            "OUTPUT_VALIDATION_ERROR"
        )


# ---------------------------------------------------------------------------
# Scenario 5: Memory Proposal & HITL Memory Approval Traces
# ---------------------------------------------------------------------------


def test_scenario_5_memory_proposal_and_approval_traces_and_saved_counts(tmp_path: Path) -> None:
    extractor_json = {
        "candidates": [
            {
                "scope": "contact",
                "contact_id": "cnt_0001",
                "memory_type": "follow_up_commitment",
                "text": "Priya asked to share our latency benchmark deck next Tuesday.",
                "rationale": "Concrete follow-up commitment for the next coffee chat.",
                "excerpt": "Share latency benchmark deck next Tuesday",
                "supersedes_memory_id": None,
            }
        ]
    }
    fastapi_app, _, _ = _build_traced_firestore_app(
        tmp_path,
        coach_steps=[],
        extractor_steps=[_llm_json_with_tokens(extractor_json, input_tokens=260, output_tokens=95)],
    )

    with TestClient(fastapi_app) as client:
        headers = {"Authorization": "Bearer tok-alice"}
        contact_id = client.post(
            "/api/v1/contacts",
            headers=headers,
            json={"name": "Priya Nair", "organization": "Nimbus Cloud"},
        ).json()["id"]

        # 5a. Stage candidate proposal (must NOT write to approved memories yet)
        with capture_traces() as propose_recorder:
            prop_resp = client.post(
                "/api/v1/memories/propose",
                headers=headers,
                json={
                    "contact_id": contact_id,
                    "notes": (
                        "CONFIDENTIAL_NOTE_TOKEN_771: Priya asked to share our latency "
                        "benchmark deck next Tuesday."
                    ),
                },
            )

        assert prop_resp.status_code == 201
        proposal_id = prop_resp.json()["proposals"][0]["id"]

        p_spans = propose_recorder.get_finished_spans()
        p_root = next(s for s in p_spans if s.name == "POST /api/v1/memories/propose")
        _assert_all_spans_linked_to_root(p_spans, p_root)
        propose_span = next(s for s in p_spans if s.name == "brew.memory.propose")
        assert dict(propose_span.attributes or {})[ATTR_MEMORY_SAVED_COUNT] == 1
        assert any(s.name == "invoke_agent memory_candidate_extractor" for s in p_spans)
        assert any(s.name == "firestore.memory_proposals.save" for s in p_spans)
        assert not any(s.name == "firestore.memories.save" for s in p_spans)
        for sp in p_spans:
            assert "CONFIDENTIAL_NOTE_TOKEN_771" not in json.dumps(
                dict(sp.attributes or {}), default=str
            )

        # 5b. Human-in-the-Loop approval promotes proposal into durable Firestore memory
        with capture_traces() as approve_recorder:
            approve_resp = client.post(
                f"/api/v1/memories/{proposal_id}/approve",
                headers=headers,
                json={"expected_version": 1},
            )

        assert approve_resp.status_code == 200
        a_spans = approve_recorder.get_finished_spans()
        a_root = next(s for s in a_spans if s.name == "POST /api/v1/memories/{id}/approve")
        _assert_all_spans_linked_to_root(a_spans, a_root)

        approve_span = next(s for s in a_spans if s.name == "brew.memory.approve")
        approve_attrs = dict(approve_span.attributes or {})
        assert approve_attrs[ATTR_MEMORY_SAVED_COUNT] == 1
        assert approve_attrs[ATTR_MEMORY_RETRIEVED_COUNT] == 0

        fs_mem_save = next(s for s in a_spans if s.name == "firestore.memories.save")
        assert dict(fs_mem_save.attributes or {})[ATTR_MEMORY_SAVED_COUNT] == 1
        assert dict(fs_mem_save.attributes or {})["db.system"] == "firestore"


# ---------------------------------------------------------------------------
# Privacy Gates, Upstream Propagation, Cloud Trace Exporter, & Zero-Print Checks
# ---------------------------------------------------------------------------


def test_privacy_defaults_suppress_content_capture_and_completion_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SPAN_AND_EVENT")
    monkeypatch.setenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "true")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "upload")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH", "gs://bucket/completions")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT", "jsonl")

    default_settings = AppSettings(environment="test", otel_to_cloud=False)
    posture = enforce_telemetry_privacy_defaults(default_settings)

    assert posture["content_capture_mode"] == "NO_CONTENT"
    assert posture["adk_span_content_capture"] == "false"
    assert posture["completion_uploads_enabled"] == "false"
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "NO_CONTENT"
    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"
    assert "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK" not in os.environ
    assert "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH" not in os.environ

    adk_cfg = build_adk_telemetry_config(default_settings)
    assert adk_cfg.should_add_content_to_legacy_spans is False
    assert adk_cfg.should_add_content_to_experimental_spans is False
    assert adk_cfg.should_add_content_to_logs is False

    # Explicit opt-in authorizes capture and preserves completion upload hook
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "upload")
    authorized_settings = AppSettings(
        environment="test",
        otel_to_cloud=False,
        telemetry_capture_content=True,
        telemetry_upload_completions=True,
    )
    opt_in_posture = enforce_telemetry_privacy_defaults(authorized_settings)
    assert opt_in_posture["completion_uploads_enabled"] == "true"
    assert os.environ.get("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK") == "upload"

    # Restore strict privacy immediately after test
    enforce_telemetry_privacy_defaults(default_settings)


def test_w3c_traceparent_and_cloud_trace_context_propagation_and_exporter_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fastapi_app, _, _ = _build_traced_firestore_app(tmp_path, coach_steps=[])

    with TestClient(fastapi_app) as client:
        # W3C traceparent header propagation
        w3c_trace = "4bf92f3577b34da6a3ce929d0e0e4736"
        with capture_traces() as w3c_rec:
            resp1 = client.get(
                "/healthz",
                headers={"traceparent": f"00-{w3c_trace}-00f067aa0ba902b7-01"},
            )
        assert resp1.status_code == 200
        assert resp1.headers["X-Trace-ID"] == w3c_trace
        root1 = next(s for s in w3c_rec.get_finished_spans() if s.name == "GET /healthz")
        assert format(root1.context.trace_id, "032x") == w3c_trace

        # Google Cloud X-Cloud-Trace-Context header propagation
        gcp_trace = "105445aa7843bc8bf206b12000100000"
        with capture_traces() as gcp_rec:
            resp2 = client.get(
                "/healthz",
                headers={"X-Cloud-Trace-Context": f"{gcp_trace}/123456789;o=1"},
            )
        assert resp2.status_code == 200
        assert resp2.headers["X-Trace-ID"] == gcp_trace
        root2 = next(s for s in gcp_rec.get_finished_spans() if s.name == "GET /healthz")
        assert format(root2.context.trace_id, "032x") == gcp_trace

    # Verify standalone CloudTraceSpanExporter attachment uses configured GCP project ID
    captured_projects: list[str | None] = []

    class _StubCloudTraceExporter:
        def export(self, spans: Any) -> Any:
            del spans
            return None

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            del timeout_millis
            return True

    def _fake_builder(project_id: str | None = None) -> Any:
        captured_projects.append(project_id)
        return _StubCloudTraceExporter()

    monkeypatch.setattr(obs_module, "build_cloud_trace_exporter", _fake_builder)
    monkeypatch.setattr(obs_module, "_CLOUD_TRACE_ATTACHED_PROVIDERS", set())
    ensure_tracer_provider(
        AppSettings(
            environment="test",
            google_cloud_project="brew-cloud-trace-verify",
            otel_to_cloud=False,
        ),
        attach_cloud_trace_exporter=True,
    )
    assert captured_projects == ["brew-cloud-trace-verify"]


def test_credential_scrubber_and_zero_arbitrary_print_statements_in_app() -> None:
    raw = (
        "Failed calling endpoint with Authorization: Bearer eyJhbGciOiJSUzI1NiJ9."
        "eyJzdWIiOiJ1c3JfMSJ9.c2lnbmF0dXJl, api_key=AIzaSyDummySecretKey1234567890, "
        "contact alice@example.com SSN 123-45-6789"
    )
    scrubbed = scrub_sensitive_telemetry_text(raw)
    assert "eyJhbGci" not in scrubbed
    assert "AIzaSyDummy" not in scrubbed
    assert "alice@example.com" not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "[REDACTED" in scrubbed

    app_dir = REPO_ROOT / "app"
    offenders: list[str] = []
    for py_file in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and (node.func.id == "print")
            ):
                offenders.append(f"{py_file.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], f"Arbitrary print() statements found in app/: {offenders}"
