"""OpenTelemetry + Google Cloud Trace setup, privacy enforcement, and JSON logging."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from google.adk.telemetry import ContentCapturingMode, TelemetryConfig
from opentelemetry import trace
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from app.application.shared.correlation import get_workflow_correlation
from app.application.shared.telemetry import (
    classify_telemetry_error,
    is_forbidden_telemetry_key,
    scrub_sensitive_telemetry_text,
)
from app.config import AppSettings, get_settings
from app.domain.shared.errors import BrewDomainError

logger = logging.getLogger(__name__)

_SAFE_LOG_EXTRA_KEYS: tuple[str, ...] = (
    "event_type",
    "operation_name",
    "request_id",
    "trace_id",
    "otel_trace_id",
    "session_id",
    "agent_name",
    "agent_version",
    "model_name",
    "tool_name",
    "duration_ms",
    "result_status",
    "error_type",
    "error_code",
    "error_classification",
    "memory_retrieved_count",
    "memory_saved_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "attempt_count",
    "regeneration_count",
    "http_method",
    "http_route",
    "http_status_code",
)

_COMPLETION_UPLOAD_ENV_VARS: tuple[str, ...] = (
    "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT",
)


def _sanitize_log_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, str):
        return scrub_sensitive_telemetry_text(value, max_chars=512)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_log_value(item) for item in list(value)[:20]]
    if isinstance(value, dict):
        cleaned_dict: dict[str, Any] = {}
        for k, v in list(value.items())[:25]:
            key_str = str(k)
            if is_forbidden_telemetry_key(key_str):
                continue
            cleaned_dict[key_str] = _sanitize_log_value(v)
        return cleaned_dict
    return scrub_sensitive_telemetry_text(str(value), max_chars=256)


class TraceContextLogFilter(logging.Filter):
    """Captures active correlation and OTel span IDs onto ``LogRecord`` at log-call time."""

    def filter(self, record: logging.LogRecord) -> bool:
        corr = get_workflow_correlation()
        if corr is not None:
            if getattr(record, "request_id", None) is None:
                record.request_id = corr.request_id
            if getattr(record, "trace_id", None) is None:
                record.trace_id = corr.trace_id
            if corr.otel_trace_id and getattr(record, "otel_trace_id", None) is None:
                record.otel_trace_id = corr.otel_trace_id

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            otel_hex = format(span_context.trace_id, "032x")
            span_hex = format(span_context.span_id, "016x")
            if getattr(record, "trace_id", None) is None:
                record.trace_id = otel_hex
            record.otel_trace_id = otel_hex
            record.span_id = span_hex
            record.trace_sampled = bool(span_context.trace_flags.sampled)
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Formats Python log records as single-line Cloud Logging compatible JSON."""

    def __init__(self, *, gcp_project_id: str | None = None) -> None:
        super().__init__()
        self._gcp_project_id = gcp_project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": scrub_sensitive_telemetry_text(record.getMessage(), max_chars=1000),
        }

        corr = get_workflow_correlation()
        if corr is not None:
            payload["request_id"] = corr.request_id
            payload["trace_id"] = corr.trace_id
            if corr.otel_trace_id:
                payload["otel_trace_id"] = corr.otel_trace_id

        rec_span_id = getattr(record, "span_id", None)
        rec_otel_trace = getattr(record, "otel_trace_id", None)
        rec_sampled = getattr(record, "trace_sampled", None)

        span_context = trace.get_current_span().get_span_context()
        otel_trace_hex: str | None = (
            str(rec_otel_trace) if isinstance(rec_otel_trace, str) and rec_otel_trace else None
        )
        if span_context.is_valid:
            otel_trace_hex = format(span_context.trace_id, "032x")
            span_hex = format(span_context.span_id, "016x")
            payload.setdefault("trace_id", otel_trace_hex)
            payload["otel_trace_id"] = otel_trace_hex
            payload["span_id"] = span_hex
            payload["logging.googleapis.com/spanId"] = span_hex
            payload["logging.googleapis.com/trace_sampled"] = bool(span_context.trace_flags.sampled)
        else:
            if isinstance(rec_span_id, str) and rec_span_id:
                payload["span_id"] = rec_span_id
                payload["logging.googleapis.com/spanId"] = rec_span_id
            if isinstance(rec_sampled, bool):
                payload["logging.googleapis.com/trace_sampled"] = rec_sampled
            if otel_trace_hex is None and corr is not None and corr.otel_trace_id:
                otel_trace_hex = corr.otel_trace_id

        project_id = self._gcp_project_id
        if project_id is None:
            env_proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
            if env_proj and env_proj != "your-gcp-project-id":
                project_id = env_proj

        for extra_key in _SAFE_LOG_EXTRA_KEYS:
            if is_forbidden_telemetry_key(extra_key):
                continue
            value = getattr(record, extra_key, None)
            if value is not None:
                payload[extra_key] = _sanitize_log_value(value)

        if not otel_trace_hex and isinstance(payload.get("otel_trace_id"), str):
            otel_trace_hex = str(payload["otel_trace_id"])

        if otel_trace_hex:
            if project_id:
                payload["logging.googleapis.com/trace"] = (
                    f"projects/{project_id}/traces/{otel_trace_hex}"
                )
            else:
                payload["logging.googleapis.com/trace"] = otel_trace_hex

        if record.exc_info and record.exc_info[1] is not None:
            exc_obj = record.exc_info[1]
            payload.setdefault("error_type", type(exc_obj).__name__)
            payload.setdefault("error_classification", classify_telemetry_error(exc_obj))
            if isinstance(exc_obj, BrewDomainError):
                payload.setdefault("error_code", exc_obj.code)
            raw_exc = self.formatException(record.exc_info)
            payload["exception"] = scrub_sensitive_telemetry_text(raw_exc, max_chars=2000)

        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(
    level: str = "INFO",
    *,
    gcp_project_id: str | None = None,
) -> None:
    """Configure application and ADK loggers with structured JSON output on stdout."""
    formatter = StructuredJsonFormatter(gcp_project_id=gcp_project_id)
    for logger_name, target_level in (
        ("app", level.upper()),
        ("google_adk", "WARNING"),
    ):
        target_logger = logging.getLogger(logger_name)
        target_logger.setLevel(target_level)
        if not any(isinstance(f, TraceContextLogFilter) for f in target_logger.filters):
            target_logger.addFilter(TraceContextLogFilter())
        existing_json_handlers = [
            h for h in target_logger.handlers if isinstance(h.formatter, StructuredJsonFormatter)
        ]
        if existing_json_handlers:
            for handler in existing_json_handlers:
                handler.setFormatter(formatter)
                if not any(isinstance(f, TraceContextLogFilter) for f in handler.filters):
                    handler.addFilter(TraceContextLogFilter())
        else:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            stream_handler.addFilter(TraceContextLogFilter())
            target_logger.handlers = [stream_handler]
        has_pytest_capture = any(
            h.__class__.__name__ == "LogCaptureHandler" for h in logging.getLogger().handlers
        )
        target_logger.propagate = has_pytest_capture


