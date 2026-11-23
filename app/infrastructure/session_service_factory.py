"""Factory constructing ADK session services while isolating domain Firestore collections."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.utils.service_factory import create_session_service_from_options
from google.adk.integrations.firestore.firestore_session_service import (
    FirestoreSessionService,
)
from google.adk.sessions import BaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.cloud import firestore

from app.config import AppSettings, get_settings
from app.domain.errors import InvalidConfigurationError
from app.infrastructure.firestore_repositories import (
    BRIEFS_SUBCOLLECTION,
    CONTACTS_SUBCOLLECTION,
    DELETED_MEMORIES_SUBCOLLECTION,
    MEETINGS_SUBCOLLECTION,
    MEMORIES_SUBCOLLECTION,
    MEMORY_PROPOSALS_SUBCOLLECTION,
    PREFERENCES_SUBCOLLECTION,
    USERS_COLLECTION,
)

DEFAULT_ADK_SESSION_COLLECTION = "adk-session"

_DOMAIN_COLLECTION_NAMES = frozenset(
    {
        USERS_COLLECTION,
        PREFERENCES_SUBCOLLECTION,
        CONTACTS_SUBCOLLECTION,
        MEETINGS_SUBCOLLECTION,
        BRIEFS_SUBCOLLECTION,
        MEMORIES_SUBCOLLECTION,
        DELETED_MEMORIES_SUBCOLLECTION,
        MEMORY_PROPOSALS_SUBCOLLECTION,
    }
)


def validate_isolated_session_collection(root_collection: str) -> str:
    """Ensure the ADK Firestore session root collection never overlaps domain collections."""
    cleaned = root_collection.strip()
    if not cleaned or "/" in cleaned:
        raise InvalidConfigurationError(
            "ADK Firestore session root_collection must be a non-empty top-level collection name."
        )
    if cleaned in _DOMAIN_COLLECTION_NAMES:
        raise InvalidConfigurationError(
            f"ADK session collection '{cleaned}' overlaps Brew domain storage; "
            "session events must remain isolated from domain collections."
        )
    return cleaned


def create_firestore_async_client(
    *,
    project: str | None = None,
    database: str = "(default)",
) -> firestore.AsyncClient:
    """Construct a non-blocking ``firestore.AsyncClient`` honoring emulator settings."""
    resolved_project = (
        project
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ("brew-local" if os.environ.get("FIRESTORE_EMULATOR_HOST") else None)
    )
    return firestore.AsyncClient(project=resolved_project, database=database)


def create_adk_firestore_session_service(
    *,
    client: firestore.AsyncClient | None = None,
    project: str | None = None,
    database: str = "(default)",
    root_collection: str = DEFAULT_ADK_SESSION_COLLECTION,
) -> FirestoreSessionService:
    """Create the official ADK ``FirestoreSessionService`` on an isolated root collection."""
    validated_collection = validate_isolated_session_collection(root_collection)
    resolved_client = client or create_firestore_async_client(
        project=project,
        database=database,
    )
    return FirestoreSessionService(
        client=resolved_client,
        root_collection=validated_collection,
    )


class SessionServiceFactory:
    """Factory creating the appropriate ADK ``BaseSessionService`` for the active environment."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        firestore_client: firestore.AsyncClient | None = None,
        base_dir: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._firestore_client = firestore_client
        self._base_dir = base_dir or str(self._settings.web_dist_dir.parent.parent)

    def create(self) -> BaseSessionService:
        """Instantiate an ADK ``BaseSessionService`` according to configuration."""
        explicit_uri = os.environ.get("SESSION_SERVICE_URI", "").strip()
        if explicit_uri and explicit_uri != "shared://session":
            if explicit_uri.startswith("firestore://"):
                parsed = urlparse(explicit_uri)
                collection = (
                    parsed.netloc
                    or parsed.path.lstrip("/")
                    or self._settings.adk_firestore_root_collection
                )
                return create_adk_firestore_session_service(
                    client=self._firestore_client,
                    project=self._settings.google_cloud_project,
                    database=self._settings.firestore_database,
                    root_collection=collection,
                )
            service: BaseSessionService = create_session_service_from_options(
                base_dir=self._base_dir,
                session_service_uri=explicit_uri,
            )
            return service

        backend = self._settings.session_backend
        if backend == "firestore":
            return create_adk_firestore_session_service(
                client=self._firestore_client,
                project=self._settings.google_cloud_project,
                database=self._settings.firestore_database,
                root_collection=self._settings.adk_firestore_root_collection,
            )

        if backend == "vertex_ai":
            from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

            agent_engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
            return VertexAiSessionService(
                project=self._settings.google_cloud_project,
                location=(
                    os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
                    or self._settings.google_cloud_location
                ),
                agent_engine_id=agent_engine_id,
            )

        if backend == "in_memory":
            return InMemorySessionService()

        # backend == "auto"
        if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
            from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

            return VertexAiSessionService(
                project=self._settings.google_cloud_project,
                location=(
                    os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
                    or self._settings.google_cloud_location
                ),
                agent_engine_id=agent_engine_id,
            )

        if self._settings.persistence_backend == "firestore":
            return create_adk_firestore_session_service(
                client=self._firestore_client,
                project=self._settings.google_cloud_project,
                database=self._settings.firestore_database,
                root_collection=self._settings.adk_firestore_root_collection,
            )

        return InMemorySessionService()


def _firestore_uri_factory(uri: str, **kwargs: Any) -> BaseSessionService:
    del kwargs
    parsed = urlparse(uri)
    settings = get_settings()
    collection = parsed.netloc or parsed.path.lstrip("/") or settings.adk_firestore_root_collection
    return create_adk_firestore_session_service(
        project=settings.google_cloud_project,
        database=settings.firestore_database,
        root_collection=collection,
    )


def register_firestore_session_scheme() -> None:
    """Register ``firestore://`` session URI scheme with the ADK service registry."""
    get_service_registry().register_session_service("firestore", _firestore_uri_factory)
