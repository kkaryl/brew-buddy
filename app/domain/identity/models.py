"""Authenticated caller identity."""

from __future__ import annotations

from app.domain.shared.base import ImmutableDomainModel
from app.domain.shared.types import EntityId, ShortLabelText


class AuthenticatedPrincipal(ImmutableDomainModel):
    """Authenticated caller identity resolved by the authentication port."""

    user_id: EntityId
    display_name: ShortLabelText | None = None
