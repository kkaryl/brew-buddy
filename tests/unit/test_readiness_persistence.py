"""A deployed service must not report ready on storage that forgets everything on restart."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.fast_api_app import create_app


def _settings(tmp_path: Path, **overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "environment": "production",
        "persistence_backend": "in_memory",
        "session_backend": "in_memory",
        "firebase_project_id": "brew-prod",
        "otel_to_cloud": False,
        "web_dist_dir": tmp_path / "no-dist",
    }
    values.update(overrides)
    return AppSettings.model_validate(values)


@pytest.mark.parametrize(
    ("environment", "backend", "allow_ephemeral", "expected"),
    [
        ("production", "in_memory", False, False),
        ("staging", "in_memory", False, False),
        ("production", "in_memory", True, True),
        ("production", "firestore", False, True),
        ("local", "in_memory", False, True),
        ("test", "in_memory", False, True),
    ],
)
def test_ephemeral_storage_is_acceptable_only_outside_deployment_or_by_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: str,
    backend: str,
    allow_ephemeral: bool,
    expected: bool,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    settings = _settings(
        tmp_path,
        environment=environment,
        persistence_backend=backend,
        allow_ephemeral_persistence=allow_ephemeral,
    )

    assert settings.persistence_is_acceptable_for_environment is expected


def test_cloud_run_marker_counts_as_deployed_even_when_app_env_is_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("K_SERVICE", "brew")
    settings = _settings(tmp_path, environment="local", auth_mode="auto")

    assert settings.persistence_is_acceptable_for_environment is False


def test_deployed_service_on_in_memory_storage_fails_its_readiness_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)

    with TestClient(create_app(_settings(tmp_path))) as client:
        ready = client.get("/readyz")

    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not_ready"
    assert body["persistence_backend"] == "in_memory"
    assert body["checks"]["persistence_ready"] is False
    assert body["checks"]["auth_ready"] is True


def test_explicit_opt_in_lets_a_deployed_smoke_instance_report_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    settings = _settings(tmp_path, allow_ephemeral_persistence=True)

    with TestClient(create_app(settings)) as client:
        ready = client.get("/readyz")

    assert ready.status_code == 200
    assert ready.json()["checks"]["persistence_ready"] is True
