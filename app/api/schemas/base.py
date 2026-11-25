"""Shared strict request and frozen response base models for the API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """Base model forbidding unexpected or client-spoofed identity fields."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base model for serialized API responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)
