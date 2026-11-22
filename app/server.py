"""Production/container HTTP server entrypoint honoring the PORT environment variable."""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    """Start uvicorn bound to configured host and PORT (Cloud Run compatible)."""
    settings = get_settings()
    uvicorn.run(
        "app.fast_api_app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
