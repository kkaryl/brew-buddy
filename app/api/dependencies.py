"""FastAPI dependency wiring for authentication, repositories, and async application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.brief_workflow import BriefWorkflowSafeguardConfig
from app.application.memory_persistence_service import MemoryPersistenceService
from app.application.memory_retrieval_service import MemoryRetrievalService
from app.application.services import (
    BriefService,
    ContactService,
    MeetingService,
    MemoryService,
)
from app.config import AppSettings, get_settings
from app.domain.errors import AuthenticationError
from app.domain.models import AuthenticatedPrincipal
from app.infrastructure.container import build_service_container
from app.infrastructure.fakes import ServiceContainer

bearer_security = HTTPBearer(
    auto_error=False,
    description="Opaque or JWT Bearer token resolving the authenticated Brew user.",
)


def get_service_container(request: Request) -> ServiceContainer:
    """Resolve the injected ``ServiceContainer`` attached to FastAPI application state."""
    container: ServiceContainer | None = getattr(
        request.app.state,
        "service_container",
        None,
    )
    if container is None:
        settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
        container = build_service_container(settings)
        request.app.state.service_container = container
    return container


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> AuthenticatedPrincipal:
    """Resolve user identity strictly from HTTP Bearer authentication."""
    raw_header = request.headers.get("authorization")
    if not raw_header or not raw_header.strip():
        raise AuthenticationError("Missing Authorization Bearer header.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authorization header must use the Bearer scheme.")
    return container.authenticator.authenticate_bearer_token(credentials.credentials)


def get_contact_service(
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> ContactService:
    """Construct ``ContactService`` with injected ports."""
    return ContactService(
        contact_repo=container.contact_repo,
        clock=container.clock,
        id_generator=container.id_generator,
    )


def get_meeting_service(
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> MeetingService:
    """Construct ``MeetingService`` with injected ports."""
    return MeetingService(
        meeting_repo=container.meeting_repo,
        contact_repo=container.contact_repo,
    )


def get_memory_retrieval_service(
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> MemoryRetrievalService:
    """Construct ``MemoryRetrievalService`` with injected user-scoped repository ports."""
    return MemoryRetrievalService(
        preferences_repo=container.preferences_repo,
        contact_repo=container.contact_repo,
        meeting_repo=container.meeting_repo,
        memory_repo=container.memory_repo,
    )


def get_memory_persistence_service(
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> MemoryPersistenceService:
    """Construct ``MemoryPersistenceService`` with injected repository and agent ports."""
    return MemoryPersistenceService(
        preferences_repo=container.preferences_repo,
        proposal_repo=container.proposal_repo,
        memory_repo=container.memory_repo,
        contact_repo=container.contact_repo,
        meeting_repo=container.meeting_repo,
        brief_repo=container.brief_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
    )


def get_brief_service(
    request: Request,
    container: Annotated[ServiceContainer, Depends(get_service_container)],
    memory_retrieval: Annotated[MemoryRetrievalService, Depends(get_memory_retrieval_service)],
    memory_persistence: Annotated[
        MemoryPersistenceService, Depends(get_memory_persistence_service)
    ],
) -> BriefService:
    """Construct ``BriefService`` wired with retrieval, persistence, and workflow safeguards."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    safeguards = BriefWorkflowSafeguardConfig(
        max_model_invocations=settings.workflow_max_model_invocations,
        max_tool_retries=settings.workflow_max_tool_retries,
        context_io_timeout_seconds=settings.firestore_timeout_seconds,
    )
    return BriefService(
        meeting_repo=container.meeting_repo,
        brief_repo=container.brief_repo,
        memory_retrieval=memory_retrieval,
        memory_persistence=memory_persistence,
        brief_agent=container.brief_agent,
        clock=container.clock,
        id_generator=container.id_generator,
        idempotency_repo=container.idempotency_repo,
        safeguards=safeguards,
    )


def get_memory_service(
    memory_retrieval: Annotated[MemoryRetrievalService, Depends(get_memory_retrieval_service)],
    memory_persistence: Annotated[
        MemoryPersistenceService, Depends(get_memory_persistence_service)
    ],
) -> MemoryService:
    """Construct ``MemoryService`` facade over retrieval and persistence services."""
    return MemoryService(
        retrieval=memory_retrieval,
        persistence=memory_persistence,
    )
