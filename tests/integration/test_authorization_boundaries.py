"""Exhaustive authorization boundary integration tests across FastAPI v1 and ADK tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from google.adk.tools.tool_context import ToolContext

from app.agents.tools.dependencies import CoachingToolDependencies
from app.agents.tools.registry import build_coaching_tools
from app.api.schemas import ApiErrorResponse
from app.composition.container import FakeServiceContainer
from app.config import AppSettings
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.errors import AuthenticationError
from app.fast_api_app import create_app
from app.infrastructure.stubs.authenticator import FakeAuthenticator

ALICE_TOKEN = "tok_alice_isolated"
BOB_TOKEN = "tok_bob_isolated"
EXPIRED_TOKEN = "tok_expired_session"


class ExpiringAwareAuthenticator(FakeAuthenticator):
    """Authenticator stub distinguishing missing/invalid tokens from expired tokens."""

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        if token.strip() == EXPIRED_TOKEN:
            raise AuthenticationError(
                "Authentication token has expired. Please sign in again.",
                code="TOKEN_EXPIRED",
            )
        return super().authenticate_bearer_token(token)


class AdvancingAuthClock:
    """Deterministic UTC clock for reproducible authorization boundary assertions."""

    def __init__(self) -> None:
        self._now = datetime(2026, 11, 23, 7, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        current = self._now
        self._now = self._now + timedelta(seconds=10)
        return current


def _build_isolated_harness(tmp_path: Path) -> tuple[TestClient, FakeServiceContainer]:
    auth = ExpiringAwareAuthenticator(
        {
            ALICE_TOKEN: AuthenticatedPrincipal(user_id="usr_alice", display_name="Alice Chen"),
            BOB_TOKEN: AuthenticatedPrincipal(user_id="usr_bob", display_name="Bob Rivera"),
        }
    )
    container = FakeServiceContainer(clock=AdvancingAuthClock(), authenticator=auth)
    settings = AppSettings(
        environment="test",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    return TestClient(create_app(settings, service_container=container)), container


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/auth/me", None),
        ("GET", "/api/v1/contacts", None),
        ("POST", "/api/v1/contacts", {"name": "Maya Lin"}),
        ("GET", "/api/v1/meetings", None),
        (
            "POST",
            "/api/v1/briefs/generate",
            {
                "contact_id": "cnt_1",
                "purpose": "coffee_chat",
                "meeting_objective": "Explore incident review practices.",
                "duration_minutes": 30,
            },
        ),
        ("GET", "/api/v1/briefs/brf_1", None),
        ("GET", "/api/v1/briefs/brf_1/revisions", None),
        (
            "POST",
            "/api/v1/briefs/brf_1/revise",
            {"instructions": "Trim to 15 minutes", "expected_version": 1},
        ),
        (
            "POST",
            "/api/v1/memories/propose",
            {"notes": "Discussed AI adoption challenges across teams."},
        ),
        ("GET", "/api/v1/memories/proposals", None),
        ("POST", "/api/v1/memories/prop_1/approve", {}),
        ("POST", "/api/v1/memories/prop_1/reject", {"reason": "Skip"}),
        ("GET", "/api/v1/memories", None),
        ("PATCH", "/api/v1/memories/mem_1", {"expected_version": 1, "text": "Updated text"}),
        ("DELETE", "/api/v1/memories/mem_1", None),
    ],
)
def test_every_v1_endpoint_enforces_missing_invalid_and_expired_token_boundaries(
    tmp_path: Path,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    client, _ = _build_isolated_harness(tmp_path)
    with client:
        # 1. Missing Authorization header -> 401 AUTHENTICATION_REQUIRED
        unauth_resp = client.request(method, path, json=body)
        assert unauth_resp.status_code == 401
        parsed_unauth = ApiErrorResponse.model_validate(unauth_resp.json())
        assert parsed_unauth.error.code == "AUTHENTICATION_REQUIRED"

        # 2. Malformed non-Bearer scheme -> 401 AUTHENTICATION_REQUIRED
        basic_resp = client.request(
            method,
            path,
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            json=body,
        )
        assert basic_resp.status_code == 401
        assert ApiErrorResponse.model_validate(basic_resp.json()).error.code == (
            "AUTHENTICATION_REQUIRED"
        )

        # 3. Unrecognized Bearer token -> 401 AUTHENTICATION_REQUIRED
        bad_tok_resp = client.request(
            method,
            path,
            headers=_bearer("unrecognized-token"),
            json=body,
        )
        assert bad_tok_resp.status_code == 401
        assert ApiErrorResponse.model_validate(bad_tok_resp.json()).error.code == (
            "AUTHENTICATION_REQUIRED"
        )

        # 4. Expired Bearer token -> 401 TOKEN_EXPIRED
        exp_resp = client.request(
            method,
            path,
            headers=_bearer(EXPIRED_TOKEN),
            json=body,
        )
        assert exp_resp.status_code == 401
        assert ApiErrorResponse.model_validate(exp_resp.json()).error.code == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_cross_tenant_isolation_blocks_horizontal_access_across_all_resources_and_tools(
    tmp_path: Path,
) -> None:
    client, container = _build_isolated_harness(tmp_path)
    with client:
        # Alice creates a contact, brief, pending proposal, and approved memory
        contact_resp = client.post(
            "/api/v1/contacts",
            headers=_bearer(ALICE_TOKEN),
            json={
                "name": "Alex Morgan",
                "title": "Staff ML Engineer",
                "organization": "Northstar Systems",
                "context_notes": "Private Alice relationship notes.",
            },
        )
        assert contact_resp.status_code == 201
        alice_contact_id = contact_resp.json()["id"]

        brief_resp = client.post(
            "/api/v1/briefs/generate",
            headers=_bearer(ALICE_TOKEN),
            json={
                "contact_id": alice_contact_id,
                "purpose": "coffee_chat",
                "meeting_objective": "Discuss production evaluation pipelines.",
                "duration_minutes": 30,
            },
        )
        assert brief_resp.status_code == 201
        alice_brief_id = brief_resp.json()["id"]
        alice_meeting_id = brief_resp.json()["meeting_id"]

        propose_resp = client.post(
            "/api/v1/memories/propose",
            headers=_bearer(ALICE_TOKEN),
            json={
                "notes": (
                    "We discussed his team's challenges adopting AI. "
                    "He recommended exploring evaluation pipelines."
                ),
                "contact_id": alice_contact_id,
                "meeting_id": alice_meeting_id,
                "brief_id": alice_brief_id,
            },
        )
        assert propose_resp.status_code == 201
        proposals = propose_resp.json()["proposals"]
        assert len(proposals) >= 2
        proposal_to_approve = proposals[0]["id"]
        pending_proposal_id = proposals[1]["id"]

        approve_resp = client.post(
            f"/api/v1/memories/{proposal_to_approve}/approve",
            headers=_bearer(ALICE_TOKEN),
            json={"expected_version": 1},
        )
        assert approve_resp.status_code == 200
        alice_memory_id = approve_resp.json()["id"]

        # Bob's list endpoints must return strictly 0 of Alice's records
        assert client.get("/api/v1/contacts", headers=_bearer(BOB_TOKEN)).json()["total"] == 0
        assert client.get("/api/v1/meetings", headers=_bearer(BOB_TOKEN)).json()["total"] == 0
        assert (
            client.get("/api/v1/memories/proposals", headers=_bearer(BOB_TOKEN)).json()["total"]
            == 0
        )
        assert client.get("/api/v1/memories", headers=_bearer(BOB_TOKEN)).json()["total"] == 0

        # Bob targeting Alice's IDs across every endpoint MUST receive 403 FORBIDDEN
        forbidden_attempts: list[tuple[str, str, dict[str, Any] | None]] = [
            ("GET", f"/api/v1/meetings?contact_id={alice_contact_id}", None),
            (
                "POST",
                "/api/v1/briefs/generate",
                {
                    "contact_id": alice_contact_id,
                    "purpose": "networking",
                    "meeting_objective": "Attempt cross-tenant brief generation.",
                    "duration_minutes": 30,
                },
            ),
            ("GET", f"/api/v1/briefs/{alice_brief_id}", None),
            ("GET", f"/api/v1/briefs/{alice_brief_id}/revisions", None),
            (
                "POST",
                f"/api/v1/briefs/{alice_brief_id}/revise",
                {"instructions": "Shorten to 15 minutes", "expected_version": 1},
            ),
            (
                "POST",
                "/api/v1/memories/propose",
                {
                    "notes": "Attempt cross-tenant proposal attachment.",
                    "contact_id": alice_contact_id,
                },
            ),
            (
                "POST",
                "/api/v1/memories/propose",
                {
                    "notes": "Attempt cross-tenant meeting attachment.",
                    "meeting_id": alice_meeting_id,
                },
            ),
            ("GET", f"/api/v1/memories/proposals?contact_id={alice_contact_id}", None),
            (
                "POST",
                f"/api/v1/memories/{pending_proposal_id}/approve",
                {"expected_version": 1},
            ),
            (
                "POST",
                f"/api/v1/memories/{pending_proposal_id}/reject",
                {"expected_version": 1, "reason": "Unauthorized reject"},
            ),
            ("GET", f"/api/v1/memories?contact_id={alice_contact_id}", None),
            (
                "PATCH",
                f"/api/v1/memories/{alice_memory_id}",
                {"expected_version": 1, "text": "Tampered memory text"},
            ),
            ("DELETE", f"/api/v1/memories/{alice_memory_id}", None),
        ]

        for method, path, body in forbidden_attempts:
            resp = client.request(method, path, headers=_bearer(BOB_TOKEN), json=body)
            assert resp.status_code == 403, (
                f"Expected 403 for Bob on {method} {path}, got {resp.status_code}"
            )
            err = ApiErrorResponse.model_validate(resp.json())
            assert err.error.code == "FORBIDDEN"
            assert "Private Alice" not in err.error.message

        # Client payload spoofing of user_id / owner_user_id -> 422 VALIDATION_ERROR
        spoofed_requests: list[tuple[str, str, dict[str, Any]]] = [
            ("POST", "/api/v1/contacts", {"name": "Spoof", "owner_user_id": "usr_alice"}),
            (
                "POST",
                "/api/v1/briefs/generate",
                {
                    "contact_id": alice_contact_id,
                    "purpose": "coffee_chat",
                    "meeting_objective": "Spoof test",
                    "duration_minutes": 30,
                    "user_id": "usr_alice",
                },
            ),
            (
                "POST",
                f"/api/v1/briefs/{alice_brief_id}/revise",
                {
                    "instructions": "Trim agenda",
                    "expected_version": 1,
                    "owner_user_id": "usr_alice",
                },
            ),
            (
                "POST",
                "/api/v1/memories/propose",
                {"notes": "Valid note length", "user_id": "usr_alice"},
            ),
            (
                "PATCH",
                f"/api/v1/memories/{alice_memory_id}",
                {"expected_version": 1, "text": "Clean", "owner_user_id": "usr_bob"},
            ),
        ]
        for method, path, spoof_body in spoofed_requests:
            spoof_resp = client.request(
                method,
                path,
                headers=_bearer(ALICE_TOKEN),
                json=spoof_body,
            )
            assert spoof_resp.status_code == 422
            assert ApiErrorResponse.model_validate(spoof_resp.json()).error.code == (
                "VALIDATION_ERROR"
            )

        # Verify Alice's resources remain completely intact after Bob's blocked attempts
        alice_mem_check = client.get("/api/v1/memories", headers=_bearer(ALICE_TOKEN))
        assert alice_mem_check.status_code == 200
        assert alice_mem_check.json()["total"] == 1

    # Also verify ADK CoachingTools enforce identical cross-tenant FORBIDDEN boundaries
    deps = CoachingToolDependencies(
        preferences_reader=container.preferences_repo,
        contact_reader=container.contact_repo,
        meeting_reader=container.meeting_repo,
        memory_reader=container.memory_repo,
        proposal_stager=container.proposal_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
    )
    tools_by_name = {t.name: t for t in build_coaching_tools(deps)}
    bob_ctx = cast(
        ToolContext,
        SimpleNamespace(
            user_id="usr_bob",
            session=SimpleNamespace(id="ses_bob_01", user_id="usr_bob"),
            agent_name="conversation_coach",
            function_call_id="fc_bob_01",
        ),
    )

    for tool_name, args in (
        ("get_contact_context", {"contact_id": alice_contact_id}),
        ("get_meeting_history", {"contact_id": alice_contact_id}),
        (
            "suggest_memory_candidates",
            {"notes": "Attempt cross-tenant staging", "contact_id": alice_contact_id},
        ),
    ):
        tool_result = await tools_by_name[tool_name].run_async(args=args, tool_context=bob_ctx)
        assert tool_result["status"] == "error"
        assert tool_result["error"]["code"] == "FORBIDDEN"


def test_deployed_auth_surface_disables_mock_sessions_cleanly(tmp_path: Path) -> None:
    prod_settings = AppSettings(
        environment="production",
        otel_to_cloud=False,
        google_oauth_client_id="prod-web-client.apps.googleusercontent.com",
        web_dist_dir=tmp_path / "no-dist",
    )
    with TestClient(create_app(prod_settings)) as prod_client:
        cfg_resp = prod_client.get("/api/auth/config")
        assert cfg_resp.status_code == 200
        cfg = cfg_resp.json()
        assert cfg["auth_mode"] == "verified"
        assert cfg["local_mock_enabled"] is False
        assert cfg["mock_personas"] == []

        mock_resp = prod_client.post("/api/auth/mock-session", json={"persona_id": "alice"})
        assert mock_resp.status_code == 403
        err = ApiErrorResponse.model_validate(mock_resp.json())
        assert err.error.code == "MOCK_AUTH_DISABLED"
