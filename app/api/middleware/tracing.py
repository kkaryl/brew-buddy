"""HTTP observability middleware and upstream trace-context extraction."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.api.errors import (
    resolve_request_and_trace_ids,
)
from app.api.middleware.adk_surface_auth import enforce_adk_and_memory_route_security
from app.application.shared.correlation import bind_workflow_correlation
from app.application.shared.telemetry import (
    ATTR_DURATION_MS,
    ATTR_ERROR_CLASSIFICATION,
    ATTR_ERROR_CODE,
    ATTR_OPERATION_NAME,
    ATTR_OTEL_TRACE_ID,
    ATTR_REQUEST_ID,
    ATTR_RESULT_STATUS,
    ATTR_TRACE_ID,
    mark_span_error,
    set_safe_span_attributes,
)

logger = logging.getLogger(__name__)


_http_tracer = trace.get_tracer("brew.http")


_CLOUD_TRACE_HEADER_RE = re.compile(r"^([0-9a-fA-F]{32})(?:/([0-9]{1,20}))?(?:;o=([01]))?$")


_TRACE_ERROR_CODES_4XX = frozenset(
    {
        "MODEL_OUTPUT_VALIDATION_ERROR",
        "MODEL_TIMEOUT",
        "MODEL_EXECUTION_ERROR",
        "PERSISTENCE_UNAVAILABLE",
    }
)


def _extract_upstream_trace_context(request: Request) -> otel_context.Context:
    """Extract W3C ``traceparent`` or Google Cloud ``X-Cloud-Trace-Context`` parent context."""
    ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
    if trace.get_current_span(ctx).get_span_context().is_valid:
        return ctx

    cloud_header = (request.headers.get("x-cloud-trace-context") or "").strip()
    if cloud_header:
        match = _CLOUD_TRACE_HEADER_RE.match(cloud_header)
        if match:
            trace_int = int(match.group(1), 16)
            span_int = int(match.group(2)) & 0xFFFFFFFFFFFFFFFF if match.group(2) else 1
            if trace_int != 0 and span_int != 0:
                sampled_flag = match.group(3)
                flags = TraceFlags(0x01 if sampled_flag != "0" else 0x00)
                remote_ctx = SpanContext(
                    trace_id=trace_int,
                    span_id=span_int,
                    is_remote=True,
                    trace_flags=flags,
                )
                return trace.set_span_in_context(NonRecordingSpan(remote_ctx), ctx)
    return ctx


def install_http_tracing_middleware(fastapi_app: FastAPI) -> None:
    """Install root OpenTelemetry HTTP request tracing & correlation middleware."""

    @fastapi_app.middleware("http")
    async def brew_http_observability_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/assets/"):
            return await call_next(request)

        parent_ctx = _extract_upstream_trace_context(request)
        initial_name = f"{request.method} {request.url.path}"
        started = time.perf_counter()

        with _http_tracer.start_as_current_span(
            initial_name,
            context=parent_ctx,
            kind=SpanKind.SERVER,
        ) as span:
            request_id, trace_id = resolve_request_and_trace_ids(request)
            span_ctx = span.get_span_context()
            otel_trace = format(span_ctx.trace_id, "032x") if span_ctx.is_valid else None
            if otel_trace:
                request.state.otel_trace_id = otel_trace

            set_safe_span_attributes(
                span,
                {
                    ATTR_OPERATION_NAME: "http.request",
                    ATTR_REQUEST_ID: request_id,
                    ATTR_TRACE_ID: trace_id,
                    ATTR_OTEL_TRACE_ID: otel_trace,
                    "http.request.method": request.method,
                    "url.path": request.url.path,
                },
            )

            with bind_workflow_correlation(
                request_id=request_id,
                trace_id=trace_id,
                otel_trace_id=otel_trace,
            ):
                try:
                    security_rejection = await enforce_adk_and_memory_route_security(request)
                    response = (
                        security_rejection
                        if security_rejection is not None
                        else await call_next(request)
                    )
                except Exception as exc:
                    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
                    set_safe_span_attributes(
                        span,
                        {
                            ATTR_DURATION_MS: elapsed_ms,
                            "http.response.status_code": 500,
                        },
                    )
                    mark_span_error(
                        span,
                        classification="INTERNAL_ERROR",
                        error_code="INTERNAL_SERVER_ERROR",
                        error_type=type(exc).__name__,
                    )
                    raise

                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
                matched_route = request.scope.get("route")
                route_template = getattr(matched_route, "path", None) or request.url.path
                if span.is_recording():
                    span.update_name(f"{request.method} {route_template}")

                status_code = response.status_code
                err_class: str | None = getattr(request.state, "error_classification", None)
                err_code: str | None = getattr(request.state, "error_code", None)
                result_status = "error" if status_code >= 400 else "ok"
                if status_code >= 400 and not err_class:
                    err_class = f"HTTP_{status_code}"

                set_safe_span_attributes(
                    span,
                    {
                        ATTR_DURATION_MS: elapsed_ms,
                        ATTR_RESULT_STATUS: result_status,
                        ATTR_ERROR_CLASSIFICATION: err_class,
                        ATTR_ERROR_CODE: err_code,
                        "http.route": route_template,
                        "http.response.status_code": status_code,
                    },
                )
                if status_code >= 500 or (err_code in _TRACE_ERROR_CODES_4XX):
                    mark_span_error(
                        span,
                        classification=err_class or f"HTTP_{status_code}",
                        error_code=err_code,
                        description=err_class or f"HTTP_{status_code}",
                    )
                elif span.is_recording():
                    span.set_status(Status(StatusCode.OK))

                if "X-Request-ID" not in response.headers:
                    response.headers["X-Request-ID"] = request_id
                if otel_trace and "X-Trace-ID" not in response.headers:
                    response.headers["X-Trace-ID"] = otel_trace

                logger.info(
                    f"HTTP {request.method} {route_template} -> {status_code} ({elapsed_ms}ms)",
                    extra={
                        "event_type": "http.request.completed",
                        "operation_name": "http.request",
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "otel_trace_id": otel_trace,
                        "http_method": request.method,
                        "http_route": route_template,
                        "http_status_code": status_code,
                        "duration_ms": elapsed_ms,
                        "result_status": result_status,
                        "error_code": err_code,
                        "error_classification": err_class,
                    },
                )
                return response
