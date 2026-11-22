"""FastAPI health check endpoints with dependency-injected application services."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.application.health_service import HealthCheckService
from app.config import AppSettings, get_settings
from app.infrastructure.clock import SystemUtcClock


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
    """Resolve AppSettings from FastAPI state when injected, falling back to cached settings."""
    state_settings: AppSettings | None = getattr(request.app.state, "settings", None)
    return state_settings if state_settings is not None else get_settings()


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
