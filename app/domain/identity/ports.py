"""Authentication port."""

from __future__ import annotations

from typing import Protocol

from app.domain.identity.models import AuthenticatedPrincipal


class AuthenticatorPort(Protocol):
    """Port verifying bearer credentials and returning the authenticated principal."""

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Validate ``token`` and return the authenticated user or raise ``AuthenticationError``."""
