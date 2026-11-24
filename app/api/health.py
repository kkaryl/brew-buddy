"""FastAPI health check endpoints with dependency-injected application services."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.application.health_service import HealthCheckService
from app.config import REPO_ROOT, AppSettings, clear_settings_cache, get_settings
from app.infrastructure.auth import RuntimeAuthenticator, build_runtime_authenticator
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.container import build_service_container
from app.tools.coaching_tools import (
    CoachingToolDependencies,
    set_default_coaching_dependencies,
)


def resolve_adc_file_mtime_ns() -> int | None:
    """Return mtime_ns of the active Google Cloud ADC file if present on disk."""
    explicit = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    candidate = (
        Path(explicit)
        if explicit
        else Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    )
    try:
        return candidate.stat().st_mtime_ns if candidate.is_file() else None
    except OSError:
        return None


class HealthResponse(BaseModel):
    """Typed HTTP payload returned by Brew health endpoints."""

    status: Literal["ok", "degraded"] = Field(description="Current operational status.")
    service: str = Field(description="Service name.")
    version: str = Field(description="Application semantic version.")
    environment: str = Field(description="Configured deployment environment.")
    model: str = Field(description="Configured default Gemini model.")
    timestamp_utc: str = Field(description="UTC timestamp in ISO-8601 format.")


router = APIRouter(tags=["system"])


def get_app_settings(request: Request) -> AppSettings:
    """Resolve AppSettings from FastAPI state, hot-reloading unpinned local .env edits."""
    pinned = bool(getattr(request.app.state, "settings_pinned", False))
    state_settings: AppSettings | None = getattr(request.app.state, "settings", None)
    if pinned and state_settings is not None:
        return state_settings

    env_path = REPO_ROOT / ".env"
    current_mtime = env_path.stat().st_mtime_ns if env_path.is_file() else None
    recorded_mtime: int | None = getattr(request.app.state, "env_mtime_ns", None)
    current_adc_mtime = resolve_adc_file_mtime_ns()
    recorded_adc_mtime: int | None = getattr(request.app.state, "adc_mtime_ns", None)

    if (
        state_settings is not None
        and current_mtime == recorded_mtime
        and current_adc_mtime == recorded_adc_mtime
    ):
        return state_settings

    if env_path.is_file():
        load_dotenv(env_path, override=True)
    clear_settings_cache()
    fresh_settings = get_settings()
    request.app.state.settings = fresh_settings
    request.app.state.env_mtime_ns = current_mtime
    request.app.state.adc_mtime_ns = current_adc_mtime

    container = getattr(request.app.state, "service_container", None)
    prior_mock_registry = (
        container.authenticator.mock_registry
        if container is not None and isinstance(container.authenticator, RuntimeAuthenticator)
        else None
    )
    needs_container_rebuild = (
        container is None
        or state_settings is None
        or fresh_settings.persistence_backend != state_settings.persistence_backend
        or fresh_settings.google_cloud_project != state_settings.google_cloud_project
        or fresh_settings.firestore_database != state_settings.firestore_database
        or (
            fresh_settings.persistence_backend == "firestore"
            and current_adc_mtime != recorded_adc_mtime
        )
    )
    if needs_container_rebuild:
        rebuilt = build_service_container(fresh_settings)
        if prior_mock_registry is not None and isinstance(
            rebuilt.authenticator, RuntimeAuthenticator
        ):
            rebuilt.authenticator = build_runtime_authenticator(
                fresh_settings,
                clock=rebuilt.clock,
                mock_registry=prior_mock_registry,
            )
        request.app.state.service_container = rebuilt
        coaching_deps = CoachingToolDependencies(
            preferences_reader=rebuilt.preferences_repo,
            contact_reader=rebuilt.contact_repo,
            meeting_reader=rebuilt.meeting_repo,
            memory_reader=rebuilt.memory_repo,
            proposal_stager=rebuilt.proposal_repo,
            proposal_agent=rebuilt.proposal_agent,
            clock=rebuilt.clock,
            id_generator=rebuilt.id_generator,
            io_timeout_seconds=fresh_settings.firestore_timeout_seconds,
        )
        request.app.state.coaching_tool_dependencies = coaching_deps
        set_default_coaching_dependencies(coaching_deps)
    elif container is not None and isinstance(container.authenticator, RuntimeAuthenticator):
        container.authenticator = build_runtime_authenticator(
            fresh_settings,
            clock=container.clock,
            mock_registry=container.authenticator.mock_registry,
        )
    return fresh_settings


def get_health_service(
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> HealthCheckService:
    """Construct HealthCheckService at the HTTP integration boundary."""
    return HealthCheckService(
        service_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        configured_model=settings.gemini_model,
        clock=SystemUtcClock(),
    )


@router.get("/api/health", response_model=HealthResponse)
@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
def read_health(
    health_service: Annotated[HealthCheckService, Depends(get_health_service)],
) -> HealthResponse:
    """Return current backend health and model readiness metadata."""
    report = health_service.check_health()
    return HealthResponse(
        status="ok" if report.status.value == "ok" else "degraded",
        service=report.service,
        version=report.version,
        environment=report.environment,
        model=report.model,
        timestamp_utc=report.timestamp_utc,
    )
