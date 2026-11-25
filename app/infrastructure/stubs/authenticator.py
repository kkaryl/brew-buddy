"""Static-token authenticator standing in for an identity provider."""

from __future__ import annotations

import threading
from collections.abc import Mapping

from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.errors import AuthenticationError

DEFAULT_FAKE_TOKENS: dict[str, AuthenticatedPrincipal] = {
    "brew-dev-token-alice": AuthenticatedPrincipal(
        user_id="usr_alice",
        display_name="Alice Chen",
    ),
    "brew-dev-token-bob": AuthenticatedPrincipal(
        user_id="usr_bob",
        display_name="Bob Rivera",
    ),
}


class FakeAuthenticator:
    """In-memory bearer token authenticator mapping opaque tokens to user principals."""

    def __init__(
        self,
        tokens: Mapping[str, AuthenticatedPrincipal] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._tokens: dict[str, AuthenticatedPrincipal] = dict(
            tokens if tokens is not None else DEFAULT_FAKE_TOKENS
        )

    def register_token(self, token: str, principal: AuthenticatedPrincipal) -> None:
        """Register or replace an in-memory bearer token for testing."""
        cleaned = token.strip()
        if not cleaned:
            msg = "Token cannot be empty."
            raise ValueError(msg)
        with self._lock:
            self._tokens[cleaned] = principal

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Verify ``token`` and return the bound ``AuthenticatedPrincipal``."""
        cleaned = token.strip()
        if not cleaned:
            raise AuthenticationError("Bearer token cannot be empty.")
        with self._lock:
            principal = self._tokens.get(cleaned)
        if principal is None:
            raise AuthenticationError("Invalid or unrecognized bearer token.")
        return principal
