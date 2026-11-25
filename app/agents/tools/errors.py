"""Principal resolution and exception to guided tool error translation."""

from __future__ import annotations

import logging

from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from app.agents.tools.contracts import ToolErrorDetail
from app.application.shared.validation import translate_pydantic_error
from app.domain.identity.models import AuthenticatedPrincipal
from app.domain.shared.errors import (
    AuthenticationError,
    AuthorizationError,
    BrewDomainError,
    DomainValidationError,
    EntityNotFoundError,
    PersistenceOperationError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authenticated Principal & Structured Error Translation
# ---------------------------------------------------------------------------


def resolve_authenticated_principal(tool_context: ToolContext | None) -> AuthenticatedPrincipal:
    """Extract and validate caller identity strictly from ADK ``ToolContext``."""
    if tool_context is None:
        raise AuthenticationError("Authenticated session context is required to invoke this tool.")

    raw_user_id = getattr(tool_context, "user_id", None)
    if not isinstance(raw_user_id, str) or not raw_user_id.strip():
        raise AuthenticationError("Authenticated user identity is missing from session context.")

    session = getattr(tool_context, "session", None)
    session_user_id = getattr(session, "user_id", None) if session is not None else None
    if (
        isinstance(session_user_id, str)
        and session_user_id.strip()
        and session_user_id.strip() != raw_user_id.strip()
    ):
        raise AuthorizationError("Session user identity mismatch detected.")

    try:
        return AuthenticatedPrincipal(user_id=raw_user_id)
    except ValidationError as exc:
        raise AuthenticationError("Authenticated user identifier is malformed.") from exc


def translate_tool_exception(tool_name: str, exc: Exception) -> ToolErrorDetail:
    """Map domain, validation, and operational exceptions to recoverable tool guidance."""
    if isinstance(exc, ValidationError):
        domain_err = translate_pydantic_error(exc)
        return ToolErrorDetail(
            code="VALIDATION_ERROR",
            message=domain_err.message[:500],
            retryable=True,
            recovery_instruction=(
                f"Correct the invalid parameter for `{tool_name}` using valid identifier "
                "formats and value bounds, or ask the user to clarify."
            ),
        )

    if isinstance(exc, DomainValidationError):
        return ToolErrorDetail(
            code="VALIDATION_ERROR",
            message=exc.message[:500],
            retryable=True,
            recovery_instruction=(
                f"Verify argument consistency for `{tool_name}` (for example ensuring "
                "`contact_id` matches `meeting_id`) before retrying."
            ),
        )

    if isinstance(exc, AuthenticationError):
        return ToolErrorDetail(
            code="AUTHENTICATION_REQUIRED",
            message="An authenticated user session is required to access saved records.",
            retryable=False,
            recovery_instruction=(
                f"Do not retry `{tool_name}`. Inform the user that saved context cannot be "
                "loaded without an authenticated session and continue using only details "
                "shared in this conversation."
            ),
        )

    if isinstance(exc, AuthorizationError):
        return ToolErrorDetail(
            code="FORBIDDEN",
            message="The requested record does not belong to the authenticated user.",
            retryable=False,
            recovery_instruction=(
                f"Do not retry `{tool_name}` with this identifier and never infer anything "
                "about the record. Ask the user to confirm their own saved contact or meeting."
            ),
        )

    if isinstance(exc, EntityNotFoundError):
        return ToolErrorDetail(
            code="NOT_FOUND",
            message=exc.message[:500],
            retryable=False,
            recovery_instruction=(
                f"Do not fabricate details for the missing {exc.entity_name}. Let the user "
                "know no saved record matched that ID and ask for the relevant context or "
                "correct identifier."
            ),
        )

    if isinstance(exc, TimeoutError):
        return ToolErrorDetail(
            code="TIMEOUT",
            message=f"Timed out while executing `{tool_name}` against persistence storage.",
            retryable=True,
            recovery_instruction=(
                f"Never claim `{tool_name}` succeeded. Tell the user saved records timed out "
                "and offer to prepare using the details provided directly in chat."
            ),
        )

    if isinstance(exc, (PersistenceOperationError, BrewDomainError)):
        return ToolErrorDetail(
            code="SERVICE_UNAVAILABLE",
            message="Saved coaching records are temporarily unavailable.",
            retryable=True,
            recovery_instruction=(
                f"Never claim `{tool_name}` succeeded. Inform the user that saved context "
                "could not be reached right now and proceed only with user-supplied facts."
            ),
        )

    logger.error(
        "Unexpected error inside coaching tool",
        extra={"event_type": "agent.tool.unexpected_error", "tool_name": tool_name},
    )
    return ToolErrorDetail(
        code="SERVICE_UNAVAILABLE",
        message="An unexpected operational error prevented tool completion.",
        retryable=True,
        recovery_instruction=(
            f"Never claim `{tool_name}` succeeded. Inform the user that the lookup failed "
            "and continue coaching using only explicitly provided conversation details."
        ),
    )
