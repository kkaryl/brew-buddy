"""Clock port supplying the current UTC time."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ClockPort(Protocol):
    """Port supplying the current UTC timestamp."""

    def now_utc(self) -> datetime:
        """Return a timezone-aware UTC datetime."""
