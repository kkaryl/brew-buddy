"""Consistent HTTP error translation and correlation/trace ID propagation."""

from __future__ import annotations

import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiErrorResponse, ErrorDetailItem, ErrorObject
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

_SAFE_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_HTTP_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    502: "MODEL_EXECUTION_ERROR",
    503: "PERSISTENCE_UNAVAILABLE",
    504: "MODEL_TIMEOUT",
}


def resolve_request_and_trace_ids(request: Request) -> tuple[str, str]:
    """Resolve unified ``(request_id, trace_id)`` for HTTP request and workflow tracing."""
    existing_req: str | None = getattr(request.state, "request_id", None)
    existing_trace: str | None = getattr(request.state, "trace_id", None)
    if existing_req and existing_trace:
        return existing_req, existing_trace

    header_candidate = (request.headers.get("x-request-id") or "").strip()
    valid_header = (
        header_candidate
        if header_candidate and _SAFE_CORRELATION_RE.match(header_candidate)
        else None
    )

    span_context = trace.get_current_span().get_span_context()
    otel_trace = format(span_context.trace_id, "032x") if span_context.is_valid else None

    generated = uuid.uuid4().hex
    request_id = valid_header or otel_trace or generated
    trace_id = otel_trace or valid_header or request_id

    request.state.request_id = request_id
    request.state.trace_id = trace_id
    return request_id, trace_id


def resolve_trace_id(request: Request) -> str:
    """Resolve an OpenTelemetry trace ID, validated request header, or generated UUID."""
    _, trace_id = resolve_request_and_trace_ids(request)
    return trace_id


def _domain_error_status_and_headers(
    exc: BrewDomainError,
) -> tuple[int, dict[str, str] | None]:
    if isinstance(exc, AuthenticationError):
        return 401, {"WWW-Authenticate": "Bearer"}
    if isinstance(exc, AuthorizationError):
        return 403, None
    if isinstance(exc, EntityNotFoundError):
        return 404, None
    if isinstance(exc, (VersionConflictError, ConflictError)):
        return 409, None
    if isinstance(exc, (DomainValidationError, ModelOutputValidationError)):
        return 422, None
    if isinstance(exc, ModelTimeoutError):
        return 504, None
    if isinstance(exc, ModelExecutionError):
        return 502, None
    if isinstance(exc, PersistenceOperationError):
        return 503, None
    return (400 if exc.recoverable else 500), None


def register_exception_handlers(fastapi_app: FastAPI) -> None:
    """Attach consistent ``ApiErrorResponse`` exception handlers to ``fastapi_app``."""

    @fastapi_app.exception_handler(BrewDomainError)
    async def handle_domain_error(request: Request, exc: BrewDomainError) -> JSONResponse:
        request_id, trace_id = resolve_request_and_trace_ids(request)
        status_code, headers = _domain_error_status_and_headers(exc)
        details: list[ErrorDetailItem] = []
        if isinstance(exc, ModelOutputValidationError):
            details = [
                ErrorDetailItem(
                    field="brief_output",
                    message=violation,
                    error_type="brief_quality_or_schema_violation",
                )
                for violation in exc.violations
            ]
        payload = ApiErrorResponse(
            error=ErrorObject(
                code=exc.code,
                message=exc.message,
                trace_id=trace_id,
                details=details,
            )
        )
        merged_headers = {"X-Request-ID": request_id, **(headers or {})}
        return JSONResponse(
            status_code=status_code,
            content=payload.model_dump(mode="json"),
            headers=merged_headers,
        )

    @fastapi_app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        trace_id = resolve_trace_id(request)
        details = [
            ErrorDetailItem(
                field=".".join(str(part) for part in err.get("loc", ())),
                message=str(err.get("msg", "Invalid input.")),
                error_type=str(err.get("type", "validation_error")),
            )
            for err in exc.errors()
        ]
        payload = ApiErrorResponse(
            error=ErrorObject(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                trace_id=trace_id,
                details=details,
            )
        )
        return JSONResponse(
            status_code=422,
            content=payload.model_dump(mode="json"),
            headers={"X-Request-ID": trace_id},
        )

    @fastapi_app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        trace_id = resolve_trace_id(request)
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.detail.strip()
            else "HTTP request failed."
        )
        payload = ApiErrorResponse(
            error=ErrorObject(
                code=code,
                message=message,
                trace_id=trace_id,
                details=[],
            )
        )
        merged_headers = {"X-Request-ID": trace_id, **(exc.headers or {})}
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(mode="json"),
            headers=merged_headers,
        )
