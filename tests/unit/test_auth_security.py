"""Unit and FastAPI integration tests for verified authentication and deployment mock lockout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppSettings
from app.domain.errors import AuthenticationError
from app.fast_api_app import create_app
from app.infrastructure.auth import (
    FirebaseGoogleTokenAuthenticator,
    RuntimeAuthenticator,
    build_runtime_authenticator,
)
from app.infrastructure.fakes import FakeServiceContainer


class ManualUtcClock:
    """Mutable UTC clock for deterministic session TTL expiration tests."""

    def __init__(self, initial: datetime | None = None) -> None:
        self.current = initial or datetime(2026, 11, 23, 2, 0, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current = self.current + timedelta(seconds=seconds)


def test_settings_forbid_local_mock_auth_in_production_staging_or_cloud_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)

    with pytest.raises(ValidationError, match="local_mock"):
        AppSettings(environment="production", auth_mode="local_mock", otel_to_cloud=False)

    with pytest.raises(ValidationError, match="local_mock"):
        AppSettings(environment="staging", auth_mode="local_mock", otel_to_cloud=False)

    monkeypatch.setenv("K_SERVICE", "brew-cloud-run-service")
    with pytest.raises(ValidationError, match="local_mock"):
        AppSettings(environment="local", auth_mode="local_mock", otel_to_cloud=False)


def test_deployed_environment_disables_mock_sessions_and_requires_verified_jwt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)

    def fake_firebase_verifier(token: str) -> dict[str, object]:
        if token == "header.valid_firebase.sig":
            return {
                "user_id": "fb_user_99",
                "name": "Verified Priya",
                "email": "priya@example.com",
            }
        if token == "header.expired_firebase.sig":
            raise ValueError("Token expired: 1700000000 < 1700003600")
        raise ValueError("Invalid token signature")

    settings = AppSettings(
        environment="production",
        firebase_project_id="brew-prod-proj",
        firebase_web_api_key="AIzaPublicFirebaseWebKeyPlaceholder",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    assert settings.local_mock_auth_enabled is False

    runtime_auth: RuntimeAuthenticator = build_runtime_authenticator(
        settings,
        firebase_verifier_override=fake_firebase_verifier,
    )
    container = FakeServiceContainer(authenticator=runtime_auth)

    with TestClient(create_app(settings, service_container=container)) as client:
        # 1. Public auth config exposes non-secret Firebase web settings and hides mock personas
        cfg_resp = client.get("/api/auth/config")
        assert cfg_resp.status_code == 200
        cfg = cfg_resp.json()
        assert cfg["auth_mode"] == "verified"
        assert cfg["local_mock_enabled"] is False
        assert cfg["mock_personas"] == []
        assert cfg["google_sign_in_enabled"] is True
        assert cfg["firebase"]["project_id"] == "brew-prod-proj"

        # 2. Local mock session endpoint is strictly blocked in production (403)
        mock_attempt = client.post("/api/auth/mock-session", json={"persona_id": "alice"})
        assert mock_attempt.status_code == 403
        assert mock_attempt.json()["error"]["code"] == "MOCK_AUTH_DISABLED"

        # 3. Developer fake tokens are rejected in production (401)
        dev_tok_resp = client.get(
            "/api/v1/contacts",
            headers={"Authorization": "Bearer brew-dev-token-alice"},
        )
        assert dev_tok_resp.status_code == 401

        # 4. Expired Firebase JWT returns 401 with TOKEN_EXPIRED code
        expired_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer header.expired_firebase.sig"},
        )
        assert expired_resp.status_code == 401
        assert expired_resp.headers["WWW-Authenticate"] == "Bearer"
        assert expired_resp.json()["error"]["code"] == "TOKEN_EXPIRED"

        # 5. Valid Firebase JWT resolves isolated firebase:<uid> principal
        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer header.valid_firebase.sig"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json() == {
            "user_id": "firebase:fb_user_99",
            "display_name": "Verified Priya",
            "auth_provider": "verified",
        }


def test_google_oidc_verifier_and_invalid_issuer_rejection() -> None:
    def fake_google_verifier(token: str) -> dict[str, object]:
        if token == "hdr.good_google.sig":
            return {
                "iss": "https://accounts.google.com",
                "sub": "10987654321",
                "email": "jordan@example.org",
            }
        if token == "hdr.bad_issuer.sig":
            return {
                "iss": "https://evil.example.com",
                "sub": "10987654321",
            }
        raise ValueError("Invalid Google token")

    auth = FirebaseGoogleTokenAuthenticator(
        google_oauth_client_id="client-123.apps.googleusercontent.com",
        google_verifier_override=fake_google_verifier,
    )
    principal = auth.authenticate_bearer_token("hdr.good_google.sig")
    assert principal.user_id == "google:10987654321"
    assert principal.display_name == "jordan"

    with pytest.raises(AuthenticationError, match="issuer"):
        auth.authenticate_bearer_token("hdr.bad_issuer.sig")


def test_local_mock_sessions_enforce_isolation_expiry_and_logout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    clock = ManualUtcClock()
    settings = AppSettings(
        environment="local",
        mock_session_ttl_seconds=120,
        brief_coach_backend="fake",
        memory_extractor_backend="fake",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    runtime_auth = build_runtime_authenticator(settings, clock=clock)
    container = FakeServiceContainer(clock=clock, authenticator=runtime_auth)

    with TestClient(create_app(settings, service_container=container)) as client:
        alice_ses = client.post("/api/auth/mock-session", json={"persona_id": "alice"})
        assert alice_ses.status_code == 201
        alice_token = alice_ses.json()["access_token"]
        assert alice_token.startswith("mses_")
        assert alice_ses.json()["principal"]["user_id"] == "usr_mock_alice"
        assert alice_ses.json()["principal"]["auth_provider"] == "local_mock"

        bob_ses = client.post("/api/auth/mock-session", json={"persona_id": "bob"})
        assert bob_ses.status_code == 201
        bob_token = bob_ses.json()["access_token"]

        # Create contact under Alice's isolated mock namespace; Bob sees 0 contacts
        created = client.post(
            "/api/v1/contacts",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"name": "Alex Morgan"},
        )
        assert created.status_code == 201
        assert (
            client.get(
                "/api/v1/contacts",
                headers={"Authorization": f"Bearer {bob_token}"},
            ).json()["total"]
            == 0
        )

        # Advance clock past 120s TTL -> Alice's session expires with 401 TOKEN_EXPIRED
        clock.advance(125)
        expired_check = client.get(
            "/api/v1/contacts",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert expired_check.status_code == 401
        assert expired_check.json()["error"]["code"] == "TOKEN_EXPIRED"

        # Issue fresh Bob session and revoke via /api/auth/logout
        fresh_bob = client.post("/api/auth/mock-session", json={"persona_id": "bob"}).json()[
            "access_token"
        ]
        logout_resp = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {fresh_bob}"},
        )
        assert logout_resp.status_code == 204
        after_logout = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {fresh_bob}"},
        )
        assert after_logout.status_code == 401


def test_google_oauth_client_id_quote_cleaning_and_popup_access_token_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)

    settings = AppSettings(
        environment="local",
        google_oauth_client_id='  "987654321-web.apps.googleusercontent.com"  ',
        brief_coach_backend="fake",
        memory_extractor_backend="fake",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    assert settings.google_oauth_client_id == "987654321-web.apps.googleusercontent.com"

    placeholder_settings = AppSettings(
        environment="local",
        google_oauth_client_id="your-google-oauth-web-client-id.apps.googleusercontent.com",
        otel_to_cloud=False,
    )
    assert placeholder_settings.google_oauth_client_id is None

    # Synthetic non-JWT bearer tokens for unit testing only (never real credentials).
    valid_test_oauth_token = "oauth_test.valid_popup_oauth_token"
    wrong_client_test_token = "oauth_test.wrong_client_token"

    def fake_access_token_verifier(token: str) -> dict[str, object]:
        if token == valid_test_oauth_token:
            return {
                "sub": "112233445566",
                "name": "Kary Long",
                "email": "kary@example.com",
            }
        raise AuthenticationError("Audience mismatch", code="AUTHENTICATION_REQUIRED")

    runtime_auth = build_runtime_authenticator(
        settings,
        google_access_token_verifier_override=fake_access_token_verifier,
    )
    container = FakeServiceContainer(authenticator=runtime_auth)

    with TestClient(create_app(settings, service_container=container)) as client:
        cfg = client.get("/api/auth/config").json()
        assert cfg["google_sign_in_enabled"] is True
        assert cfg["google_oauth_client_id"] == "987654321-web.apps.googleusercontent.com"

        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {valid_test_oauth_token}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json() == {
            "user_id": "google:112233445566",
            "display_name": "Kary Long",
            "auth_provider": "verified",
        }

        bad_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {wrong_client_test_token}"},
        )
        assert bad_resp.status_code == 401


def test_deployed_adk_and_memory_routes_enforce_auth_ownership_and_hitl_governance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)

    def fake_firebase_verifier(token: str) -> dict[str, object]:
        if token == "hdr.alice_prod.sig":
            return {"user_id": "uid_alice", "name": "Alice Prod"}
        raise ValueError("Invalid token")

    def fake_iap_verifier(assertion: str) -> dict[str, object]:
        if assertion == "hdr.valid_iap.sig":
            return {
                "iss": "https://cloud.google.com/iap",
                "sub": "accounts.google.com:99887766",
                "email": "iap-user@example.com",
            }
        raise ValueError("Invalid IAP assertion")

    settings = AppSettings(
        environment="production",
        persistence_backend="in_memory",
        session_backend="in_memory",
        firebase_project_id="brew-prod",
        iap_jwt_audience="/projects/123456/locations/us-east1/services/brew",
        app_url="https://brew-123456.us-east1.run.app",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    runtime_auth = build_runtime_authenticator(
        settings,
        firebase_verifier_override=fake_firebase_verifier,
        iap_verifier_override=fake_iap_verifier,
    )
    container = FakeServiceContainer(authenticator=runtime_auth)

    with TestClient(create_app(settings, service_container=container)) as client:
        # Readiness probe passes when verified auth provider and ADK runner are ready
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # 1. Raw ADK writable memory route is NEVER publicly writable (401 without auth)
        unauth_mem = client.patch(
            "/apps/app/users/firebase:uid_alice/memory",
            json={"session_id": "s1"},
        )
        assert unauth_mem.status_code == 401
        assert unauth_mem.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

        # 2. Even with valid auth, direct ungoverned ADK memory writes are rejected (403)
        governed_block = client.patch(
            "/apps/app/users/firebase:uid_alice/memory",
            headers={"Authorization": "Bearer hdr.alice_prod.sig"},
            json={"session_id": "s1"},
        )
        assert governed_block.status_code == 403
        assert governed_block.json()["error"]["code"] == "UNGOVERNED_MEMORY_WRITE_DISABLED"

        # 3. Unauthenticated ADK / A2A invocation routes reject in deployed mode (401)
        for method, path, payload in (
            ("GET", "/list-apps", None),
            ("POST", "/apps/app/users/firebase:uid_alice/sessions", {}),
            (
                "POST",
                "/run",
                {
                    "app_name": "app",
                    "user_id": "firebase:uid_alice",
                    "session_id": "s1",
                    "new_message": {"role": "user", "parts": [{"text": "Hi"}]},
                },
            ),
            ("POST", "/run_sse", {"app_name": "app", "user_id": "firebase:uid_alice"}),
            ("POST", "/a2a/app", {"jsonrpc": "2.0", "id": "1", "method": "tasks/get"}),
        ):
            resp = client.request(method, path, json=payload)
            assert resp.status_code == 401, (
                f"Expected 401 on {method} {path}, got {resp.status_code}"
            )

        # 4. Cross-user ADK session/run spoofing is blocked with 403 FORBIDDEN
        cross_session = client.post(
            "/apps/app/users/firebase:uid_other/sessions",
            headers={"Authorization": "Bearer hdr.alice_prod.sig"},
            json={},
        )
        assert cross_session.status_code == 403
        assert cross_session.json()["error"]["code"] == "FORBIDDEN"

        cross_run = client.post(
            "/run",
            headers={"Authorization": "Bearer hdr.alice_prod.sig"},
            json={
                "app_name": "app",
                "user_id": "firebase:uid_other",
                "session_id": "s1",
                "new_message": {"role": "user", "parts": [{"text": "Hi"}]},
            },
        )
        assert cross_run.status_code == 403
        assert cross_run.json()["error"]["code"] == "FORBIDDEN"

        # 5. Authenticated owner can create their own ADK session
        own_session = client.post(
            "/apps/app/users/firebase:uid_alice/sessions",
            headers={"Authorization": "Bearer hdr.alice_prod.sig"},
            json={},
        )
        assert own_session.status_code == 200

        # 6. Verified Cloud Run IAP JWT assertion resolves isolated iap:<sub> principal
        iap_me = client.get(
            "/api/v1/auth/me",
            headers={"X-Goog-IAP-JWT-Assertion": "hdr.valid_iap.sig"},
        )
        assert iap_me.status_code == 200
        assert iap_me.json() == {
            "user_id": "iap:99887766",
            "display_name": "iap-user",
            "auth_provider": "verified",
        }


def test_readiness_returns_503_when_deployed_without_verified_auth_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    unconfigured_prod = AppSettings(
        environment="production",
        persistence_backend="in_memory",
        session_backend="in_memory",
        google_cloud_project="your-gcp-project-id",
        firebase_project_id="",
        google_oauth_client_id="",
        iap_jwt_audience="",
        app_url="",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "no-dist",
    )
    with TestClient(create_app(unconfigured_prod)) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        body = ready.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["auth_ready"] is False
