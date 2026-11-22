"""FastAPI dependency wiring for authentication, repositories, and application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.services import (
    BriefService,
    ContactService,
    MeetingService,
    MemoryService,
)
from app.domain.errors import AuthenticationError
from app.domain.models import AuthenticatedPrincipal
from app.infrastructure.fakes import FakeServiceContainer

bearer_security = HTTPBearer(
    auto_error=False,
    description="Opaque or JWT Bearer token resolving the authenticated Brew user.",
)


def get_service_container(request: Request) -> FakeServiceContainer:
    """Resolve the injected ``FakeServiceContainer`` attached to FastAPI application state."""
    container: FakeServiceContainer | None = getattr(
        request.app.state,
        "service_container",
        None,
    )
    if container is None:
        container = FakeServiceContainer()
        request.app.state.service_container = container
    return container


def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    container: Annotated[FakeServiceContainer, Depends(get_service_container)],
) -> AuthenticatedPrincipal:
    """Resolve user identity strictly from HTTP Bearer authentication."""
    raw_header = request.headers.get("authorization")
    if not raw_header or not raw_header.strip():
        raise AuthenticationError("Missing Authorization Bearer header.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authorization header must use the Bearer scheme.")
    return container.authenticator.authenticate_bearer_token(credentials.credentials)


def get_contact_service(
    container: Annotated[FakeServiceContainer, Depends(get_service_container)],
) -> ContactService:
    """Construct ``ContactService`` with injected ports."""
    return ContactService(
        contact_repo=container.contact_repo,
        clock=container.clock,
        id_generator=container.id_generator,
    )


def get_meeting_service(
    container: Annotated[FakeServiceContainer, Depends(get_service_container)],
) -> MeetingService:
    """Construct ``MeetingService`` with injected ports."""
    return MeetingService(
        meeting_repo=container.meeting_repo,
        contact_repo=container.contact_repo,
    )


def get_brief_service(
    container: Annotated[FakeServiceContainer, Depends(get_service_container)],
) -> BriefService:
    """Construct ``BriefService`` with injected ports."""
    return BriefService(
        contact_repo=container.contact_repo,
        meeting_repo=container.meeting_repo,
        brief_repo=container.brief_repo,
        memory_repo=container.memory_repo,
        preferences_repo=container.preferences_repo,
        brief_agent=container.brief_agent,
        clock=container.clock,
        id_generator=container.id_generator,
    )


def get_memory_service(
    container: Annotated[FakeServiceContainer, Depends(get_service_container)],
) -> MemoryService:
    """Construct ``MemoryService`` with injected ports."""
    return MemoryService(
        proposal_repo=container.proposal_repo,
        memory_repo=container.memory_repo,
        contact_repo=container.contact_repo,
        meeting_repo=container.meeting_repo,
        brief_repo=container.brief_repo,
        proposal_agent=container.proposal_agent,
        clock=container.clock,
        id_generator=container.id_generator,
    )
