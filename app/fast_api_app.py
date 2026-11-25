"""FastAPI application factory integrating Google ADK, A2A, telemetry, health, and SPA hosting."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
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
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.auth import router as auth_router
from app.api.dependencies import (
    get_service_container,
    resolve_authenticated_principal_off_event_loop,
)
from app.api.errors import (
    build_domain_error_json_response,
    register_exception_handlers,
    resolve_request_and_trace_ids,
)
from app.api.health import get_app_settings, resolve_adc_file_mtime_ns
from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.application.correlation import bind_workflow_correlation
from app.application.telemetry import (
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
from app.config import REPO_ROOT, AppSettings, get_settings
from app.domain.errors import AuthorizationError, BrewDomainError, DomainValidationError
from app.infrastructure.container import build_service_container
from app.infrastructure.fakes import ServiceContainer
from app.infrastructure.observability import (
    configure_structured_logging,
    enforce_telemetry_privacy_defaults,
    ensure_tracer_provider,
)
from app.infrastructure.session_service_factory import SessionServiceFactory
from app.tools.coaching_tools import (
    CoachingToolDependencies,
    set_default_coaching_dependencies,
)

load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger(__name__)
_http_tracer = trace.get_tracer("brew.http")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESERVED_BACKEND_PREFIXES = (
    "api/",
    "apps/",
    "a2a/",
    "docs",
    "redoc",
    "openapi.json",
    "run",
    "run_sse",
    "list-apps",
    "healthz",
    "readyz",
)
_ADK_APPS_USER_PATH_RE = re.compile(r"^/apps/[^/]+/users/([^/]+)(?:/|$)")
_ADK_APPS_MEMORY_PATH_RE = re.compile(r"^/apps/[^/]+/users/[^/]+/memory/?$")
_ADK_RUN_INVOCATION_PATHS = frozenset({"/run", "/run_sse"})
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


async def _enforce_adk_and_memory_route_security(request: Request) -> Response | None:
    """Enforce authenticated user identity on ADK/A2A routes and block ungoverned memory writes."""
    path = request.url.path
    method = request.method.upper()

    # 1. Never allow direct ungoverned memory writes through ADK's built-in /memory endpoint.
    #    Durable cross-session memories in Brew strictly require HITL proposal and approval.
    if _ADK_APPS_MEMORY_PATH_RE.match(path) and method in {"PATCH", "POST", "PUT", "DELETE"}:
        try:
            container = get_service_container(request)
            await resolve_authenticated_principal_off_event_loop(request, container)
            raise AuthorizationError(
                "Direct unreviewed memory writes are disabled. Submit candidates via "
                "POST /api/v1/memories/propose and approve via POST /api/v1/memories/{id}/approve.",
                code="UNGOVERNED_MEMORY_WRITE_DISABLED",
            )
        except BrewDomainError as exc:
            return build_domain_error_json_response(request, exc)

    active_settings = get_app_settings(request)
    if active_settings.local_mock_auth_enabled:
        return None

    is_protected_adk_surface = (
        path.startswith("/apps/")
        or path in {"/run", "/run_sse", "/list-apps", "/agent-identity/finalize"}
        or (path.startswith("/a2a/") and method != "GET")
    )
    if not is_protected_adk_surface:
        return None

    try:
        container = get_service_container(request)
        principal = await resolve_authenticated_principal_off_event_loop(request, container)

        user_match = _ADK_APPS_USER_PATH_RE.match(path)
        if user_match:
            target_user_id = unquote(user_match.group(1)).strip()
            if target_user_id != principal.user_id:
                raise AuthorizationError(
                    "Authenticated user cannot access or modify another user's agent sessions.",
                    code="FORBIDDEN",
                )

        if path in _ADK_RUN_INVOCATION_PATHS and method == "POST":
            _require_run_request_targets_principal(await request.body(), principal.user_id)
    except BrewDomainError as exc:
        return build_domain_error_json_response(request, exc)

    return None


def _is_user_identity_key(key: str) -> bool:
    """Return True for every spelling of the ADK caller-identity field.

    ADK request models declare ``user_id`` and also accept its camelCase alias ``userId``
    (``populate_by_name=True``), and the alias wins when both are supplied. Matching on the
    normalized key keeps this check aligned with whichever spelling ADK ends up honoring.
    """
    return key.replace("_", "").replace("-", "").lower() == "userid"


def _require_run_request_targets_principal(raw_body: bytes, principal_user_id: str) -> None:
    """Reject ``/run`` and ``/run_sse`` bodies that do not name exactly the authenticated user.

    Fails closed: a body that is not a JSON object, names no user, or names any user other
    than the verified principal under any accepted spelling never reaches the ADK runner.
    """
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except ValueError:
        parsed_body = None
    if not isinstance(parsed_body, dict):
        raise DomainValidationError(
            "Agent run requests must be a JSON object naming the caller's own user_id."
        )

    # Compared exactly, without trimming: ADK uses the value verbatim as the session owner.
    requested_user_ids = [
        value if isinstance(value, str) else None
        for key, value in parsed_body.items()
        if _is_user_identity_key(key)
    ]
    if not requested_user_ids:
        raise DomainValidationError("Agent run requests must include the caller's own user_id.")
    if any(requested != principal_user_id for requested in requested_user_ids):
        raise AuthorizationError(
            "Authenticated user cannot invoke the agent as another user_id.",
            code="FORBIDDEN",
        )


def _websocket_targets_principal(query_string: bytes, principal_user_id: str) -> bool:
    """Return True only when every ``user_id`` query value equals the authenticated user."""
    requested_user_ids = [
        value
        for key, value in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
        if _is_user_identity_key(key)
    ]
    return bool(requested_user_ids) and all(
        requested == principal_user_id for requested in requested_user_ids
    )


class _DeployedWebSocketAuthMiddleware:
    """Bind ADK ``/run_live`` WebSocket upgrades to the authenticated user when deployed."""

    def __init__(self, app: ASGIApp, fastapi_app: FastAPI) -> None:
        self._app = app
        self._fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "websocket" and scope.get("path") == "/run_live":
            query_string: bytes = scope.get("query_string", b"")
            pseudo_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/run_live",
                    "headers": scope.get("headers", []),
                    "query_string": query_string,
                    "app": self._fastapi_app,
                }
            )
            active_settings = get_app_settings(pseudo_request)
            if not active_settings.local_mock_auth_enabled:
                try:
                    container = get_service_container(pseudo_request)
                    principal = await resolve_authenticated_principal_off_event_loop(
                        pseudo_request,
                        container,
                    )
                except BrewDomainError:
                    await send({"type": "websocket.close", "code": 1008})
                    return
                if not _websocket_targets_principal(query_string, principal.user_id):
                    await send({"type": "websocket.close", "code": 1008})
                    return
        await self._app(scope, receive, send)


def _install_http_tracing_middleware(fastapi_app: FastAPI) -> None:
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
                    security_rejection = await _enforce_adk_and_memory_route_security(request)
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


def _attach_spa_routes(fastapi_app: FastAPI, dist_dir: Path) -> None:
    """Mount built Vite assets and SPA index fallback when web/dist is present."""
    resolved_dist = dist_dir.resolve()
    index_file = resolved_dist / "index.html"
    if not index_file.is_file():
        return

    assets_dir = resolved_dist / "assets"
    if assets_dir.is_dir():
        fastapi_app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="brew-web-assets",
        )

    @fastapi_app.get("/", include_in_schema=False, response_model=None)
    async def serve_spa_root() -> FileResponse:
        return FileResponse(index_file)

    @fastapi_app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def serve_spa_fallback(full_path: str) -> FileResponse:
        normalized = full_path.lstrip("/")
        if normalized == "api" or normalized.startswith(_RESERVED_BACKEND_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = (resolved_dist / normalized).resolve()
        if candidate.is_relative_to(resolved_dist) and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(index_file)


def create_app(
    settings: AppSettings | None = None,
    *,
    service_container: ServiceContainer | None = None,
) -> FastAPI:
    """Build the Brew FastAPI application with ADK, A2A, health, v1 API, and SPA routes."""
    resolved_settings = settings or get_settings()
    enforce_telemetry_privacy_defaults(resolved_settings)
    configure_structured_logging(
        resolved_settings.log_level,
        gcp_project_id=resolved_settings.resolved_gcp_project_for_telemetry,
    )

    has_built_spa = (resolved_settings.web_dist_dir / "index.html").is_file()
    enable_adk_web = resolved_settings.enable_adk_web_ui and not has_built_spa

    resolved_container = (
        service_container
        if service_container is not None
        else build_service_container(resolved_settings)
    )
    coaching_deps = CoachingToolDependencies(
        preferences_reader=resolved_container.preferences_repo,
        contact_reader=resolved_container.contact_repo,
        meeting_reader=resolved_container.meeting_repo,
        memory_reader=resolved_container.memory_repo,
        proposal_stager=resolved_container.proposal_repo,
        proposal_agent=resolved_container.proposal_agent,
        clock=resolved_container.clock,
        id_generator=resolved_container.id_generator,
        io_timeout_seconds=resolved_settings.firestore_timeout_seconds,
    )
    set_default_coaching_dependencies(coaching_deps)

    @contextlib.asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
        from app.agent import build_adk_app, build_conversation_coach_agent

        active_agent = build_conversation_coach_agent(
            resolved_settings,
            tool_dependencies=coaching_deps,
        )
        adk_app = build_adk_app(
            resolved_settings,
            tool_dependencies=coaching_deps,
            root_agent_override=active_agent,
        )

        session_service = (
            SessionServiceFactory(settings=resolved_settings, base_dir=AGENT_DIR).create()
            if settings is not None
            else services.get_session_service()
        )
        runner = Runner(
            app=adk_app,
            session_service=session_service,
            artifact_service=services.get_artifact_service(),
            auto_create_session=True,
        )
        fastapi_app.state.runner = runner
        fastapi_app.state.session_service = session_service
        fastapi_app.state.agent_app_name = adk_app.name

        if not getattr(fastapi_app.state, "a2a_routes_attached", False):
            await attach_a2a_routes(
                fastapi_app,
                agent=active_agent,
                runner=runner,
                task_store=InMemoryTaskStore(),
                rpc_path=f"/a2a/{adk_app.name}",
                agent_version=resolved_settings.app_version,
                app_url=resolved_settings.app_url,
            )
            fastapi_app.state.a2a_routes_attached = True

        if has_built_spa and not getattr(fastapi_app.state, "spa_routes_attached", False):
            _attach_spa_routes(fastapi_app, resolved_settings.web_dist_dir)
            fastapi_app.state.spa_routes_attached = True

        logger.info(
            "Brew FastAPI runtime initialized",
            extra={
                "event_type": "server.startup",
                "operation_name": "server.startup",
                "agent_name": active_agent.name,
                "agent_version": resolved_settings.app_version,
                "model_name": resolved_settings.gemini_model,
                "result_status": "ok",
            },
        )
        try:
            yield
        finally:
            # Give in-flight background jobs a short grace period before the loop closes.
            await resolved_container.job_runner.drain(timeout_seconds=5.0)

    effective_session_uri = (
        "memory://"
        if settings is not None
        and resolved_settings.session_backend in {"in_memory", "auto"}
        and resolved_settings.persistence_backend == "in_memory"
        and not os.environ.get("SESSION_SERVICE_URI")
        else services.SESSION_SERVICE_URI
    )
    fastapi_app: FastAPI = get_fast_api_app(
        agents_dir=AGENT_DIR,
        web=enable_adk_web,
        artifact_service_uri=services.ARTIFACT_SERVICE_URI,
        allow_origins=resolved_settings.allow_origins or None,
        session_service_uri=effective_session_uri,
        otel_to_cloud=resolved_settings.otel_enabled,
        lifespan=lifespan,
    )
    ensure_tracer_provider(
        resolved_settings,
        attach_cloud_trace_exporter=bool(
            resolved_settings.cloud_trace_enabled and not resolved_settings.otel_enabled
        ),
    )

    fastapi_app.state.settings = resolved_settings
    fastapi_app.state.settings_pinned = settings is not None
    fastapi_app.state.env_mtime_ns = (
        (REPO_ROOT / ".env").stat().st_mtime_ns if (REPO_ROOT / ".env").is_file() else None
    )
    fastapi_app.state.adc_mtime_ns = resolve_adc_file_mtime_ns()
    fastapi_app.state.service_container = resolved_container
    fastapi_app.state.coaching_tool_dependencies = coaching_deps
    fastapi_app.title = resolved_settings.app_name
    fastapi_app.version = resolved_settings.app_version
    fastapi_app.description = "Brew — AI-powered Coffee Chat Buddy API"

    register_exception_handlers(fastapi_app)
    _install_http_tracing_middleware(fastapi_app)
    fastapi_app.add_middleware(_DeployedWebSocketAuthMiddleware, fastapi_app=fastapi_app)

    fastapi_app.include_router(health_router)
    fastapi_app.include_router(auth_router)
    fastapi_app.include_router(v1_router)
    return fastapi_app


app: FastAPI = create_app()


if __name__ == "__main__":
    from app.server import main

    main()
