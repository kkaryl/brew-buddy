"""Process-wide ADK session/artifact services shared by every serving surface.

Registered under ``shared://`` so the ADK web routes, the A2A path, and the
reasoning_engine adapter share one instance: a session created on any surface
is visible to the others.
"""

from __future__ import annotations

import functools
import os
from typing import Any

from google.adk.artifacts import BaseArtifactService, GcsArtifactService, InMemoryArtifactService
from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.utils.service_factory import create_session_service_from_options
from google.adk.sessions import BaseSessionService

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@functools.cache
def get_session_service() -> BaseSessionService:
    """Process-wide session service shared across every serving surface."""
    if uri := os.environ.get("SESSION_SERVICE_URI"):
        service: BaseSessionService = create_session_service_from_options(
            base_dir=_AGENT_DIR, session_service_uri=uri
        )
        return service
    if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

        return VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_LOCATION"),
            agent_engine_id=agent_engine_id,
        )
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return InMemorySessionService()


@functools.cache
def get_artifact_service() -> BaseArtifactService:
    """Process-wide artifact service: GCS when a bucket is set, else in-memory."""
    if bucket := os.environ.get("LOGS_BUCKET_NAME"):
        return GcsArtifactService(bucket_name=bucket)
    return InMemoryArtifactService()


def _resolve_shared_session(uri: str, **kwargs: Any) -> BaseSessionService:
    del uri, kwargs
    return get_session_service()


def _resolve_shared_artifact(uri: str, **kwargs: Any) -> BaseArtifactService:
    del uri, kwargs
    return get_artifact_service()


_registry = get_service_registry()
_registry.register_session_service("shared", _resolve_shared_session)
_registry.register_artifact_service("shared", _resolve_shared_artifact)
