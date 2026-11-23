"""Structured domain error hierarchy for Brew."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models import BriefWorkflowDiagnostics


class BrewDomainError(Exception):
    """Base error for domain rule violations and operational domain failures."""

    def __init__(self, *, code: str, message: str, recoverable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.workflow_diagnostics: BriefWorkflowDiagnostics | None = None


class InvalidConfigurationError(BrewDomainError):
    """Raised when domain-level runtime metadata fails invariant checks."""

    def __init__(self, message: str) -> None:
        super().__init__(code="INVALID_CONFIGURATION", message=message, recoverable=False)


class DomainValidationError(BrewDomainError):
    """Raised when a domain rule or cross-entity invariant fails validation."""

    def __init__(self, message: str, *, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(code=code, message=message, recoverable=True)


class AuthenticationError(BrewDomainError):
    """Raised when caller credentials are missing, malformed, or invalid."""

    def __init__(
        self,
        message: str = "Valid authentication credentials are required.",
        *,
        code: str = "AUTHENTICATION_REQUIRED",
    ) -> None:
        super().__init__(code=code, message=message, recoverable=True)


class AuthorizationError(BrewDomainError):
    """Raised when an authenticated user accesses a resource they do not own."""

    def __init__(
        self,
        message: str = "You are not authorized to access or modify this resource.",
        *,
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(code=code, message=message, recoverable=True)


class EntityNotFoundError(BrewDomainError):
    """Raised when a requested domain entity does not exist."""

    def __init__(self, *, entity_name: str, entity_id: str) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(
            code="NOT_FOUND",
            message=f"{entity_name} '{entity_id}' was not found.",
            recoverable=True,
        )


class VersionConflictError(BrewDomainError):
    """Raised when an optimistic concurrency version check fails."""

    def __init__(
        self,
        *,
        entity_name: str,
        entity_id: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            code="VERSION_CONFLICT",
            message=(
                f"Version conflict on {entity_name} '{entity_id}': "
                f"expected version {expected_version}, current version is {actual_version}."
            ),
            recoverable=True,
        )


class ConflictError(BrewDomainError):
    """Raised when an operation conflicts with the current lifecycle state of an entity."""

    def __init__(self, message: str, *, code: str = "STATE_CONFLICT") -> None:
        super().__init__(code=code, message=message, recoverable=True)


class PersistenceOperationError(BrewDomainError):
    """Raised when an external persistence operation times out or fails."""

    def __init__(
        self,
        message: str = "Persistence backend failed to complete the operation.",
    ) -> None:
        super().__init__(code="PERSISTENCE_UNAVAILABLE", message=message, recoverable=False)


class ModelTimeoutError(BrewDomainError):
    """Raised when Gemini / ADK model inference exceeds the configured request deadline."""

    def __init__(
        self,
        message: str = "The coaching model timed out before completing the preparation brief.",
    ) -> None:
        super().__init__(code="MODEL_TIMEOUT", message=message, recoverable=False)


class ModelExecutionError(BrewDomainError):
    """Raised when Gemini / ADK model execution fails or exceeds invocation safeguards."""

    def __init__(
        self,
        message: str = "The coaching model encountered an execution failure.",
        *,
        code: str = "MODEL_EXECUTION_ERROR",
    ) -> None:
        super().__init__(code=code, message=message, recoverable=False)


class ModelOutputValidationError(BrewDomainError):
    """Raised when model output fails strict schema or deterministic brief quality checks."""

    def __init__(
        self,
        message: str = "Generated preparation brief failed schema or quality validation.",
        *,
        violations: tuple[str, ...] = (),
    ) -> None:
        self.violations = violations
        super().__init__(
            code="MODEL_OUTPUT_VALIDATION_ERROR",
            message=message,
            recoverable=True,
        )
