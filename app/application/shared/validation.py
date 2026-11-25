"""Translate Pydantic validation failures into structured domain validation errors."""

from __future__ import annotations

from pydantic import ValidationError

from app.domain.shared.errors import DomainValidationError


def translate_pydantic_error(exc: ValidationError) -> DomainValidationError:
    """Convert a Pydantic ``ValidationError`` into a structured ``DomainValidationError``."""
    first = exc.errors()[0] if exc.errors() else None
    if first is not None:
        loc = ".".join(str(part) for part in first.get("loc", ()))
        msg = str(first.get("msg", "Invalid domain value."))
        summary = f"{loc}: {msg}" if loc else msg
    else:
        summary = "Domain validation failed."
    return DomainValidationError(summary)
