"""Service health status and report value object."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.shared.errors import InvalidConfigurationError


class HealthStatus(StrEnum):
    """Canonical health state of the Brew service."""

    OK = "ok"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ServiceHealthReport:
    """Immutable value object describing service readiness and model configuration."""

    status: HealthStatus
    service: str
    version: str
    environment: str
    model: str
    timestamp_utc: str

    def __post_init__(self) -> None:
        if not self.service.strip():
            raise InvalidConfigurationError("Service name cannot be empty.")
        if not self.model.strip():
            raise InvalidConfigurationError("Configured Gemini model cannot be empty.")
