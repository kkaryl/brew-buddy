"""v1 route for inspecting the authenticated caller identity."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_current_principal,
)
from app.api.routers.error_responses import STANDARD_ERROR_RESPONSES
from app.api.schemas import (
    AuthenticatedPrincipalResponse,
)
from app.domain.identity.models import AuthenticatedPrincipal

router = APIRouter(
    prefix="/api/v1",
    responses=STANDARD_ERROR_RESPONSES,
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
) -> AuthenticatedPrincipalResponse:
    """Verify the caller's Bearer token and return the resolved identity boundary."""
    provider = (
        "verified"
        if principal.user_id.startswith(("firebase:", "google:", "iap:"))
        else "local_mock"
    )
    return AuthenticatedPrincipalResponse(
        user_id=principal.user_id,
        display_name=principal.display_name,
        auth_provider=provider,
    )
