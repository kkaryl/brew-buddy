"""FastAPI application factory integrating Google ADK, A2A, telemetry, health, and SPA hosting."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.api.health import router as health_router
from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.config import AppSettings, get_settings
from app.domain.errors import BrewDomainError
from app.infrastructure.observability import configure_structured_logging

load_dotenv()

logger = logging.getLogger(__name__)

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
)


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


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Build the Brew FastAPI application with ADK, A2A, health, and optional static SPA routes."""
    resolved_settings = settings or get_settings()
    configure_structured_logging(resolved_settings.log_level)

    has_built_spa = (resolved_settings.web_dist_dir / "index.html").is_file()
    enable_adk_web = resolved_settings.enable_adk_web_ui and not has_built_spa

    @contextlib.asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
        from app.agent import app as adk_app
        from app.agent import root_agent

        runner = Runner(
            app=adk_app,
            session_service=services.get_session_service(),
            artifact_service=services.get_artifact_service(),
            auto_create_session=True,
        )
        fastapi_app.state.runner = runner
        fastapi_app.state.agent_app_name = adk_app.name

        if not getattr(fastapi_app.state, "a2a_routes_attached", False):
            await attach_a2a_routes(
                fastapi_app,
                agent=root_agent,
                runner=runner,
                task_store=InMemoryTaskStore(),
                rpc_path=f"/a2a/{adk_app.name}",
                agent_version=resolved_settings.app_version,
            )
            fastapi_app.state.a2a_routes_attached = True

        if has_built_spa and not getattr(fastapi_app.state, "spa_routes_attached", False):
            _attach_spa_routes(fastapi_app, resolved_settings.web_dist_dir)
            fastapi_app.state.spa_routes_attached = True

        logger.info(
            "Brew FastAPI runtime initialized",
            extra={
                "event_type": "server.startup",
                "agent_name": root_agent.name,
            },
        )
        yield

    fastapi_app: FastAPI = get_fast_api_app(
        agents_dir=AGENT_DIR,
        web=enable_adk_web,
        artifact_service_uri=services.ARTIFACT_SERVICE_URI,
        allow_origins=resolved_settings.allow_origins or None,
        session_service_uri=services.SESSION_SERVICE_URI,
        otel_to_cloud=resolved_settings.otel_enabled,
        lifespan=lifespan,
    )
    fastapi_app.state.settings = resolved_settings
    fastapi_app.title = resolved_settings.app_name
    fastapi_app.version = resolved_settings.app_version
    fastapi_app.description = "Brew — AI-powered Coffee Chat Buddy API"

    @fastapi_app.exception_handler(BrewDomainError)
    async def handle_domain_error(request: Request, exc: BrewDomainError) -> JSONResponse:
        del request
        status_code = 400 if exc.recoverable else 500
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    fastapi_app.include_router(health_router)
    return fastapi_app


app: FastAPI = create_app()


if __name__ == "__main__":
    from app.server import main

    main()
