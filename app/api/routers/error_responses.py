"""Error responses documented on every /api/v1 route."""

from __future__ import annotations

from typing import Any

from app.api.schemas import (
    ApiErrorResponse,
)

STANDARD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ApiErrorResponse,
        "description": "Missing, malformed, or invalid Bearer authentication credentials.",
    },
    403: {
        "model": ApiErrorResponse,
        "description": "Authenticated user does not own the target resource.",
    },
    404: {
        "model": ApiErrorResponse,
        "description": "Requested resource does not exist.",
    },
    409: {
        "model": ApiErrorResponse,
        "description": "Optimistic concurrency version conflict or invalid lifecycle transition.",
    },
    422: {
        "model": ApiErrorResponse,
        "description": "Request schema, domain invariant, or model output validation failure.",
    },
    502: {
        "model": ApiErrorResponse,
        "description": "Coaching model execution or invocation budget failure.",
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Persistence backend unavailable.",
    },
    504: {
        "model": ApiErrorResponse,
        "description": "Coaching model request deadline exceeded.",
    },
}
