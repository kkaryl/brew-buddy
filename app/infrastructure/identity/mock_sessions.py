"""Local-only mock personas and the short-lived mock session registry."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthenticationError, DomainValidationError
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.stubs.authenticator import DEFAULT_FAKE_TOKENS

MOCK_TOKEN_PREFIX = "mses_"


@dataclass(frozen=True)
class MockPersonaDefinition:
    """Isolated local test persona never permitted in deployed environments."""

    persona_id: str
    user_id: str
    display_name: str
    role_summary: str


LOCAL_MOCK_PERSONAS: tuple[MockPersonaDefinition, ...] = (
    MockPersonaDefinition(
        persona_id="alice",
        user_id="usr_mock_alice",
        display_name="Alice Chen",
        role_summary="Product Lead · Isolated Local Workspace",
    ),
    MockPersonaDefinition(
        persona_id="bob",
        user_id="usr_mock_bob",
        display_name="Bob Rivera",
        role_summary="Staff Engineer · Secondary Isolated Workspace",
    ),
)


_PERSONAS_BY_ID: Mapping[str, MockPersonaDefinition] = {
    persona.persona_id: persona for persona in LOCAL_MOCK_PERSONAS
}


@dataclass(frozen=True)
class IssuedMockSession:
    """Short-lived isolated local mock session token with explicit UTC expiry."""

    access_token: str
    expires_at: datetime
    principal: AuthenticatedPrincipal


class LocalMockSessionRegistry:
    """Thread-safe ephemeral session store strictly isolated to local/test environments."""

    def __init__(
        self,
        *,
        clock: ClockPort | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._clock = clock or SystemUtcClock()
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, IssuedMockSession] = {}

    def issue_session(
        self,
        persona_id: str = "alice",
        *,
        ttl_seconds_override: int | None = None,
    ) -> IssuedMockSession:
        """Create an isolated mock session token with an explicit expiration timestamp."""
        persona = _PERSONAS_BY_ID.get(persona_id.strip().lower())
        if persona is None:
            raise DomainValidationError(
                f"Unknown local mock persona '{persona_id}'. Expected one of: "
                f"{', '.join(sorted(_PERSONAS_BY_ID))}."
            )
        ttl = ttl_seconds_override if ttl_seconds_override is not None else self._ttl_seconds
        now = self._clock.now_utc()
        expires_at = now + timedelta(seconds=ttl)
        token = f"{MOCK_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"
        principal = AuthenticatedPrincipal(
            user_id=persona.user_id,
            display_name=persona.display_name,
        )
        session = IssuedMockSession(
            access_token=token,
            expires_at=expires_at,
            principal=principal,
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def revoke_session(self, token: str) -> None:
        """Invalidate an issued local mock session token."""
        with self._lock:
            self._sessions.pop(token.strip(), None)

    def authenticate_mock_token(self, token: str) -> AuthenticatedPrincipal:
        """Resolve an ephemeral or local developer mock token, enforcing expiry."""
        cleaned = token.strip()
        with self._lock:
            issued = self._sessions.get(cleaned)
        if issued is not None:
            if self._clock.now_utc() >= issued.expires_at:
                self.revoke_session(cleaned)
                raise AuthenticationError(
                    "Authentication token has expired. Please sign in again.",
                    code="TOKEN_EXPIRED",
                )
            return issued.principal

        static_principal = DEFAULT_FAKE_TOKENS.get(cleaned)
        if static_principal is not None:
            return static_principal

        raise AuthenticationError(
            "Invalid or unrecognized bearer token.",
            code="AUTHENTICATION_REQUIRED",
        )
