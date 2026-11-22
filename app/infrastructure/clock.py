"""System UTC clock adapter."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemUtcClock:
    """Production implementation of ClockPort returning current UTC time."""

    def now_utc(self) -> datetime:
        """Return timezone-aware current UTC datetime."""
        return datetime.now(UTC)
