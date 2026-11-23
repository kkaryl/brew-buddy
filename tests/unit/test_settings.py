"""Unit tests for validated AppSettings configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import AppSettings


def test_default_settings_use_gemini_3_8_flash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("OTEL_TO_CLOUD", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)

    settings = AppSettings()

    assert settings.app_name == "brew"
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.port == 8000
    assert settings.model_workflow_timeout_seconds == 60.0
    assert settings.otel_enabled is False
    assert settings.allow_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_settings_accept_custom_model_and_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("ALLOW_ORIGINS", "https://brew.example.com, http://localhost:4173 ")
    monkeypatch.setenv("OTEL_TO_CLOUD", "true")

    settings = AppSettings()

    assert settings.gemini_model == "gemini-2.5-pro"
    assert settings.port == 8080
    assert settings.otel_enabled is True
    assert settings.allow_origins == [
        "https://brew.example.com",
        "http://localhost:4173",
    ]


def test_settings_reject_blank_model_or_invalid_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        AppSettings(gemini_model="   ")

    with pytest.raises(ValidationError):
        AppSettings(port=70000)
