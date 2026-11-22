"""Integration tests for Brew API v1 contracts, OpenAPI spec, auth, errors, and concurrency."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.openapi import DEFAULT_OPENAPI_PATH, build_openapi_contract
from app.api.schemas import ApiErrorResponse
from app.config import AppSettings
from app.domain.models import AuthenticatedPrincipal
from app.fast_api_app import create_app
from app.infrastructure.fakes import FakeAuthenticator, FakeServiceContainer

ALICE_TOKEN = "token-alice-test"
BOB_TOKEN = "token-bob-test"


class StepUtcClock:
    """Deterministic UTC clock for reproducible HTTP contract tests."""

    def __init__(self) -> None:
        self._current = datetime(2026, 11, 22, 13, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        value = self._current
        self._current = self._current + timedelta(seconds=30)
        return value


def _build_client(tmp_path: Path) -> TestClient:
    authenticator = FakeAuthenticator(
        {
            ALICE_TOKEN: AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice"),
            BOB_TOKEN: AuthenticatedPrincipal(user_id="usr_bob", display_name="Bob"),
        }
    )
    container = FakeServiceContainer(clock=StepUtcClock(), authenticator=authenticator)
    settings = AppSettings(
        environment="test",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "missing-dist",
    )
    return TestClient(create_app(settings, service_container=container))


def _auth_headers(token: str, *, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    return headers


def _assert_error_envelope(
    response_json: dict[str, object],
    *,
    expected_code: str,
    expected_trace_id: str | None = None,
) -> ApiErrorResponse:
    parsed = ApiErrorResponse.model_validate(response_json)
    assert parsed.error.code == expected_code
    assert parsed.error.trace_id
    if expected_trace_id is not None:
        assert parsed.error.trace_id == expected_trace_id
    assert "Traceback" not in parsed.error.message
    return parsed


def test_openapi_contract_contains_all_required_v1_endpoints_and_matches_committed_spec(
    tmp_path: Path,
) -> None:
    expected_operations = {
        "/api/v1/briefs/generate": {"post"},
        "/api/v1/briefs/{id}/revise": {"post"},
        "/api/v1/briefs/{id}": {"get"},
        "/api/v1/contacts": {"get", "post"},
        "/api/v1/meetings": {"get"},
        "/api/v1/memories/propose": {"post"},
        "/api/v1/memories/{id}/approve": {"post"},
        "/api/v1/memories": {"get"},
        "/api/v1/memories/{id}": {"patch", "delete"},
    }

    generated_contract = build_openapi_contract()
    assert DEFAULT_OPENAPI_PATH.is_file(), "Expected generated docs/openapi.json file"
    committed_contract = json.loads(DEFAULT_OPENAPI_PATH.read_text(encoding="utf-8"))
    assert committed_contract == generated_contract

    security_schemes = generated_contract["components"]["securitySchemes"]
    assert "HTTPBearer" in security_schemes
    assert "ApiErrorResponse" in generated_contract["components"]["schemas"]

    for path, methods in expected_operations.items():
        assert path in generated_contract["paths"], f"Missing OpenAPI path: {path}"
        for method in methods:
            operation = generated_contract["paths"][path][method]
            assert operation["security"] == [{"HTTPBearer": []}]
            for err_status in ("401", "403", "404", "409", "422"):
                err_ref = operation["responses"][err_status]["content"]["application/json"][
                    "schema"
                ]["$ref"]
                assert err_ref == "#/components/schemas/ApiErrorResponse"

    with _build_client(tmp_path) as client:
        live_spec_resp = client.get("/openapi.json")
        assert live_spec_resp.status_code == 200
        live_paths = live_spec_resp.json()["paths"]
        for path in expected_operations:
            assert path in live_paths


def test_full_end_to_end_v1_workflow_with_injected_fakes(tmp_path: Path) -> None:
    with _build_client(tmp_path) as client:
        alice_headers = _auth_headers(ALICE_TOKEN)

        # 1. Create contact & list contacts
        create_contact_resp = client.post(
            "/api/v1/contacts",
            headers=alice_headers,
            json={
                "name": "Dr. Samir Patel",
                "title": "Principal Research Scientist",
                "role": "Industry Mentor",
                "organization": "Helios Labs",
                "context_notes": "Connected via alumni mentorship circle.",
            },
        )
        assert create_contact_resp.status_code == 201
        contact = create_contact_resp.json()
        contact_id = contact["id"]
        assert contact["version"] == 1
        assert contact["created_at"].endswith("Z") or contact["created_at"].endswith("+00:00")

        list_contacts_resp = client.get("/api/v1/contacts", headers=alice_headers)
        assert list_contacts_resp.status_code == 200
        assert list_contacts_resp.json()["total"] == 1
        assert list_contacts_resp.json()["items"][0]["id"] == contact_id

        # 2. Generate brief (passing non-UTC offset timestamp to verify UTC normalization)
        generate_resp = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": contact_id,
                "purpose": "mentorship",
                "tone": "warm_casual",
                "meeting_objective": "Align on transitioning from senior to staff scope.",
                "duration_minutes": 30,
                "scheduled_at": "2026-12-03T16:30:00-05:00",
                "meeting_notes": "First mentorship session of Q4.",
                "preferences": {
                    "preferred_question_count": 4,
                    "communication_style_notes": "Prefer open-ended reflection prompts.",
                    "focus_areas": ["technical strategy", "influence"],
                },
            },
        )
        assert generate_resp.status_code == 201
        brief = generate_resp.json()
        brief_id = brief["id"]
        meeting_id = brief["meeting_id"]
        assert brief["version"] == 1
        assert brief["duration_minutes"] == 30
        assert sum(seg["duration_minutes"] for seg in brief["time_boxed_agenda"]) == 30
        assert len(brief["suggested_questions"]) == 4
        assert all(q["question"] and q["rationale"] for q in brief["suggested_questions"])
        assert brief["suggested_follow_up_topics"]

        # 3. Verify GET /api/v1/meetings and normalized UTC scheduled_at
        meetings_resp = client.get(
            f"/api/v1/meetings?contact_id={contact_id}",
            headers=alice_headers,
        )
        assert meetings_resp.status_code == 200
        meetings_payload = meetings_resp.json()
        assert meetings_payload["total"] == 1
        meeting_item = meetings_payload["items"][0]
        assert meeting_item["id"] == meeting_id
        assert meeting_item["latest_brief_id"] == brief_id
        assert meeting_item["scheduled_at"] in (
            "2026-12-03T21:30:00Z",
            "2026-12-03T21:30:00+00:00",
        )

        # 4. Retrieve brief by ID
        get_brief_resp = client.get(f"/api/v1/briefs/{brief_id}", headers=alice_headers)
        assert get_brief_resp.status_code == 200
        assert get_brief_resp.json()["id"] == brief_id

        # 5. Revise brief with optimistic version check and updated duration/tone
        revise_resp = client.post(
            f"/api/v1/briefs/{brief_id}/revise",
            headers=alice_headers,
            json={
                "instructions": "Tighten agenda to 20 minutes and shift to candid coaching tone.",
                "expected_version": 1,
                "duration_minutes": 20,
                "tone": "candid_coaching",
            },
        )
        assert revise_resp.status_code == 200
        revised_brief = revise_resp.json()
        assert revised_brief["version"] == 2
        assert revised_brief["duration_minutes"] == 20
        assert revised_brief["tone"] == "candid_coaching"
        assert sum(seg["duration_minutes"] for seg in revised_brief["time_boxed_agenda"]) == 20

        # 6. Propose memories — proposals stored separately from approved memories
        propose_resp = client.post(
            "/api/v1/memories/propose",
            headers=alice_headers,
            json={
                "notes": (
                    "Samir recommended writing a one-page vision memo before Q1 planning. "
                    "Follow up next month with a draft outline. "
                    "I prefer direct feedback questions."
                ),
                "meeting_id": meeting_id,
                "brief_id": brief_id,
            },
        )
        assert propose_resp.status_code == 201
        proposals_data = propose_resp.json()
        assert proposals_data["total"] == 3
        first_proposal = proposals_data["proposals"][0]
        assert first_proposal["status"] == "pending"
        assert first_proposal["version"] == 1

        # Approved memories endpoint MUST still be empty prior to approval
        pre_approve_memories = client.get("/api/v1/memories", headers=alice_headers)
        assert pre_approve_memories.status_code == 200
        assert pre_approve_memories.json() == {"items": [], "total": 0}

        # 7. Approve first proposal (with optional user edit)
        proposal_id = first_proposal["id"]
        approve_resp = client.post(
            f"/api/v1/memories/{proposal_id}/approve",
            headers=alice_headers,
            json={
                "expected_version": 1,
                "edited_text": "Samir advises drafting a 1-page vision memo ahead of Q1 planning.",
            },
        )
        assert approve_resp.status_code == 200
        approved_memory = approve_resp.json()
        memory_id = approved_memory["id"]
        assert approved_memory["owner_user_id"] == "usr_alice"
        assert approved_memory["scope"] == "contact"
        assert approved_memory["contact_id"] == contact_id
        assert approved_memory["consent_status"] == "approved"
        assert approved_memory["version"] == 1
        assert approved_memory["source"]["proposal_id"] == proposal_id
        assert approved_memory["source"]["meeting_id"] == meeting_id

        # 8. List approved memories
        list_mem_resp = client.get(
            f"/api/v1/memories?scope=contact&contact_id={contact_id}",
            headers=alice_headers,
        )
        assert list_mem_resp.status_code == 200
        assert list_mem_resp.json()["total"] == 1
        assert list_mem_resp.json()["items"][0]["id"] == memory_id

        # 9. PATCH approved memory with optimistic version check
        patch_resp = client.patch(
            f"/api/v1/memories/{memory_id}",
            headers=alice_headers,
            json={
                "expected_version": 1,
                "text": "Samir advises sharing a 1-page vision memo 48h before Q1 review.",
            },
        )
        assert patch_resp.status_code == 200
        patched_memory = patch_resp.json()
        assert patched_memory["version"] == 2
        assert "48h" in patched_memory["text"]

        # 10. DELETE approved memory
        delete_resp = client.delete(
            f"/api/v1/memories/{memory_id}?expected_version=2",
            headers=alice_headers,
        )
        assert delete_resp.status_code == 204

        after_delete_resp = client.get("/api/v1/memories", headers=alice_headers)
        assert after_delete_resp.status_code == 200
        assert after_delete_resp.json() == {"items": [], "total": 0}


def test_authentication_failures_and_client_user_id_spoofing_rejection(
    tmp_path: Path,
) -> None:
    with _build_client(tmp_path) as client:
        # Missing Authorization header -> 401
        no_auth = client.get(
            "/api/v1/contacts",
            headers={"X-Request-ID": "trace_missing_auth"},
        )
        assert no_auth.status_code == 401
        assert no_auth.headers["WWW-Authenticate"] == "Bearer"
        _assert_error_envelope(
            no_auth.json(),
            expected_code="AUTHENTICATION_REQUIRED",
            expected_trace_id="trace_missing_auth",
        )

        # Wrong auth scheme -> 401
        basic_auth = client.get(
            "/api/v1/contacts",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert basic_auth.status_code == 401
        _assert_error_envelope(basic_auth.json(), expected_code="AUTHENTICATION_REQUIRED")

        # Unknown bearer token -> 401
        bad_token = client.get(
            "/api/v1/meetings",
            headers=_auth_headers("unrecognized-token"),
        )
        assert bad_token.status_code == 401
        _assert_error_envelope(bad_token.json(), expected_code="AUTHENTICATION_REQUIRED")

        # Client attempting to inject user_id / owner_user_id in request body -> 422
        spoof_contact = client.post(
            "/api/v1/contacts",
            headers=_auth_headers(ALICE_TOKEN),
            json={"name": "Spoof Test", "user_id": "usr_bob"},
        )
        assert spoof_contact.status_code == 422
        parsed_err = _assert_error_envelope(
            spoof_contact.json(),
            expected_code="VALIDATION_ERROR",
        )
        assert any("user_id" in detail.field for detail in parsed_err.error.details)

        spoof_propose = client.post(
            "/api/v1/memories/propose",
            headers=_auth_headers(ALICE_TOKEN),
            json={
                "notes": "Trying to spoof owner_user_id on memory proposal.",
                "owner_user_id": "usr_bob",
            },
        )
        assert spoof_propose.status_code == 422
        _assert_error_envelope(spoof_propose.json(), expected_code="VALIDATION_ERROR")


def test_invalid_inputs_missing_records_authorization_and_version_conflicts(
    tmp_path: Path,
) -> None:
    with _build_client(tmp_path) as client:
        alice_headers = _auth_headers(ALICE_TOKEN, request_id="req_alice_trace")
        bob_headers = _auth_headers(BOB_TOKEN, request_id="req_bob_trace")

        # --- Invalid Inputs (422) ---
        # Blank contact name
        blank_name = client.post(
            "/api/v1/contacts",
            headers=alice_headers,
            json={"name": "   "},
        )
        assert blank_name.status_code == 422
        _assert_error_envelope(blank_name.json(), expected_code="VALIDATION_ERROR")

        # Create valid Alice contact for subsequent tests
        alice_contact_id = client.post(
            "/api/v1/contacts",
            headers=alice_headers,
            json={"name": "Nadia Okafor", "organization": "Vertex Orbit"},
        ).json()["id"]

        # Invalid meeting duration (> 180)
        bad_duration = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": alice_contact_id,
                "purpose": "networking",
                "meeting_objective": "Explore distributed ML infrastructure roles.",
                "duration_minutes": 240,
            },
        )
        assert bad_duration.status_code == 422
        _assert_error_envelope(bad_duration.json(), expected_code="VALIDATION_ERROR")

        # Naive scheduled_at date without timezone offset
        naive_date = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": alice_contact_id,
                "purpose": "networking",
                "meeting_objective": "Explore distributed ML infrastructure roles.",
                "duration_minutes": 30,
                "scheduled_at": "2026-12-10T09:00:00",
            },
        )
        assert naive_date.status_code == 422
        _assert_error_envelope(naive_date.json(), expected_code="VALIDATION_ERROR")

        # Invalid ID format in path parameter
        bad_path_id = client.get(
            "/api/v1/briefs/invalid id with spaces",
            headers=alice_headers,
        )
        assert bad_path_id.status_code == 422
        _assert_error_envelope(bad_path_id.json(), expected_code="VALIDATION_ERROR")

        # Incompatible scope=user_preference with contact_id query filter
        bad_mem_filter = client.get(
            f"/api/v1/memories?scope=user_preference&contact_id={alice_contact_id}",
            headers=alice_headers,
        )
        assert bad_mem_filter.status_code == 422
        _assert_error_envelope(bad_mem_filter.json(), expected_code="VALIDATION_ERROR")

        # --- Missing Records (404) ---
        missing_contact_brief = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": "cnt_does_not_exist",
                "purpose": "coffee_chat",
                "meeting_objective": "Catch up on Q4 roadmap.",
                "duration_minutes": 30,
            },
        )
        assert missing_contact_brief.status_code == 404
        _assert_error_envelope(
            missing_contact_brief.json(),
            expected_code="NOT_FOUND",
            expected_trace_id="req_alice_trace",
        )

        assert client.get("/api/v1/briefs/brf_missing", headers=alice_headers).status_code == 404
        assert (
            client.post(
                "/api/v1/briefs/brf_missing/revise",
                headers=alice_headers,
                json={"instructions": "Make shorter.", "expected_version": 1},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/memories/prop_missing/approve",
                headers=alice_headers,
                json={"expected_version": 1},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/v1/memories/mem_missing",
                headers=alice_headers,
                json={"expected_version": 1, "text": "Updated memory text."},
            ).status_code
            == 404
        )
        assert (
            client.delete("/api/v1/memories/mem_missing", headers=alice_headers).status_code == 404
        )

        # Create Alice's brief, proposal, and approved memory to test 403 & 409
        alice_brief = client.post(
            "/api/v1/briefs/generate",
            headers=alice_headers,
            json={
                "contact_id": alice_contact_id,
                "purpose": "networking",
                "meeting_objective": "Learn about ML serving reliability practices.",
                "duration_minutes": 30,
            },
        ).json()
        alice_brief_id = alice_brief["id"]
        alice_meeting_id = alice_brief["meeting_id"]

        alice_proposals = client.post(
            "/api/v1/memories/propose",
            headers=alice_headers,
            json={
                "notes": (
                    "Nadia leads multi-region inference reliability. "
                    "Follow up with latency benchmark questions."
                ),
                "meeting_id": alice_meeting_id,
            },
        ).json()["proposals"]
        pending_proposal_id = alice_proposals[0]["id"]
        second_proposal_id = alice_proposals[1]["id"]

        alice_memory = client.post(
            f"/api/v1/memories/{pending_proposal_id}/approve",
            headers=alice_headers,
            json={"expected_version": 1},
        ).json()
        alice_memory_id = alice_memory["id"]

        # --- Authorization Failures (403) ---
        # Bob sees empty contacts, meetings, and memories lists
        assert client.get("/api/v1/contacts", headers=bob_headers).json()["total"] == 0
        assert client.get("/api/v1/meetings", headers=bob_headers).json()["total"] == 0
        assert client.get("/api/v1/memories", headers=bob_headers).json()["total"] == 0

        # Bob cannot use or mutate any of Alice's resources
        bob_gen = client.post(
            "/api/v1/briefs/generate",
            headers=bob_headers,
            json={
                "contact_id": alice_contact_id,
                "purpose": "coffee_chat",
                "meeting_objective": "Unauthorized access attempt.",
                "duration_minutes": 15,
            },
        )
        assert bob_gen.status_code == 403
        _assert_error_envelope(
            bob_gen.json(),
            expected_code="FORBIDDEN",
            expected_trace_id="req_bob_trace",
        )

        assert (
            client.get(f"/api/v1/briefs/{alice_brief_id}", headers=bob_headers).status_code == 403
        )
        assert (
            client.post(
                f"/api/v1/briefs/{alice_brief_id}/revise",
                headers=bob_headers,
                json={"instructions": "Unauthorized edit.", "expected_version": 1},
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/meetings?contact_id={alice_contact_id}",
                headers=bob_headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/memories/propose",
                headers=bob_headers,
                json={"notes": "Unauthorized meeting reference.", "meeting_id": alice_meeting_id},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/memories/{second_proposal_id}/approve",
                headers=bob_headers,
                json={"expected_version": 1},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/memories/{alice_memory_id}",
                headers=bob_headers,
                json={"expected_version": 1, "text": "Unauthorized memory patch."},
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/v1/memories/{alice_memory_id}",
                headers=bob_headers,
            ).status_code
            == 403
        )

        # --- Optimistic Version & Lifecycle Conflicts (409) ---
        # Revise brief once (v1 -> v2), then send stale expected_version=1
        ok_revise = client.post(
            f"/api/v1/briefs/{alice_brief_id}/revise",
            headers=alice_headers,
            json={"instructions": "Add a question on SLO budgets.", "expected_version": 1},
        )
        assert ok_revise.status_code == 200
        assert ok_revise.json()["version"] == 2

        stale_revise = client.post(
            f"/api/v1/briefs/{alice_brief_id}/revise",
            headers=alice_headers,
            json={"instructions": "Stale revision attempt.", "expected_version": 1},
        )
        assert stale_revise.status_code == 409
        _assert_error_envelope(stale_revise.json(), expected_code="VERSION_CONFLICT")

        # Approving already-approved proposal with stale version=1 -> VERSION_CONFLICT
        stale_approve = client.post(
            f"/api/v1/memories/{pending_proposal_id}/approve",
            headers=alice_headers,
            json={"expected_version": 1},
        )
        assert stale_approve.status_code == 409
        _assert_error_envelope(stale_approve.json(), expected_code="VERSION_CONFLICT")

        # Approving already-approved proposal with current version=2 -> PROPOSAL_NOT_PENDING
        double_approve = client.post(
            f"/api/v1/memories/{pending_proposal_id}/approve",
            headers=alice_headers,
            json={"expected_version": 2},
        )
        assert double_approve.status_code == 409
        _assert_error_envelope(double_approve.json(), expected_code="PROPOSAL_NOT_PENDING")

        # Empty PATCH body without any updatable fields -> 422
        empty_patch = client.patch(
            f"/api/v1/memories/{alice_memory_id}",
            headers=alice_headers,
            json={"expected_version": 1},
        )
        assert empty_patch.status_code == 422
        _assert_error_envelope(empty_patch.json(), expected_code="VALIDATION_ERROR")

        # Valid PATCH (v1 -> v2), then stale PATCH and stale DELETE -> 409
        ok_patch = client.patch(
            f"/api/v1/memories/{alice_memory_id}",
            headers=alice_headers,
            json={
                "expected_version": 1,
                "text": "Nadia leads multi-region inference reliability across three regions.",
            },
        )
        assert ok_patch.status_code == 200
        assert ok_patch.json()["version"] == 2

        stale_patch = client.patch(
            f"/api/v1/memories/{alice_memory_id}",
            headers=alice_headers,
            json={"expected_version": 1, "text": "Stale patch write."},
        )
        assert stale_patch.status_code == 409
        _assert_error_envelope(stale_patch.json(), expected_code="VERSION_CONFLICT")

        stale_delete = client.delete(
            f"/api/v1/memories/{alice_memory_id}?expected_version=1",
            headers=alice_headers,
        )
        assert stale_delete.status_code == 409
        _assert_error_envelope(stale_delete.json(), expected_code="VERSION_CONFLICT")
