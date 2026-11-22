"""Foundational system readiness ADK tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.application.health_service import HealthCheckService
from app.config import get_settings
from app.domain.errors import BrewDomainError
from app.infrastructure.clock import SystemUtcClock


class ServiceReadinessOutput(BaseModel):
    """Strict output schema for check_brew_service_health."""

    status: Literal["ok", "degraded", "error"] = Field(
        description="Operational status of the Brew runtime."
    )
    service: str = Field(description="Canonical service identifier.")
    version: str = Field(description="Deployed semantic version of Brew.")
    environment: str = Field(description="Runtime environment name.")
    model: str = Field(description="Configured default Gemini model identifier.")
    timestamp_utc: str = Field(description="ISO-8601 UTC timestamp of the health check.")
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code when status is 'error'.",
    )
    recovery_instruction: str | None = Field(
        default=None,
        description="Actionable recovery guidance for the agent when status is 'error'.",
    )


def check_brew_service_health() -> dict[str, str | None]:
    """Inspect the current operational health and model configuration of the Brew service.

    Use this tool when a user or operator asks whether Brew is online, which environment
    is active, or which Gemini model is configured for this runtime.

    Returns:
        A dictionary validated against ``ServiceReadinessOutput`` containing service
        status, version, environment, configured model, and optional recovery guidance.
    """
    try:
        settings = get_settings()
        service = HealthCheckService(
            service_name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
            configured_model=settings.gemini_model,
            clock=SystemUtcClock(),
        )
        report = service.check_health()
        output = ServiceReadinessOutput(
            status="ok" if report.status.value == "ok" else "degraded",
            service=report.service,
            version=report.version,
            environment=report.environment,
            model=report.model,
            timestamp_utc=report.timestamp_utc,
        )
        return output.model_dump()
    except BrewDomainError as exc:
        fallback = ServiceReadinessOutput(
            status="error",
            service="brew",
            version="unknown",
            environment="unknown",
            model="unknown",
            timestamp_utc="",
            error_code=exc.code,
            recovery_instruction=(
                "Report to the user that Brew runtime configuration is invalid and verify "
                "APP_NAME and GEMINI_MODEL environment variables."
            ),
        )
        return fallback.model_dump()
