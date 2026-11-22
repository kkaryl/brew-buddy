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
