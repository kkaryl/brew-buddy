"""Structured JSON logging integrated with OpenTelemetry trace context."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from app.application.correlation import get_workflow_correlation


class StructuredJsonFormatter(logging.Formatter):
    """Formats Python log records as single-line Cloud Logging compatible JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        corr = get_workflow_correlation()
        if corr is not None:
            payload["request_id"] = corr.request_id
            payload["trace_id"] = corr.trace_id

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload.setdefault("trace_id", format(span_context.trace_id, "032x"))
            payload["span_id"] = format(span_context.span_id, "016x")

        for extra_key in (
            "event_type",
            "request_id",
            "trace_id",
            "session_id",
            "agent_name",
            "tool_name",
        ):
            value = getattr(record, extra_key, None)
            if value is not None:
                payload[extra_key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(level: str = "INFO") -> None:
    """Configure root application logger with structured JSON output on stdout."""
    brew_logger = logging.getLogger("app")
    brew_logger.setLevel(level.upper())

    if not any(
        isinstance(handler.formatter, StructuredJsonFormatter) for handler in brew_logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        brew_logger.handlers = [handler]
        brew_logger.propagate = False
