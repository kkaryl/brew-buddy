"""FastAPI dependency wiring for authentication, repositories, and async application services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.health import get_app_settings
from app.application.briefs.inputs import BriefWorkflowSafeguardConfig
from app.application.briefs.service import BriefService
from app.application.contacts.service import ContactService
from app.application.meetings.service import MeetingService
from app.application.memory.jobs import MemoryExtractionJobService
from app.application.memory.persistence import MemoryPersistenceService
from app.application.memory.retrieval import MemoryRetrievalService
from app.application.memory.service import MemoryService
from app.composition.builders import build_service_container
from app.composition.container import ServiceContainer
from app.config import AppSettings, get_settings
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.errors import AuthenticationError
from app.infrastructure.identity.runtime import RuntimeAuthenticator

bearer_security = HTTPBearer(
    auto_error=False,
    description="Opaque or JWT Bearer token resolving the authenticated Brew user.",
)


def get_service_container(request: Request) -> ServiceContainer:
    """Resolve the injected ``ServiceContainer`` attached to FastAPI application state."""
    settings = get_app_settings(request)
    container: ServiceContainer | None = getattr(
        request.app.state,
        "service_container",
        None,
    )
    if container is None:
        container = build_service_container(settings)
        request.app.state.service_container = container
    return container


def resolve_authenticated_principal_from_request(
    request: Request,
    container: ServiceContainer,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> AuthenticatedPrincipal:
    """Resolve user identity from HTTP Bearer token or verified Cloud Run IAP assertion."""
    raw_header = (request.headers.get("authorization") or "").strip()
    iap_assertion = (request.headers.get("x-goog-iap-jwt-assertion") or "").strip()
    authenticator = container.authenticator

    if raw_header:
        if credentials is not None:
            if credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
                raise AuthenticationError("Authorization header must use the Bearer scheme.")
            bearer_token = credentials.credentials
        else:
            scheme, _, remainder = raw_header.partition(" ")
            if scheme.lower() != "bearer" or not remainder.strip():
                raise AuthenticationError("Authorization header must use the Bearer scheme.")
            bearer_token = remainder.strip()

        try:
            return authenticator.authenticate_bearer_token(bearer_token)
        except AuthenticationError as exc:
            if (
                exc.code != "TOKEN_EXPIRED"
                and iap_assertion
                and isinstance(authenticator, RuntimeAuthenticator)
                and authenticator.is_iap_configured
            ):
                return authenticator.authenticate_iap_assertion(iap_assertion)
            raise

    if iap_assertion and isinstance(authenticator, RuntimeAuthenticator):
        return authenticator.authenticate_iap_assertion(iap_assertion)

    raise AuthenticationError("Missing Authorization Bearer header.")


async def resolve_authenticated_principal_off_event_loop(
    request: Request,
    container: ServiceContainer,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> AuthenticatedPrincipal:
    """Resolve the caller's identity on a worker thread.

    Token verification is synchronous and may call Google over HTTPS (signing certificates,
    ``tokeninfo``, ``userinfo``). Running it inline in an ``async`` handler would stall every
    other in-flight request on the event loop for the duration of those calls.
    """
    return await run_in_threadpool(
        resolve_authenticated_principal_from_request,
        request,
        container,
        credentials,
    )


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> AuthenticatedPrincipal:
    """Resolve user identity strictly from verified HTTP Bearer or IAP authentication."""
    return await resolve_authenticated_principal_off_event_loop(
        request,
        container,
        credentials,
    )


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


def get_memory_extraction_job_service(
    request: Request,
    container: Annotated[ServiceContainer, Depends(get_service_container)],
    memory_persistence: Annotated[
        MemoryPersistenceService, Depends(get_memory_persistence_service)
    ],
) -> MemoryExtractionJobService:
    """Construct ``MemoryExtractionJobService`` over the shared job store and runner."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return MemoryExtractionJobService(
        persistence=memory_persistence,
        job_repo=container.job_repo,
        proposal_repo=container.proposal_repo,
        job_runner=container.job_runner,
        clock=container.clock,
        id_generator=container.id_generator,
        stale_after_seconds=settings.memory_job_stale_after_seconds,
    )
