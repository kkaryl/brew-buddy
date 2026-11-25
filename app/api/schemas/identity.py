"""HTTP request and response contracts for the authenticated caller identity."""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ResponseModel, StrictRequestModel
from app.domain.shared.types import ShortLabelText


class AuthenticatedPrincipalResponse(ResponseModel):
    """Serialized authenticated caller profile returned by ``GET/PATCH /api/v1/auth/me``."""

    user_id: str = Field(description="Verified or isolated local user identifier.")
    display_name: str | None = Field(
        default=None,
        description=(
            "Effective human-readable display name (custom user name when set, otherwise "
            "the default Google or identity provider name)."
        ),
    )
    custom_display_name: str | None = Field(
        default=None,
        description="Custom display name chosen by the user, or null when using the default name.",
    )
    account_display_name: str | None = Field(
        default=None,
        description="Default display name supplied by the Google or local identity provider.",
    )
    auth_provider: str = Field(
        description="Authentication provider tier ('verified' or 'local_mock').",
    )


class UpdateAuthenticatedProfileRequest(StrictRequestModel):
    """Request payload for ``PATCH /api/v1/auth/me``."""

    display_name: ShortLabelText | None = Field(
        description=(
            "Custom display name (1 to 120 characters) to use instead of the default Google "
            "account name, or null to revert to the default account name."
        ),
    )
