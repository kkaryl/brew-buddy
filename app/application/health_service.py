"""Application service reporting Brew operational health."""

from __future__ import annotations

from app.domain.health import ClockPort, HealthStatus, ServiceHealthReport


class HealthCheckService:
    """Produces a typed health report using injected metadata and clock port."""

    def __init__(
        self,
        *,
        service_name: str,
        version: str,
        environment: str,
        configured_model: str,
        clock: ClockPort,
    ) -> None:
        self._service_name = service_name
        self._version = version
        self._environment = environment
        self._configured_model = configured_model
        self._clock = clock

    def check_health(self) -> ServiceHealthReport:
        """Evaluate current service health."""
        timestamp = self._clock.now_utc().isoformat()
        return ServiceHealthReport(
            status=HealthStatus.OK,
            service=self._service_name,
            version=self._version,
            environment=self._environment,
            model=self._configured_model,
            timestamp_utc=timestamp,
        )
