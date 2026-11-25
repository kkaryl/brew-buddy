"""Base class for immutable, strictly validated domain models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ImmutableDomainModel(BaseModel):
    """Base configuration for immutable, strictly validated domain models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )
