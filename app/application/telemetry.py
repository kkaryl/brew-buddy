"""Privacy-safe OpenTelemetry span helpers, attribute schemas, and error classification.

Kept free of FastAPI, ADK, and Google Cloud SDK imports so both application workflows
and outer adapters share a single canonical attribute schema and redaction boundary.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue

from app.application.correlation import (
    current_otel_trace_id_hex,
    get_workflow_correlation,
)
from app.application.untrusted_data import redact_pii_text
from app.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    BrewDomainError,
    ConflictError,
    DomainValidationError,
    EntityNotFoundError,
    ModelExecutionError,
    ModelOutputValidationError,
    ModelTimeoutError,
    PersistenceOperationError,
    VersionConflictError,
)

# Canonical Brew OpenTelemetry span attribute keys
ATTR_REQUEST_ID = "brew.request_id"
ATTR_TRACE_ID = "brew.trace_id"
ATTR_OTEL_TRACE_ID = "brew.otel_trace_id"
ATTR_AGENT_NAME = "brew.agent.name"
ATTR_AGENT_VERSION = "brew.agent.version"
ATTR_MODEL_NAME = "brew.model.name"
ATTR_OPERATION_NAME = "brew.operation.name"
ATTR_TOOL_NAME = "brew.tool.name"
ATTR_DURATION_MS = "brew.duration_ms"
ATTR_INPUT_TOKENS = "brew.tokens.input"
ATTR_OUTPUT_TOKENS = "brew.tokens.output"
ATTR_TOTAL_TOKENS = "brew.tokens.total"
ATTR_RESULT_STATUS = "brew.result.status"
ATTR_ERROR_CLASSIFICATION = "brew.error.classification"
ATTR_ERROR_CODE = "brew.error.code"
ATTR_MEMORY_RETRIEVED_COUNT = "brew.memory.retrieved_count"
ATTR_MEMORY_SAVED_COUNT = "brew.memory.saved_count"
ATTR_VALIDATION_PASSED = "brew.validation.passed"
ATTR_VALIDATION_STAGE = "brew.validation.stage"
ATTR_VALIDATION_VIOLATION_COUNT = "brew.validation.violation_count"
ATTR_REGENERATION_ATTEMPT = "brew.regeneration.attempt"
ATTR_REGENERATION_COUNT = "brew.regeneration.count"

# Attribute / log keys forbidden by default privacy policy
FORBIDDEN_TELEMETRY_KEYS: frozenset[str] = frozenset(
    {
        "notes",
        "meeting_notes",
        "context_notes",
        "communication_style_notes",
        "private_biography",
        "biography",
        "prompt",
        "raw_prompt",
        "full_prompt",
        "system_instruction",
        "instructions",
        "edited_text",
        "rejection_reason",
        "reason",
        "excerpt",
        "notes_excerpt",
        "llm_request",
        "llm_response",
        "completion",
        "authorization",
        "bearer",
        "token",
        "id_token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "password",
        "credentials",
        "cookie",
    }
)

_BEARER_SECRET_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_GOOGLE_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")
_GOOGLE_OAUTH_TOKEN_RE = re.compile(r"\bya29\.[0-9A-Za-z._-]{16,}\b")
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|id[_-]?token|secret|password|authorization)"
    r"(\s*[:=]\s*['\"]?)([^\s'\",;}{]+)"
)


def is_forbidden_telemetry_key(key: str) -> bool:
    """Return True if ``key`` could carry raw user notes, prompts, or credentials."""
    normalized = key.strip().lower().replace("-", "_")
    if normalized in FORBIDDEN_TELEMETRY_KEYS:
        return True
    leaf = normalized.rsplit(".", 1)[-1]
    return leaf in FORBIDDEN_TELEMETRY_KEYS


def scrub_sensitive_telemetry_text(text: str, *, max_chars: int = 512) -> str:
    """Scrub credentials, tokens, API keys, and PII from telemetry strings."""
    cleaned = _BEARER_SECRET_RE.sub("Bearer [REDACTED_CREDENTIAL]", text)
    cleaned = _JWT_RE.sub("[REDACTED_JWT]", cleaned)
    cleaned = _GOOGLE_API_KEY_RE.sub("[REDACTED_API_KEY]", cleaned)
    cleaned = _GOOGLE_OAUTH_TOKEN_RE.sub("[REDACTED_OAUTH_TOKEN]", cleaned)
    cleaned = _KEY_VALUE_SECRET_RE.sub(r"\1\2[REDACTED_SECRET]", cleaned)
    cleaned, _ = redact_pii_text(cleaned)
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 3] + "..."
    return cleaned


def classify_telemetry_error(
    exc: BaseException,
    *,
    is_tool: bool = False,
    is_persistence: bool = False,
) -> str:
    """Classify an exception into a deterministic telemetry error category."""
    if isinstance(exc, ModelTimeoutError):
        return "MODEL_TIMEOUT"
    if isinstance(exc, TimeoutError):
        if is_tool:
            return "TOOL_TIMEOUT"
        if is_persistence:
            return "PERSISTENCE_TIMEOUT"
        return "TIMEOUT"
    if isinstance(exc, ModelOutputValidationError):
        return "OUTPUT_VALIDATION_ERROR"
    if isinstance(exc, ModelExecutionError):
        return exc.code or "MODEL_EXECUTION_ERROR"
    if isinstance(exc, PersistenceOperationError):
        return "PERSISTENCE_UNAVAILABLE"
    if isinstance(exc, AuthenticationError):
        return "AUTHENTICATION_REQUIRED"
    if isinstance(exc, AuthorizationError):
        return "FORBIDDEN"
    if isinstance(exc, EntityNotFoundError):
        return "NOT_FOUND"
    if isinstance(exc, VersionConflictError):
        return "VERSION_CONFLICT"
    if isinstance(exc, ConflictError):
        return exc.code or "STATE_CONFLICT"
    if isinstance(exc, DomainValidationError):
        return exc.code or "VALIDATION_ERROR"
    if isinstance(exc, BrewDomainError):
        return exc.code or "DOMAIN_ERROR"
    return "INTERNAL_ERROR"


def set_safe_span_attribute(span: Span, key: str, value: object) -> None:
    """Attach a single primitive attribute to ``span`` after privacy & PII checks."""
    if value is None or not span.is_recording():
        return
    if is_forbidden_telemetry_key(key):
        return

    if isinstance(value, (bool, int)):
        span.set_attribute(key, value)
    elif isinstance(value, float):
        span.set_attribute(key, round(value, 3))
    elif isinstance(value, str):
        span.set_attribute(key, scrub_sensitive_telemetry_text(value))


def set_safe_span_attributes(span: Span, attributes: Mapping[str, object]) -> None:
    """Attach multiple privacy-checked attributes to ``span``."""
    for key, value in attributes.items():
        set_safe_span_attribute(span, key, value)


def stamp_correlation_attributes(span: Span) -> None:
    """Stamp active ``request_id``, ``trace_id``, and ``otel_trace_id`` onto ``span``."""
    if not span.is_recording():
        return
    corr = get_workflow_correlation()
    otel_hex = current_otel_trace_id_hex()
    if corr is not None:
        set_safe_span_attribute(span, ATTR_REQUEST_ID, corr.request_id)
        set_safe_span_attribute(span, ATTR_TRACE_ID, corr.trace_id)
    elif otel_hex is not None:
        set_safe_span_attribute(span, ATTR_REQUEST_ID, otel_hex)
        set_safe_span_attribute(span, ATTR_TRACE_ID, otel_hex)
    if otel_hex is not None:
        set_safe_span_attribute(span, ATTR_OTEL_TRACE_ID, otel_hex)


def mark_span_error(
    span: Span,
    *,
    classification: str,
    error_code: str | None = None,
    error_type: str | None = None,
    description: str | None = None,
) -> None:
    """Mark ``span`` as failed with safe error classification metadata."""
    if not span.is_recording():
        return
    safe_class = scrub_sensitive_telemetry_text(classification, max_chars=120)
    set_safe_span_attribute(span, ATTR_RESULT_STATUS, "error")
    set_safe_span_attribute(span, ATTR_ERROR_CLASSIFICATION, safe_class)
    if error_code:
        set_safe_span_attribute(span, ATTR_ERROR_CODE, error_code)
    if error_type:
        set_safe_span_attribute(span, "error.type", error_type)
    safe_desc = scrub_sensitive_telemetry_text(description or safe_class, max_chars=200)
    span.set_status(Status(StatusCode.ERROR, safe_desc))


@dataclass
class SpanOutcomeTracker:
    """Mutable outcome state updated inside a ``brew_span`` block."""

    span: Span
    status: str = "ok"
    error_classification: str | None = None
    error_code: str | None = None

    def set_attribute(self, key: str, value: object) -> None:
        set_safe_span_attribute(self.span, key, value)

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        set_safe_span_attributes(self.span, attributes)

    def mark_degraded(self, classification: str | None = None) -> None:
        self.status = "degraded"
        if classification:
            self.error_classification = classification

    def mark_error(
        self,
        classification: str,
        *,
        error_code: str | None = None,
        error_type: str | None = None,
        description: str | None = None,
    ) -> None:
        self.status = "error"
        self.error_classification = classification
        self.error_code = error_code
        mark_span_error(
            self.span,
            classification=classification,
            error_code=error_code,
            error_type=error_type,
            description=description,
        )


@contextlib.contextmanager
def brew_span(
    span_name: str,
    *,
    operation_name: str,
    tracer_name: str = "brew.telemetry",
    kind: SpanKind = SpanKind.INTERNAL,
    agent_name: str | None = None,
    agent_version: str | None = None,
    model_name: str | None = None,
    tool_name: str | None = None,
    attributes: Mapping[str, AttributeValue | object] | None = None,
    is_tool: bool = False,
    is_persistence: bool = False,
) -> Iterator[SpanOutcomeTracker]:
    """Create a correlated, duration-measured, privacy-safe OpenTelemetry span."""
    tracer = trace.get_tracer(tracer_name)
    started = time.perf_counter()
    with tracer.start_as_current_span(span_name, kind=kind) as span:
        stamp_correlation_attributes(span)
        set_safe_span_attribute(span, ATTR_OPERATION_NAME, operation_name)
        if agent_name:
            set_safe_span_attribute(span, ATTR_AGENT_NAME, agent_name)
        if agent_version:
            set_safe_span_attribute(span, ATTR_AGENT_VERSION, agent_version)
        if model_name:
            set_safe_span_attribute(span, ATTR_MODEL_NAME, model_name)
        if tool_name:
            set_safe_span_attribute(span, ATTR_TOOL_NAME, tool_name)
        if attributes:
            set_safe_span_attributes(span, attributes)

        tracker = SpanOutcomeTracker(span=span)
        try:
            yield tracker
        except BaseException as exc:
            if not isinstance(exc, GeneratorExit):
                classification = classify_telemetry_error(
                    exc,
                    is_tool=is_tool,
                    is_persistence=is_persistence,
                )
                err_code = exc.code if isinstance(exc, BrewDomainError) else classification
                tracker.mark_error(
                    classification,
                    error_code=err_code,
                    error_type=type(exc).__name__,
                    description=classification,
                )
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            set_safe_span_attribute(span, ATTR_DURATION_MS, elapsed_ms)
            set_safe_span_attribute(span, ATTR_RESULT_STATUS, tracker.status)
            if tracker.error_classification and tracker.status != "error":
                set_safe_span_attribute(
                    span,
                    ATTR_ERROR_CLASSIFICATION,
                    tracker.error_classification,
                )
            if tracker.status != "error" and span.is_recording():
                span.set_status(Status(StatusCode.OK))
