"""Deterministic FastAPI integration tests covering health, ADK/A2A wiring, and SPA hosting."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppSettings
from app.fast_api_app import create_app


def test_health_and_adk_a2a_surfaces(tmp_path: Path) -> None:
    settings = AppSettings(
        environment="test",
        gemini_model="gemini-3.8-flash",
        otel_to_cloud=False,
        web_dist_dir=tmp_path / "missing-dist",
    )
    fastapi_app = create_app(settings)

    with TestClient(fastapi_app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        payload = health.json()
        assert payload["status"] == "ok"
        assert payload["service"] == "brew"
        assert payload["environment"] == "test"
        assert payload["model"] == "gemini-3.8-flash"

        readiness = client.get("/healthz")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "ok"

        ready_probe = client.get("/readyz")
        assert ready_probe.status_code == 200
        ready_body = ready_probe.json()
        assert ready_body["status"] == "ready"
        assert ready_body["checks"] == {
            "config_loaded": True,
            "agent_runner_initialized": True,
            "persistence_ready": True,
            "auth_ready": True,
        }

        apps_resp = client.get("/list-apps")
        assert apps_resp.status_code == 200
        assert "app" in apps_resp.json()

        card_resp = client.get("/a2a/app/.well-known/agent-card.json")
        assert card_resp.status_code == 200
        card = card_resp.json()
        assert card["name"] == "conversation_coach"
        assert "supportedInterfaces" in card


def test_static_spa_serving_when_dist_present(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>Brew SPA</div></body></html>",
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('brew');", encoding="utf-8")

    settings = AppSettings(
        environment="production",
        otel_to_cloud=False,
        web_dist_dir=dist_dir,
    )
    fastapi_app = create_app(settings)

    with TestClient(fastapi_app) as client:
        root_resp = client.get("/")
        assert root_resp.status_code == 200
        assert "Brew SPA" in root_resp.text

        asset_resp = client.get("/assets/app.js")
        assert asset_resp.status_code == 200
        assert "console.log('brew');" in asset_resp.text

        client_route_resp = client.get("/workspace/session-1")
        assert client_route_resp.status_code == 200
        assert "Brew SPA" in client_route_resp.text

        missing_api_resp = client.get("/api/does-not-exist")
        assert missing_api_resp.status_code == 404

        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"
