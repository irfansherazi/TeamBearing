"""
vQA — JWT Revocation Set
=========================
Module: backend/auth/revocation.py

In-memory LRU + TTL-scoped set of revoked JWT JTIs (JWT IDs).

Design (ADR-7):
  - In-memory only: container restart wipes it, but container restart also
    kills every session.  The JWT `exp` claim provides the ultimate bound.
  - LRU eviction at ``max_size`` keeps memory bounded.
  - TTL-scoped eviction: a JTI is evicted once its ``expires_at`` has passed
    (because the JWT itself is expired and no longer valid anyway).

This module is intentionally simple — no external dependencies.
``fcntl`` / file locks, Redis, etc. are all unnecessary for the single
uvicorn-worker deployment model (--workers 1 enforced by supervisord.conf).

Usage
-----
    from backend.auth.revocation import get_revocation_set

    rset = get_revocation_set()
    rset.add(jti, expires_at=jwt_payload["exp"])
    if rset.is_revoked(jti):
        return 401
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)

#: Default maximum number of JTIs to keep in memory.
_DEFAULT_MAX_SIZE = 10_000


class RevokedJtiSet:
    """
    Bounded in-memory set of revoked JWT IDs (JTIs).

    - LRU eviction when ``max_size`` is reached (oldest entry removed).
    - TTL-scoped: ``is_revoked()`` treats expired entries as not revoked and
      evicts them on access, so the set self-cleans over time.

    Thread-safe via a threading.Lock (compatible with asyncio single-worker model).
    """

    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._max_size = max_size
        self._lock = threading.Lock()
        #: OrderedDict[jti, expires_at_float] — insertion order = LRU order.
        self._store: OrderedDict[str, float] = OrderedDict()

    def add(self, jti: str, expires_at: float) -> None:
        """
        Add a JTI to the revocation set.

        Parameters
        ----------
        jti
            The JWT ID (``jti`` claim) to revoke.
        expires_at
            Unix timestamp after which the JWT is expired anyway (from ``exp``).
            Used for TTL-scoped eviction.
        """
        with self._lock:
            # If already present, move to end (most-recently-used)
            if jti in self._store:
                self._store.move_to_end(jti)
                self._store[jti] = expires_at
                return

            # LRU eviction: remove the oldest entry if at capacity
            if len(self._store) >= self._max_size:
                oldest_jti, _ = self._store.popitem(last=False)
                logger.debug("RevokedJtiSet: LRU evicted jti=%s at capacity", oldest_jti)

            self._store[jti] = expires_at

    def is_revoked(self, jti: str) -> bool:
        """
        Return True if the JTI is in the revocation set and has not expired.

        Expired entries are evicted on access (TTL-scoped cleanup).
        """
        with self._lock:
            if jti not in self._store:
                return False
            expires_at = self._store[jti]
            if time.time() > expires_at:
                # JTI has expired — evict it (no longer relevant to check)
                del self._store[jti]
                return False
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_revocation_set_instance: Optional[RevokedJtiSet] = None
_revocation_set_lock = threading.Lock()


def get_revocation_set() -> RevokedJtiSet:
    """Return the module-level RevokedJtiSet singleton."""
    global _revocation_set_instance
    if _revocation_set_instance is None:
        with _revocation_set_lock:
            if _revocation_set_instance is None:
                _revocation_set_instance = RevokedJtiSet()
    return _revocation_set_instance
