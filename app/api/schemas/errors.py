"""The canonical error envelope returned by every Brew API endpoint."""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ResponseModel


class ErrorDetailItem(ResponseModel):
    """Field-level validation or constraint failure detail."""

    field: str = Field(description="Dot-delimited request location of the offending input.")
    message: str = Field(description="Human-readable validation error explanation.")
    error_type: str = Field(description="Machine-readable validation category.")


class ErrorObject(ResponseModel):
    """Structured error payload included in every error response."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Safe human-readable error message.")
    trace_id: str = Field(description="Request correlation or OpenTelemetry trace identifier.")
    details: list[ErrorDetailItem] = Field(
        default_factory=list,
        description="Optional field-level validation failures.",
    )


class ApiErrorResponse(ResponseModel):
    """Canonical error envelope returned across all Brew API endpoints."""

    error: ErrorObject
