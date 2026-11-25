"""Identifier generators: collision-resistant UUID ids and deterministic sequential ids."""

from __future__ import annotations

import threading
import uuid


class UuidIdGenerator:
    """Collision-resistant prefixed identifier generator."""

    def new_id(self, prefix: str) -> str:
        """Generate a URL-safe prefixed identifier."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SequentialIdGenerator:
    """Deterministic sequential ID generator useful for reproducible tests."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    def new_id(self, prefix: str) -> str:
        """Return the next sequential ID for ``prefix``."""
        with self._lock:
            next_num = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = next_num
            return f"{prefix}_{next_num:04d}"
