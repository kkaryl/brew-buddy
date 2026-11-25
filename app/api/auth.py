"""Public auth bootstrap metadata and local-only isolated mock session endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_service_container
from app.api.health import get_app_settings
from app.composition.container import ServiceContainer
from app.config import AppSettings
from app.domain.shared.errors import AuthorizationError
from app.infrastructure.identity.mock_sessions import LOCAL_MOCK_PERSONAS
from app.infrastructure.identity.runtime import RuntimeAuthenticator

router = APIRouter(prefix="/api/auth", tags=["auth"])


class FirebaseClientConfigResponse(BaseModel):
    """Non-secret Firebase Web configuration required to launch Google Sign-In in the browser."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(description="Firebase / Google Cloud project identifier.")
    api_key: str = Field(description="Public Firebase Web API key configured on the server.")
    auth_domain: str = Field(description="Firebase Auth domain for OAuth popup/redirect flows.")


class MockPersonaOptionResponse(BaseModel):
    """Isolated local test persona descriptor surfaced only when local mock auth is enabled."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_id: str = Field(description="Short persona identifier ('alice' or 'bob').")
    display_name: str = Field(description="Human-readable local demo name.")
    role_summary: str = Field(description="Workspace isolation description.")


class AuthClientConfigResponse(BaseModel):
    """Runtime authentication capabilities returned by ``GET /api/auth/config``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    auth_mode: Literal["verified", "local_mock"] = Field(
        description="Effective authentication enforcement mode.",
    )
    environment: str = Field(description="Active runtime environment name.")
    local_mock_enabled: bool = Field(
        description="True strictly in local/test modes; always False in deployed environments.",
    )
    google_sign_in_enabled: bool = Field(
        description="True when Firebase Auth or Google OAuth client configuration is available.",
    )
    firebase: FirebaseClientConfigResponse | None = Field(
        default=None,
        description="Firebase web config when configured via server environment variables.",
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        description="Google Identity Services OAuth 2.0 Web Client ID when configured.",
    )
    mock_personas: list[MockPersonaOptionResponse] = Field(
        default_factory=list,
        description="Available isolated local personas when local_mock_enabled is True.",
    )


class CreateMockSessionRequest(BaseModel):
    """Request payload for ``POST /api/auth/mock-session`` (local/test environments only)."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(
        default="alice",
        min_length=1,
        max_length=32,
        description="Isolated local persona key ('alice' or 'bob').",
    )


class AuthSessionPrincipalResponse(BaseModel):
    """Authenticated principal summary returned upon session bootstrap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(description="Canonical isolated user identifier.")
    display_name: str | None = Field(default=None, description="Display name for UI chrome.")
    auth_provider: Literal["verified", "local_mock"] = Field(
        description="Originating identity provider tier.",
    )


class MockSessionResponse(BaseModel):
    """Ephemeral session response returned only in local/test environments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    access_token: str = Field(description="Short-lived local mock Bearer token.")
    token_type: Literal["Bearer"] = Field(default="Bearer", description="HTTP auth scheme.")
    expires_at: datetime = Field(description="UTC timestamp when this mock session expires.")
    principal: AuthSessionPrincipalResponse = Field(
        description="Isolated mock principal bound to the session.",
    )


@router.get(
    "/config",
    response_model=AuthClientConfigResponse,
    include_in_schema=False,
)
def get_auth_config(
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> AuthClientConfigResponse:
    """Return browser sign-in configuration without exposing secrets in static frontend code."""
    local_mock = settings.local_mock_auth_enabled
    project_id = settings.resolved_firebase_project_id
    web_api_key = (settings.firebase_web_api_key or "").strip() or None
    explicit_domain = (settings.firebase_auth_domain or "").strip() or None
    google_client_id = (settings.google_oauth_client_id or "").strip() or None

    firebase_cfg: FirebaseClientConfigResponse | None = None
    if project_id and web_api_key:
        firebase_cfg = FirebaseClientConfigResponse(
            project_id=project_id,
            api_key=web_api_key,
            auth_domain=explicit_domain or f"{project_id}.firebaseapp.com",
        )

    personas = (
        [
            MockPersonaOptionResponse(
                persona_id=p.persona_id,
                display_name=p.display_name,
                role_summary=p.role_summary,
            )
            for p in LOCAL_MOCK_PERSONAS
        ]
        if local_mock
        else []
    )

    return AuthClientConfigResponse(
        auth_mode="local_mock" if local_mock else "verified",
        environment=settings.environment,
        local_mock_enabled=local_mock,
        google_sign_in_enabled=bool(firebase_cfg or google_client_id),
        firebase=firebase_cfg,
        google_oauth_client_id=google_client_id,
        mock_personas=personas,
    )


@router.post(
    "/mock-session",
    response_model=MockSessionResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_local_mock_session(
    settings: Annotated[AppSettings, Depends(get_app_settings)],
    container: Annotated[ServiceContainer, Depends(get_service_container)],
    payload: Annotated[CreateMockSessionRequest | None, Body()] = None,
) -> MockSessionResponse:
    """Issue a short-lived isolated mock session strictly when local_mock_auth_enabled is True."""
    if not settings.local_mock_auth_enabled:
        raise AuthorizationError(
            "Local mock authentication is disabled in deployed environments.",
            code="MOCK_AUTH_DISABLED",
        )

    authenticator = container.authenticator
    if not isinstance(authenticator, RuntimeAuthenticator):
        raise AuthorizationError(
            "Active service authenticator does not support local mock session issuance.",
            code="MOCK_AUTH_DISABLED",
        )

    resolved_payload = payload or CreateMockSessionRequest()
    issued = authenticator.issue_local_mock_session(resolved_payload.persona_id)
    return MockSessionResponse(
        access_token=issued.access_token,
        expires_at=issued.expires_at,
        principal=AuthSessionPrincipalResponse(
            user_id=issued.principal.user_id,
            display_name=issued.principal.display_name,
            auth_provider="local_mock",
        ),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
def revoke_local_mock_session(
    request: Request,
    container: Annotated[ServiceContainer, Depends(get_service_container)],
) -> Response:
    """Best-effort revocation for local mock sessions on sign-out."""
    raw_auth = (request.headers.get("authorization") or "").strip()
    if raw_auth.lower().startswith("bearer "):
        token = raw_auth[7:].strip()
        authenticator = container.authenticator
        if isinstance(authenticator, RuntimeAuthenticator) and authenticator.local_mock_enabled:
            authenticator.mock_registry.revoke_session(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
