"""FastAPI health check endpoints with dependency-injected application services."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Request, Response, status
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


class ReadinessChecksResponse(BaseModel):
    """Individual subsystem checks evaluated by Brew readiness probes."""

    config_loaded: bool = Field(description="True when runtime settings validated cleanly.")
    agent_runner_initialized: bool = Field(
        description="True when ADK Conversation Coach runner and session service are attached."
    )
    persistence_ready: bool = Field(
        description="True when the configured persistence adapter is initialized."
    )
    auth_ready: bool = Field(
        description="True when authentication enforcement is properly configured for this env."
    )


class ReadinessResponse(BaseModel):
    """Typed HTTP payload returned by Brew startup and readiness probe endpoints."""

    status: Literal["ready", "not_ready"] = Field(description="Overall traffic readiness state.")
    service: str = Field(description="Service name.")
    version: str = Field(description="Application semantic version.")
    environment: str = Field(description="Configured deployment environment.")
    persistence_backend: str = Field(description="Active persistence backend name.")
    checks: ReadinessChecksResponse = Field(description="Component readiness breakdown.")
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


@router.get("/api/ready", response_model=ReadinessResponse, include_in_schema=False)
@router.get("/readyz", response_model=ReadinessResponse, include_in_schema=False)
def read_readiness(
    request: Request,
    response: Response,
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> ReadinessResponse:
    """Evaluate Cloud Run startup and traffic readiness across ADK, auth, and persistence."""
    container = getattr(request.app.state, "service_container", None)
    if container is None:
        container = build_service_container(settings)
        request.app.state.service_container = container

    agent_runner_initialized = (
        getattr(request.app.state, "runner", None) is not None
        and getattr(request.app.state, "session_service", None) is not None
    )

    if settings.persistence_backend == "firestore":
        persistence_ready = container.memory_repo is not None and container.brief_repo is not None
    else:
        persistence_ready = True

    if settings.local_mock_auth_enabled:
        auth_ready = True
    elif isinstance(container.authenticator, RuntimeAuthenticator):
        auth_ready = container.authenticator.is_verified_provider_configured
    else:
        auth_ready = True

    checks = ReadinessChecksResponse(
        config_loaded=True,
        agent_runner_initialized=agent_runner_initialized,
        persistence_ready=persistence_ready,
        auth_ready=auth_ready,
    )
    overall_ready = (
        checks.config_loaded
        and checks.agent_runner_initialized
        and checks.persistence_ready
        and checks.auth_ready
    )
    if not overall_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if overall_ready else "not_ready",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        persistence_backend=settings.persistence_backend,
        checks=checks,
        timestamp_utc=SystemUtcClock().now_utc().isoformat(),
    )