def enforce_telemetry_privacy_defaults(settings: AppSettings | None = None) -> dict[str, str]:
    """Disable prompt/response content capture and completion uploads unless authorized.

    Returns a dictionary summarizing the active non-sensitive privacy posture.
    """
    resolved = settings or get_settings()
    suppressed_upload_vars: list[str] = []

    if resolved.telemetry_capture_content:
        mode = (
            os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "").strip()
            or "SPAN_AND_EVENT"
        )
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = mode
        os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "true")
    else:
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "NO_CONTENT"
        os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] = "false"

    if not resolved.telemetry_upload_completions:
        for env_key in _COMPLETION_UPLOAD_ENV_VARS:
            if env_key in os.environ:
                os.environ.pop(env_key, None)
                suppressed_upload_vars.append(env_key)

    if suppressed_upload_vars:
        logger.warning(
            "Disabled unauthorized GenAI completion upload environment hooks",
            extra={
                "event_type": "telemetry.privacy.upload_hooks_disabled",
                "operation_name": "telemetry.privacy_guard",
                "result_status": "suppressed",
            },
        )

    return {
        "content_capture_mode": os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"],
        "adk_span_content_capture": os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"],
        "completion_uploads_enabled": str(resolved.telemetry_upload_completions).lower(),
    }


