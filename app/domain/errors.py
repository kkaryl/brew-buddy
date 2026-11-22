"""Structured domain error hierarchy for Brew."""

from __future__ import annotations


class BrewDomainError(Exception):
    """Base error for domain rule violations and operational domain failures."""

    def __init__(self, *, code: str, message: str, recoverable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable


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

    def __init__(self, message: str = "Valid authentication credentials are required.") -> None:
        super().__init__(code="AUTHENTICATION_REQUIRED", message=message, recoverable=True)


class AuthorizationError(BrewDomainError):
    """Raised when an authenticated user accesses a resource they do not own."""

    def __init__(
        self,
        message: str = "You are not authorized to access or modify this resource.",
    ) -> None:
        super().__init__(code="FORBIDDEN", message=message, recoverable=True)


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
