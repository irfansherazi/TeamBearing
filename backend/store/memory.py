"""
vQA — In-Memory Run State Store
===================================
Module: backend/store/memory.py

Default state store implementation that wraps a Python dict.
Zero dependencies, zero config.  Identical behavior to the
original ``_run_states`` dict in ``routes.py``.

Limitations
-----------
  - State is lost on process restart
  - Not shared across multiple workers / containers
  - No TTL-based expiration

For production multi-container deployments, use ``RedisStateStore``.

See Also
--------
  - ``backend/store/base.py``  — RunStateStore ABC
  - ``backend/store/redis.py`` — Redis-backed implementation
"""

from __future__ import annotations

import logging
from typing import Any

from backend.store.base import RunStateStore

logger = logging.getLogger(__name__)


class InMemoryStateStore(RunStateStore):
    """
    In-memory run state store backed by a plain Python dict.

    Thread-safe for single-process use (GIL-protected dict ops).
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, run_id: str) -> dict[str, Any] | None:
        return self._store.get(run_id)

    async def set(self, run_id: str, data: dict[str, Any]) -> None:
        self._store[run_id] = data

    async def update(self, run_id: str, **kwargs: Any) -> None:
        if run_id not in self._store:
            raise KeyError(f"Run '{run_id}' not found in state store")
        self._store[run_id].update(kwargs)

    async def delete(self, run_id: str) -> None:
        self._store.pop(run_id, None)

    async def exists(self, run_id: str) -> bool:
        return run_id in self._store

    async def list_runs(self, status: str | None = None) -> list[str]:
        if status is None:
            return list(self._store.keys())
        return [rid for rid, data in self._store.items() if data.get("status") == status]

    # ── Compatibility helpers ─────────────────────────────────────────
    # These allow the store to be used as a drop-in for the old dict.

    def __contains__(self, run_id: str) -> bool:
        """Synchronous 'in' operator for backward compatibility."""
        return run_id in self._store

    def __getitem__(self, run_id: str) -> dict[str, Any]:
        """Synchronous subscript access for backward compatibility."""
        return self._store[run_id]

    def __setitem__(self, run_id: str, data: dict[str, Any]) -> None:
        """Synchronous assignment for backward compatibility."""
        self._store[run_id] = data

    def values(self):
        """Synchronous .values() for backward-compat with dict-style iteration."""
        return self._store.values()

    def keys(self):
        """Synchronous .keys() for backward-compat with dict-style iteration."""
        return self._store.keys()

    def items(self):
        """Synchronous .items() for backward-compat with dict-style iteration."""
        return self._store.items()

    def get_sync(self, run_id: str, default=None):
        """Synchronous .get() for backward-compat (async get() is on the ABC)."""
        return self._store.get(run_id, default)
