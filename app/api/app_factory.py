"""FastAPI application factory integrating Google ADK, A2A, telemetry, health and the SPA."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator

from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.agents.tools.dependencies import (
    CoachingToolDependencies,
    set_default_coaching_dependencies,
)
from app.api.auth import router as auth_router
from app.api.errors import (
    register_exception_handlers,
)
from app.api.health import resolve_adc_file_mtime_ns
from app.api.health import router as health_router
from app.api.middleware.adk_surface_auth import DeployedWebSocketAuthMiddleware
from app.api.middleware.tracing import install_http_tracing_middleware
from app.api.routers.api_v1 import router as v1_router
from app.api.spa import attach_spa_routes
from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.composition.builders import build_service_container
from app.composition.container import ServiceContainer
from app.config import REPO_ROOT, AppSettings, get_settings
from app.infrastructure.observability import (
    configure_structured_logging,
    enforce_telemetry_privacy_defaults,
    ensure_tracer_provider,
)
from app.infrastructure.sessions import SessionServiceFactory

logger = logging.getLogger(__name__)


# The directory that contains the `app` package, three levels above this file.
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
            attach_spa_routes(fastapi_app, resolved_settings.web_dist_dir)
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
    install_http_tracing_middleware(fastapi_app)
    fastapi_app.add_middleware(DeployedWebSocketAuthMiddleware, fastapi_app=fastapi_app)

    fastapi_app.include_router(health_router)
    fastapi_app.include_router(auth_router)
    fastapi_app.include_router(v1_router)
    return fastapi_app
