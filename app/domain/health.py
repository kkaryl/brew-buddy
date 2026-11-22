"""Domain health models and clock port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.domain.errors import InvalidConfigurationError


class HealthStatus(StrEnum):
    """Canonical health state of the Brew service."""

    OK = "ok"
    DEGRADED = "degraded"


class ClockPort(Protocol):
    """Port supplying the current UTC timestamp."""

    def now_utc(self) -> datetime:
        """Return a timezone-aware UTC datetime."""


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
