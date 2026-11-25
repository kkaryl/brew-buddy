"""Runtime authenticator switching between verified tokens and local mock sessions."""

from __future__ import annotations

from app.config import AppSettings
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.clock import ClockPort
from app.domain.shared.errors import AuthenticationError, AuthorizationError
from app.infrastructure.identity.mock_sessions import (
    MOCK_TOKEN_PREFIX,
    IssuedMockSession,
    LocalMockSessionRegistry,
)
from app.infrastructure.identity.verified_tokens import (
    FirebaseGoogleTokenAuthenticator,
    TokenClaimsVerifier,
)
from app.infrastructure.stubs.authenticator import DEFAULT_FAKE_TOKENS


class RuntimeAuthenticator:
    """Runtime authenticator enforcing verified tokens in deployment and safe isolation locally."""

    def __init__(
        self,
        *,
        verified_authenticator: FirebaseGoogleTokenAuthenticator,
        local_mock_enabled: bool,
        mock_registry: LocalMockSessionRegistry | None = None,
    ) -> None:
        self._verified = verified_authenticator
        self._local_mock_enabled = local_mock_enabled
        self._mock_registry = mock_registry or LocalMockSessionRegistry()

    @property
    def local_mock_enabled(self) -> bool:
        """Return True only when isolated local mock sessions are enabled."""
        return self._local_mock_enabled

    @property
    def is_verified_provider_configured(self) -> bool:
        """Return True when at least one verified auth provider is configured."""
        return self._verified.is_configured

    @property
    def is_iap_configured(self) -> bool:
        """Return True when Cloud Run IAP JWT verification is configured."""
        return self._verified.is_iap_configured

    @property
    def mock_registry(self) -> LocalMockSessionRegistry:
        """Access the local mock session registry (guarded by ``issue_local_mock_session``)."""
        return self._mock_registry

    def authenticate_iap_assertion(self, assertion: str) -> AuthenticatedPrincipal:
        """Verify a Google Cloud IAP ``X-Goog-IAP-JWT-Assertion`` header."""
        return self._verified.authenticate_iap_assertion(assertion)

    def issue_local_mock_session(
        self,
        persona_id: str = "alice",
        *,
        ttl_seconds_override: int | None = None,
    ) -> IssuedMockSession:
        """Issue an isolated mock session strictly when ``local_mock_enabled`` is True."""
        if not self._local_mock_enabled:
            raise AuthorizationError(
                "Local mock authentication is disabled in deployed environments.",
                code="MOCK_AUTH_DISABLED",
            )
        return self._mock_registry.issue_session(
            persona_id,
            ttl_seconds_override=ttl_seconds_override,
        )

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Authenticate a Bearer token according to the active security mode."""
        cleaned = token.strip()
        if not cleaned:
            raise AuthenticationError("Bearer token must not be empty.")

        if not self._local_mock_enabled:
            return self._verified.authenticate_bearer_token(cleaned)

        # Route local mock tokens and static developer test tokens directly to the mock registry.
        if cleaned.startswith(MOCK_TOKEN_PREFIX) or cleaned in DEFAULT_FAKE_TOKENS:
            return self._mock_registry.authenticate_mock_token(cleaned)

        # In local/test mode, verify real Google/Firebase JWTs and Google OAuth2 popup tokens
        # whenever Firebase/Google OAuth is configured on the server.
        if self._verified.is_configured:
            return self._verified.authenticate_bearer_token(cleaned)

        return self._mock_registry.authenticate_mock_token(cleaned)


def build_runtime_authenticator(
    settings: AppSettings,
    *,
    clock: ClockPort | None = None,
    mock_registry: LocalMockSessionRegistry | None = None,
    firebase_verifier_override: TokenClaimsVerifier | None = None,
    google_verifier_override: TokenClaimsVerifier | None = None,
    google_access_token_verifier_override: TokenClaimsVerifier | None = None,
    iap_verifier_override: TokenClaimsVerifier | None = None,
) -> RuntimeAuthenticator:
    """Construct ``RuntimeAuthenticator`` from validated ``AppSettings``."""
    verified = FirebaseGoogleTokenAuthenticator(
        firebase_project_id=settings.resolved_firebase_project_id,
        google_oauth_client_id=settings.google_oauth_client_id,
        service_oidc_audience=settings.app_url,
        iap_jwt_audience=settings.iap_jwt_audience,
        timeout_seconds=min(settings.http_timeout_seconds, 10.0),
        firebase_verifier_override=firebase_verifier_override,
        google_verifier_override=google_verifier_override,
        google_access_token_verifier_override=google_access_token_verifier_override,
        iap_verifier_override=iap_verifier_override,
    )
    registry = mock_registry or LocalMockSessionRegistry(
        clock=clock,
        ttl_seconds=settings.mock_session_ttl_seconds,
    )
    return RuntimeAuthenticator(
        verified_authenticator=verified,
        local_mock_enabled=settings.local_mock_auth_enabled,
        mock_registry=registry,
    )
