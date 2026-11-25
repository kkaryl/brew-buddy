"""Unit tests for domain health invariants, application service, logging, and ADK tool."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from app.agents.tools.system import check_brew_service_health
from app.application.health.service import HealthCheckService
from app.config import clear_settings_cache
from app.domain.shared.errors import InvalidConfigurationError
from app.domain.shared.health import HealthStatus, ServiceHealthReport
from app.infrastructure.observability import StructuredJsonFormatter


class FixedClock:
    """Deterministic clock test double."""

    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now_utc(self) -> datetime:
        return self._fixed


def test_service_health_report_enforces_non_empty_invariants() -> None:
    with pytest.raises(InvalidConfigurationError):
        ServiceHealthReport(
            status=HealthStatus.OK,
            service=" ",
            version="0.1.0",
            environment="test",
            model="gemini-3.8-flash",
            timestamp_utc="2026-11-22T00:00:00+00:00",
        )

    with pytest.raises(InvalidConfigurationError):
        ServiceHealthReport(
            status=HealthStatus.OK,
            service="brew",
            version="0.1.0",
            environment="test",
            model="",
            timestamp_utc="2026-11-22T00:00:00+00:00",
        )


def test_health_check_service_uses_injected_clock() -> None:
    fixed_time = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    service = HealthCheckService(
        service_name="brew",
        version="0.1.0",
        environment="test",
        configured_model="gemini-3.8-flash",
        clock=FixedClock(fixed_time),
    )

    report = service.check_health()

    assert report.status is HealthStatus.OK
    assert report.service == "brew"
    assert report.model == "gemini-3.8-flash"
    assert report.timestamp_utc == "2026-11-22T10:00:00+00:00"


def test_system_health_tool_returns_schema_valid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    clear_settings_cache()
    try:
        result = check_brew_service_health()
    finally:
        clear_settings_cache()

    assert result["status"] == "ok"
    assert result["service"] == "brew"
    assert result["model"] == "gemini-3.8-flash"
    assert result["error_code"] is None


def test_structured_json_formatter_outputs_single_line_json() -> None:
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Health check completed",
        args=(),
        exc_info=None,
    )
    record.event_type = "health.checked"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert "\n" not in formatted
    assert parsed["severity"] == "INFO"
    assert parsed["message"] == "Health check completed"
    assert parsed["event_type"] == "health.checked"
