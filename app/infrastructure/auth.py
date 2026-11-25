"""Verified Google / Firebase ID token authentication and local-only isolated mock sessions."""

from __future__ import annotations

import logging
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import requests
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from app.config import AppSettings
from app.domain.errors import AuthenticationError, AuthorizationError, DomainValidationError
from app.domain.health import ClockPort
from app.domain.models import AuthenticatedPrincipal
from app.infrastructure.clock import SystemUtcClock
from app.infrastructure.fakes import DEFAULT_FAKE_TOKENS

logger = logging.getLogger(__name__)

_SAFE_SUBJECT_CHARS_RE = re.compile(r"[^A-Za-z0-9._:-]+")
_JWT_SEGMENT_COUNT = 3
_MOCK_TOKEN_PREFIX = "mses_"
_CLOCK_SKEW_SECONDS = 10
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_GOOGLE_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"
_GOOGLE_IAP_ISSUER = "https://cloud.google.com/iap"


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


class _BoundedGoogleAuthRequest:
    """Adapter around ``google.auth.transport.requests.Request`` with plain HTTPS session."""

    def __init__(self, timeout_seconds: float, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._inner: Any = google_auth_requests.Request(session=self._session)
        self._timeout_seconds = timeout_seconds

    @property
    def session(self) -> requests.Session:
        return self._session

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        resolved_timeout = self._timeout_seconds if timeout is None else timeout
        return self._inner(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=resolved_timeout,
            **kwargs,
        )


_VERIFY_FIREBASE_FN = cast(
    Callable[..., Mapping[str, Any]],
    google_id_token.verify_firebase_token,
)
_VERIFY_OAUTH2_FN = cast(
    Callable[..., Mapping[str, Any]],
    google_id_token.verify_oauth2_token,
)
_VERIFY_IAP_FN = cast(
    Callable[..., Mapping[str, Any]],
    google_id_token.verify_token,
)


def _normalize_verified_user_id(prefix: str, raw_subject: str) -> str:
    cleaned = _SAFE_SUBJECT_CHARS_RE.sub("_", raw_subject.strip()).strip("._:-")
    if not cleaned:
        raise AuthenticationError("Verified token is missing a valid subject identifier.")
    candidate = f"{prefix}:{cleaned}"
    return candidate[:128]


def _extract_display_name(claims: Mapping[str, Any]) -> str | None:
    raw_name = claims.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()[:120]
    raw_email = claims.get("email")
    if isinstance(raw_email, str) and "@" in raw_email:
        local_part = raw_email.split("@", 1)[0].strip()
        if local_part:
            return local_part[:120]
    return None


def _looks_like_expired_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return "expired" in lowered or "token used too late" in lowered


TokenClaimsVerifier = Callable[[str], Mapping[str, Any]]


class FirebaseGoogleTokenAuthenticator:
    """Verifies Firebase Auth ID tokens, Google OIDC ID tokens, and Google OAuth2 popup tokens."""

    def __init__(
        self,
        *,
        firebase_project_id: str | None = None,
        google_oauth_client_id: str | None = None,
        service_oidc_audience: str | None = None,
        iap_jwt_audience: str | None = None,
        timeout_seconds: float = 5.0,
        firebase_verifier_override: TokenClaimsVerifier | None = None,
        google_verifier_override: TokenClaimsVerifier | None = None,
        google_access_token_verifier_override: TokenClaimsVerifier | None = None,
        iap_verifier_override: TokenClaimsVerifier | None = None,
    ) -> None:
        self._firebase_project_id = (firebase_project_id or "").strip() or None
        self._google_oauth_client_id = (google_oauth_client_id or "").strip() or None
        self._service_oidc_audience = (service_oidc_audience or "").strip().rstrip("/") or None
        self._iap_jwt_audience = (iap_jwt_audience or "").strip() or None
        self._request_adapter = _BoundedGoogleAuthRequest(timeout_seconds=timeout_seconds)
        self._firebase_verifier_override = firebase_verifier_override
        self._google_verifier_override = google_verifier_override
        self._google_access_token_verifier_override = google_access_token_verifier_override
        self._iap_verifier_override = iap_verifier_override

    @property
    def is_configured(self) -> bool:
        """Return True when at least one verified identity audience is configured."""
        return bool(
            self._firebase_project_id
            or self._google_oauth_client_id
            or self._service_oidc_audience
            or self._iap_jwt_audience
            or self._firebase_verifier_override
            or self._google_verifier_override
            or self._google_access_token_verifier_override
            or self._iap_verifier_override
        )

    @property
    def is_bearer_configured(self) -> bool:
        """Return True when at least one Bearer token audience is configured."""
        return bool(
            self._firebase_project_id
            or self._google_oauth_client_id
            or self._service_oidc_audience
            or self._firebase_verifier_override
            or self._google_verifier_override
            or self._google_access_token_verifier_override
        )

    @property
    def is_iap_configured(self) -> bool:
        """Return True when Cloud Run IAP JWT verification is configured."""
        return bool(self._iap_jwt_audience or self._iap_verifier_override)

    def authenticate_iap_assertion(self, assertion: str) -> AuthenticatedPrincipal:
        """Cryptographically verify a Google Cloud IAP ``X-Goog-IAP-JWT-Assertion`` header."""
        cleaned = assertion.strip()
        if not cleaned or cleaned.count(".") != (_JWT_SEGMENT_COUNT - 1):
            raise AuthenticationError(
                "A valid Google Cloud IAP JWT assertion is required.",
                code="AUTHENTICATION_REQUIRED",
            )
        if not self.is_iap_configured:
            raise AuthenticationError(
                "IAP authentication header was supplied, but BREW_IAP_JWT_AUDIENCE "
                "is not configured on the server.",
                code="AUTH_PROVIDER_NOT_CONFIGURED",
            )
        try:
            claims = (
                self._iap_verifier_override(cleaned)
                if self._iap_verifier_override is not None
                else _VERIFY_IAP_FN(
                    cleaned,
                    self._request_adapter,
                    audience=self._iap_jwt_audience,
                    certs_url=_GOOGLE_IAP_CERTS_URL,
                    clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
                )
            )
            issuer = str(claims.get("iss") or "").strip()
            if issuer and issuer != _GOOGLE_IAP_ISSUER:
                raise AuthenticationError(
                    "Unexpected IAP JWT issuer.",
                    code="AUTHENTICATION_REQUIRED",
                )
            subject = str(claims.get("sub") or "").strip()
            if subject.startswith("accounts.google.com:"):
                subject = subject.split(":", 1)[1].strip()
            user_id = _normalize_verified_user_id("iap", subject)
            return AuthenticatedPrincipal(
                user_id=user_id,
                display_name=_extract_display_name(claims),
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            if _looks_like_expired_error(exc):
                raise AuthenticationError(
                    "IAP authentication assertion has expired. Please refresh and sign in again.",
                    code="TOKEN_EXPIRED",
                ) from exc
            logger.warning("IAP JWT verification rejected assertion (%s)", type(exc).__name__)
            raise AuthenticationError(
                "Invalid or untrusted IAP authentication assertion.",
                code="AUTHENTICATION_REQUIRED",
            ) from exc

    def _verify_google_oauth_access_token(self, access_token: str) -> AuthenticatedPrincipal:
        """Verify an OAuth 2.0 access token issued to ``GOOGLE_OAUTH_CLIENT_ID`` via Google OIDC."""
        if self._google_access_token_verifier_override is not None:
            claims = self._google_access_token_verifier_override(access_token)
        else:
            if not self._google_oauth_client_id:
                raise AuthenticationError(
                    "Google OAuth client ID is not configured on the server.",
                    code="AUTH_PROVIDER_NOT_CONFIGURED",
                )
            session = self._request_adapter.session
            timeout = self._request_adapter.timeout_seconds
            try:
                tokeninfo_resp = session.post(
                    _GOOGLE_TOKENINFO_URL,
                    data={"access_token": access_token},
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                logger.warning("Google tokeninfo request failed: %s", type(exc).__name__)
                raise AuthenticationError(
                    "Unable to reach Google authentication service to verify token.",
                    code="AUTHENTICATION_REQUIRED",
                ) from exc

            if tokeninfo_resp.status_code != 200:
                body_text = tokeninfo_resp.text.lower()
                if "expired" in body_text or "invalid_token" in body_text:
                    raise AuthenticationError(
                        "Authentication token has expired or is invalid. Please sign in again.",
                        code="TOKEN_EXPIRED"
                        if "expired" in body_text
                        else "AUTHENTICATION_REQUIRED",
                    )
                raise AuthenticationError(
                    "Invalid or untrusted Google OAuth access token.",
                    code="AUTHENTICATION_REQUIRED",
                )

            raw_info = tokeninfo_resp.json()
            if not isinstance(raw_info, Mapping):
                raise AuthenticationError("Malformed response from Google tokeninfo.")

            aud = str(raw_info.get("aud") or "").strip()
            azp = str(raw_info.get("azp") or "").strip()
            if self._google_oauth_client_id not in {aud, azp}:
                raise AuthenticationError(
                    "Google OAuth token audience does not match configured GOOGLE_OAUTH_CLIENT_ID.",
                    code="AUTHENTICATION_REQUIRED",
                )

            expires_in_raw = raw_info.get("expires_in")
            try:
                if int(str(expires_in_raw or "0")) <= 0:
                    raise AuthenticationError(
                        "Authentication token has expired. Please sign in again.",
                        code="TOKEN_EXPIRED",
                    )
            except ValueError:
                pass

            merged_claims: dict[str, Any] = dict(raw_info)
            try:
                userinfo_resp = session.get(
                    _GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=timeout,
                )
                if userinfo_resp.status_code == 200:
                    profile = userinfo_resp.json()
                    if isinstance(profile, Mapping):
                        merged_claims.update(profile)
            except requests.RequestException:
                logger.debug("Optional Google userinfo enrichment timed out or failed.")

            claims = merged_claims

        subject = str(claims.get("sub") or claims.get("user_id") or "").strip()
        user_id = _normalize_verified_user_id("google", subject)
        return AuthenticatedPrincipal(
            user_id=user_id,
            display_name=_extract_display_name(claims),
        )

    def authenticate_bearer_token(self, token: str) -> AuthenticatedPrincipal:
        """Cryptographically verify a Firebase/Google ID token or Google OAuth2 popup token."""
        cleaned = token.strip()
        if not cleaned:
            raise AuthenticationError(
                "A valid Firebase or Google authentication token is required.",
                code="AUTHENTICATION_REQUIRED",
            )

        if not self.is_bearer_configured:
            raise AuthenticationError(
                "Verified authentication is active, but FIREBASE_PROJECT_ID, "
                "GOOGLE_OAUTH_CLIENT_ID, or APP_URL is not configured on the server.",
                code="AUTH_PROVIDER_NOT_CONFIGURED",
            )

        # Non-JWT bearer token (e.g. ya29.* from Google OAuth2 popup flow)
        if cleaned.count(".") != (_JWT_SEGMENT_COUNT - 1):
            if (
                self._google_oauth_client_id is not None
                or self._google_access_token_verifier_override is not None
            ) and not cleaned.startswith(_MOCK_TOKEN_PREFIX):
                return self._verify_google_oauth_access_token(cleaned)
            raise AuthenticationError(
                "A valid Firebase or Google ID token is required.",
                code="AUTHENTICATION_REQUIRED",
            )

        expired_seen = False

        if self._firebase_project_id or self._firebase_verifier_override is not None:
            try:
                claims = (
                    self._firebase_verifier_override(cleaned)
                    if self._firebase_verifier_override is not None
                    else _VERIFY_FIREBASE_FN(
                        cleaned,
                        self._request_adapter,
                        audience=self._firebase_project_id,
                        clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
                    )
                )
                subject = str(claims.get("user_id") or claims.get("sub") or "").strip()
                user_id = _normalize_verified_user_id("firebase", subject)
                return AuthenticatedPrincipal(
                    user_id=user_id,
                    display_name=_extract_display_name(claims),
                )
            except AuthenticationError:
                raise
            except Exception as exc:
                if _looks_like_expired_error(exc):
                    expired_seen = True
                logger.debug("Firebase token verification did not match: %s", type(exc).__name__)

        google_audiences: list[str | None] = []
        if self._google_oauth_client_id:
            google_audiences.append(self._google_oauth_client_id)
        if self._service_oidc_audience and self._service_oidc_audience not in google_audiences:
            google_audiences.append(self._service_oidc_audience)
        if not google_audiences and self._google_verifier_override is not None:
            google_audiences.append(None)

        for target_audience in google_audiences:
            try:
                claims = (
                    self._google_verifier_override(cleaned)
                    if self._google_verifier_override is not None
                    else _VERIFY_OAUTH2_FN(
                        cleaned,
                        self._request_adapter,
                        audience=target_audience,
                        clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
                    )
                )
                issuer = str(claims.get("iss") or "")
                if issuer and issuer not in {
                    "accounts.google.com",
                    "https://accounts.google.com",
                }:
                    raise AuthenticationError("Unexpected Google OIDC token issuer.")
                subject = str(claims.get("sub") or "").strip()
                user_id = _normalize_verified_user_id("google", subject)
                return AuthenticatedPrincipal(
                    user_id=user_id,
                    display_name=_extract_display_name(claims),
                )
            except AuthenticationError:
                raise
            except Exception as exc:
                if _looks_like_expired_error(exc):
                    expired_seen = True
                logger.warning(
                    "Google OIDC token verification rejected token (%s)",
                    type(exc).__name__,
                )

        if expired_seen:
            raise AuthenticationError(
                "Authentication token has expired. Please sign in again.",
                code="TOKEN_EXPIRED",
            )

        raise AuthenticationError(
            "Invalid or untrusted authentication token.",
            code="AUTHENTICATION_REQUIRED",
        )


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
        token = f"{_MOCK_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"
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
        if cleaned.startswith(_MOCK_TOKEN_PREFIX) or cleaned in DEFAULT_FAKE_TOKENS:
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
