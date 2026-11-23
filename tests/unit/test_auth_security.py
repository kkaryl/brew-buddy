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