def build_adk_telemetry_config(settings: AppSettings | None = None) -> TelemetryConfig:
    """Construct per-run ADK ``TelemetryConfig`` honoring Brew's privacy gate."""
    resolved = settings or get_settings()
    if resolved.telemetry_capture_content:
        return TelemetryConfig()
    return TelemetryConfig(capture_message_content=ContentCapturingMode.NO_CONTENT)


class InMemoryTraceRecorder(SpanProcessor):
    """Thread-safe in-memory ``SpanProcessor`` for local deterministic trace verification."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._spans: list[ReadableSpan] = []

    def start_recording(self) -> None:
        with self._lock:
            self._spans.clear()
            self._active = True

    def stop_recording(self) -> None:
        with self._lock:
            self._active = False

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def get_finished_spans(self) -> tuple[ReadableSpan, ...]:
        with self._lock:
            return tuple(self._spans)

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        del span, parent_context

    def on_end(self, span: ReadableSpan) -> None:
        with self._lock:
            if self._active:
                self._spans.append(span)

    def shutdown(self) -> None:
        self.stop_recording()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


_PROCESS_TRACE_RECORDER = InMemoryTraceRecorder()
_RECORDER_ATTACHED_PROVIDERS: set[int] = set()
_CLOUD_TRACE_ATTACHED_PROVIDERS: set[int] = set()


def build_service_resource(settings: AppSettings) -> Resource:
    """Build OpenTelemetry ``Resource`` identifying the Brew service and environment."""
    detected = OTELResourceDetector().detect()
    brew_attrs: dict[str, str] = {
        "service.name": settings.app_name,
        "service.version": settings.app_version,
        "deployment.environment": settings.environment,
    }
    if settings.resolved_gcp_project_for_telemetry:
        brew_attrs["cloud.account.id"] = settings.resolved_gcp_project_for_telemetry
    return detected.merge(Resource.create(brew_attrs))


def build_cloud_trace_exporter(project_id: str | None = None) -> SpanExporter:
    """Instantiate Google Cloud Trace ``CloudTraceSpanExporter``."""
    from collections.abc import Callable
    from typing import cast

    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

    factory = cast(Callable[..., SpanExporter], CloudTraceSpanExporter)
    return factory(project_id=project_id) if project_id else factory()


def ensure_tracer_provider(
    settings: AppSettings | None = None,
    *,
    attach_cloud_trace_exporter: bool = False,
) -> TracerProvider:
    """Ensure a real OpenTelemetry SDK ``TracerProvider`` is registered for Brew.

    Preserves any ``TracerProvider`` already configured by ``google-adk`` / ``agents-cli``
    scaffold while attaching ``InMemoryTraceRecorder`` support and optional standalone
    ``CloudTraceSpanExporter`` when requested outside ``get_fast_api_app(otel_to_cloud=True)``.
    """
    resolved = settings or get_settings()
    enforce_telemetry_privacy_defaults(resolved)

    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        provider = current
    else:
        provider = TracerProvider(resource=build_service_resource(resolved))
        trace.set_tracer_provider(provider)
        current_after = trace.get_tracer_provider()
        if isinstance(current_after, TracerProvider):
            provider = current_after

    provider_id = id(provider)
    if provider_id not in _RECORDER_ATTACHED_PROVIDERS:
        provider.add_span_processor(_PROCESS_TRACE_RECORDER)
        _RECORDER_ATTACHED_PROVIDERS.add(provider_id)

    if attach_cloud_trace_exporter and provider_id not in _CLOUD_TRACE_ATTACHED_PROVIDERS:
        exporter = build_cloud_trace_exporter(resolved.resolved_gcp_project_for_telemetry)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _CLOUD_TRACE_ATTACHED_PROVIDERS.add(provider_id)
        logger.info(
            "Attached Google Cloud Trace span exporter",
            extra={
                "event_type": "telemetry.cloud_trace.enabled",
                "operation_name": "telemetry.setup",
                "result_status": "ok",
            },
        )

    return provider


@contextlib.contextmanager
def capture_traces(settings: AppSettings | None = None) -> Iterator[InMemoryTraceRecorder]:
    """Capture all OpenTelemetry spans emitted within the block into memory."""
    ensure_tracer_provider(settings)
    _PROCESS_TRACE_RECORDER.start_recording()
    try:
        yield _PROCESS_TRACE_RECORDER
    finally:
        _PROCESS_TRACE_RECORDER.stop_recording()
