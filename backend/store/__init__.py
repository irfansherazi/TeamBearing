"""
vQA — State Store Package
============================
Module: backend/store/__init__.py

Exports ``get_state_store()`` factory for resolving the run state
store backend based on configuration.

Usage
-----
    from backend.store import get_state_store

    store = get_state_store()  # Returns InMemoryStateStore or RedisStateStore
    await store.set("run-123", {"status": "running"})
    data = await store.get("run-123")
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.store.base import RunStateStore

logger = logging.getLogger(__name__)

# Module-level singleton
_store_instance: RunStateStore | None = None


def get_state_store() -> RunStateStore:
    """
    Resolve the run state store backend from configuration.

    Returns a singleton instance based on ``settings.state_store``:
      - ``"memory"`` (default) → ``InMemoryStateStore``
      - ``"redis"``            → ``RedisStateStore``

    Returns
    -------
    RunStateStore
        The singleton state store instance.
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    backend = settings.state_store.lower()

    if backend == "redis":
        from backend.store.redis import RedisStateStore

        _store_instance = RedisStateStore()
        logger.info("store: using RedisStateStore (%s)", settings.redis_url)
    else:
        from backend.store.memory import InMemoryStateStore

        _store_instance = InMemoryStateStore()
        logger.info("store: using InMemoryStateStore (default)")

    return _store_instance


__all__ = [
    "RunStateStore",
    "get_state_store",
]
