"""HTTP response contract for the authenticated caller identity."""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ResponseModel


class AuthenticatedPrincipalResponse(ResponseModel):
    """Serialized authenticated caller profile returned by ``GET /api/v1/auth/me``."""

    user_id: str = Field(description="Verified or isolated local user identifier.")
    display_name: str | None = Field(
        default=None,
        description="Human-readable display name when present.",
    )
    auth_provider: str = Field(
        description="Authentication provider tier ('verified' or 'local_mock').",
    )
