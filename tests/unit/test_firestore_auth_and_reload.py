"""Unit tests for fast Firestore ADC failure diagnostics and live container hot-reload."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError
from google.cloud import firestore

import app.api.health as health_module
from app.api.auth import router as auth_router
from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.routers.api_v1 import router as v1_router
from app.composition.builders import build_service_container
from app.config import AppSettings
from app.domain.shared.errors import PersistenceOperationError
from app.infrastructure.firestore.contacts import FirestoreContactRepository


class _ExpiredAdcCredentials(Credentials):
    """Test credential double simulating an expired Cloudtop ADC RAPT session."""

    def __init__(self) -> None:
        init_fn: Any = super().__init__
        init_fn()
        self.token = None

    @property
    def valid(self) -> bool:
        return False

    def refresh(self, request: Any) -> None:
        del request
        err_cls: Any = RefreshError
        raise err_cls(
            "Reauthentication is needed. Please run "
            "`gcloud auth application-default login` to reauthenticate."
        )


class _HangingFirestoreClient:
    """Fake Firestore AsyncClient whose RPC coroutine would hang if awaited without precheck."""

    def __init__(self, credentials: Any) -> None:
        self._credentials = credentials

    def collection(self, _name: str) -> Any:
        doc_mock = MagicMock()
        subcoll_mock = MagicMock()

        async def _never_returns() -> list[Any]:
            import asyncio

            await asyncio.sleep(30.0)
            return []

        subcoll_mock.get = _never_returns
        doc_mock.collection.return_value = subcoll_mock
        coll_mock = MagicMock()
        coll_mock.document.return_value = doc_mock
        return coll_mock


@pytest.mark.asyncio
async def test_firestore_contact_list_fails_fast_with_actionable_reauth_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    client = cast(firestore.AsyncClient, _HangingFirestoreClient(_ExpiredAdcCredentials()))
    repo = FirestoreContactRepository(client, timeout_seconds=10.0)

    with pytest.raises(PersistenceOperationError) as exc_info:
        await repo.list_by_owner("usr_alice")

    message = exc_info.value.message
    assert "gcloud auth application-default login" in message
    assert "BREW_PERSISTENCE_BACKEND=in_memory" in message


@pytest.mark.asyncio
async def test_firestore_emulator_skips_adc_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8085")
    client = MagicMock()
    client._credentials = _ExpiredAdcCredentials()

    async def _empty_get() -> list[Any]:
        return []

    subcoll = MagicMock()
    subcoll.get = _empty_get
    client.collection.return_value.document.return_value.collection.return_value = subcoll

    repo = FirestoreContactRepository(client, timeout_seconds=2.0)
    result = await repo.list_by_owner("usr_alice")
    assert result == []


def test_env_and_adc_update_rebuilds_container_and_preserves_mock_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("BREW_AUTH_MODE", "auto")
    monkeypatch.setenv("BREW_PERSISTENCE_BACKEND", "in_memory")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "brew-initial-project")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=local\nBREW_AUTH_MODE=auto\nBREW_PERSISTENCE_BACKEND=in_memory\n",
        encoding="utf-8",
    )
    adc_file = tmp_path / "adc.json"
    adc_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(health_module, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc_file))

    initial_settings = AppSettings(
        APP_ENV="local",
        BREW_AUTH_MODE="auto",
        BREW_PERSISTENCE_BACKEND="in_memory",
        BREW_BRIEF_COACH_BACKEND="fake",
        BREW_MEMORY_EXTRACTOR_BACKEND="fake",
    )
    app = FastAPI()
    app.state.settings = initial_settings
    app.state.settings_pinned = False
    app.state.env_mtime_ns = env_file.stat().st_mtime_ns
    app.state.adc_mtime_ns = adc_file.stat().st_mtime_ns
    initial_container = build_service_container(initial_settings)
    app.state.service_container = initial_container

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(v1_router)

    test_client = TestClient(app)

    # Create a local mock session before triggering a container hot-reload
    session_resp = test_client.post("/api/auth/mock-session", json={"persona_id": "alice"})
    assert session_resp.status_code == 201
    token = session_resp.json()["access_token"]

    # Simulate an .env update changing project ID so container rebuilds cleanly
    env_file.write_text(
        "APP_ENV=local\n"
        "BREW_AUTH_MODE=auto\n"
        "BREW_PERSISTENCE_BACKEND=in_memory\n"
        "GOOGLE_CLOUD_PROJECT=brew-reloaded-project\n",
        encoding="utf-8",
    )
    app.state.env_mtime_ns = 1

    contacts_resp = test_client.get(
        "/api/v1/contacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert contacts_resp.status_code == 200
    assert contacts_resp.json()["items"] == []
    assert app.state.service_container is not initial_container
