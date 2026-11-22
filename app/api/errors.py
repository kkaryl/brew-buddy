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
}


def resolve_trace_id(request: Request) -> str:
    """Resolve an OpenTelemetry trace ID, validated request header, or generated UUID."""
    existing: str | None = getattr(request.state, "trace_id", None)
    if existing:
        return existing

    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        resolved = format(span_context.trace_id, "032x")
        request.state.trace_id = resolved
        return resolved

    header_candidate = (request.headers.get("x-request-id") or "").strip()
    if header_candidate and _SAFE_CORRELATION_RE.match(header_candidate):
        request.state.trace_id = header_candidate
        return header_candidate

    generated = uuid.uuid4().hex
    request.state.trace_id = generated
    return generated


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
    if isinstance(exc, DomainValidationError):
        return 422, None
    return (400 if exc.recoverable else 500), None


def register_exception_handlers(fastapi_app: FastAPI) -> None:
    """Attach consistent ``ApiErrorResponse`` exception handlers to ``fastapi_app``."""

    @fastapi_app.exception_handler(BrewDomainError)
    async def handle_domain_error(request: Request, exc: BrewDomainError) -> JSONResponse:
        trace_id = resolve_trace_id(request)
        status_code, headers = _domain_error_status_and_headers(exc)
        payload = ApiErrorResponse(
            error=ErrorObject(
                code=exc.code,
                message=exc.message,
                trace_id=trace_id,
                details=[],
            )
        )
        merged_headers = {"X-Request-ID": trace_id, **(headers or {})}
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
