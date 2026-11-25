"""v1 routes for inspecting and customizing the authenticated caller profile."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_current_principal,
    get_memory_service,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    AuthenticatedPrincipalResponse,
    UpdateAuthenticatedProfileRequest,
)
from app.application.memory.service import MemoryService
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.memory.models import UserPreferences
from app.domain.shared.errors import PersistenceOperationError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
)


def _resolve_provider_tier(principal: AuthenticatedPrincipal) -> str:
    return (
        "verified"
        if principal.user_id.startswith(("firebase:", "google:", "iap:"))
        else "local_mock"
    )


def _build_principal_response(
    principal: AuthenticatedPrincipal,
    preferences: UserPreferences | None,
) -> AuthenticatedPrincipalResponse:
    custom_name = preferences.preferred_display_name if preferences is not None else None
    effective_name = custom_name if custom_name is not None else principal.display_name
    return AuthenticatedPrincipalResponse(
        user_id=principal.user_id,
        display_name=effective_name,
        custom_display_name=custom_name,
        account_display_name=principal.display_name,
        auth_provider=_resolve_provider_tier(principal),
    )


@router.get(
    "/auth/me",
    response_model=AuthenticatedPrincipalResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
    summary="Inspect the authenticated user principal",
)
async def get_authenticated_me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> AuthenticatedPrincipalResponse:
    """Verify the caller's Bearer token and return the resolved identity and custom display name."""
    prefs: UserPreferences | None = None
    try:
        prefs = await memory_service.get_user_preferences(principal=principal)
    except (TimeoutError, PersistenceOperationError):
        logger.warning(
            "Unable to load custom display name from preferences; falling back to token profile",
            extra={"event_type": "auth.profile_preferences.degraded"},
        )
    return _build_principal_response(principal, prefs)


@router.patch(
    "/auth/me",
    response_model=AuthenticatedPrincipalResponse,
    status_code=status.HTTP_200_OK,
    tags=["auth"],
    summary="Set or reset the authenticated user's custom display name",
)
async def update_authenticated_me(
    payload: UpdateAuthenticatedProfileRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> AuthenticatedPrincipalResponse:
    """Persist a custom display name override (or clear it when null) for the signed-in user."""
    prefs = await memory_service.update_preferred_display_name(
        principal=principal,
        display_name=payload.display_name,
    )
    return _build_principal_response(principal, prefs)
