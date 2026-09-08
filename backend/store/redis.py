"""
vQA — Redis Run State Store
================================
Module: backend/store/redis.py

Redis-backed implementation of ``RunStateStore`` for production
multi-container deployments.

Features
--------
  - Async operations via ``redis.asyncio``
  - JSON serialization for state dicts
  - TTL-based expiration for completed runs (configurable)
  - Connection pool with health check
  - Key schema: ``vqa:run:{run_id}``

Dependencies
------------
  - ``redis[hiredis]>=5.0.0`` — async Redis client

Configuration
-------------
  - ``REDIS_URL``           — Connection string (default: redis://localhost:6379/0)
  - ``REDIS_RUN_TTL_HOURS`` — Expiration for completed runs (default: 24)

See Also
--------
  - ``backend/store/base.py``   — RunStateStore ABC
  - ``backend/store/memory.py`` — in-memory implementation
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.config import settings
from backend.store.base import RunStateStore

logger = logging.getLogger(__name__)

# Key prefix for all vQA run state entries
_KEY_PREFIX = "vqa:run:"


class RedisStateStore(RunStateStore):
    """
    Redis-backed run state store.

    Uses ``redis.asyncio`` for non-blocking I/O and JSON
    serialization for state dicts.
    """

    def __init__(self, redis_url: str | None = None, ttl_hours: int | None = None):
        """
        Initialize the Redis state store.

        Parameters
        ----------
        redis_url : str | None
            Redis connection URL.  Defaults to ``settings.redis_url``.
        ttl_hours : int | None
            TTL in hours for completed run entries.
            Defaults to ``settings.redis_run_ttl_hours``.
        """
        self._url = redis_url or settings.redis_url
        self._ttl_seconds = (ttl_hours or settings.redis_run_ttl_hours) * 3600
        self._pool = None

    async def _get_client(self):
        """Lazy-initialize the async Redis connection pool."""
        if self._pool is None:
            try:
                import redis.asyncio as aioredis
            except ImportError as e:
                raise RuntimeError(
                    "RedisStateStore requires redis[hiredis] >= 5.0.0. Install: pip install 'redis[hiredis]>=5.0.0'"
                ) from e

            self._pool = aioredis.from_url(
                self._url,
                decode_responses=True,
                health_check_interval=30,
            )
            logger.info("RedisStateStore: connected to %s", self._url)
        return self._pool

    def _key(self, run_id: str) -> str:
        """Build the Redis key for a run."""
        return f"{_KEY_PREFIX}{run_id}"

    async def get(self, run_id: str) -> dict[str, Any] | None:
        client = await self._get_client()
        raw = await client.get(self._key(run_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("RedisStateStore: corrupt JSON for run '%s'", run_id)
            return None

    async def set(self, run_id: str, data: dict[str, Any]) -> None:
        client = await self._get_client()
        serialized = json.dumps(data, default=str)
        await client.set(self._key(run_id), serialized)

    async def update(self, run_id: str, **kwargs: Any) -> None:
        existing = await self.get(run_id)
        if existing is None:
            raise KeyError(f"Run '{run_id}' not found in Redis state store")
        existing.update(kwargs)
        await self.set(run_id, existing)

        # Apply TTL when a run completes or fails
        status = kwargs.get("status", existing.get("status"))
        if status in ("completed", "failed"):
            client = await self._get_client()
            await client.expire(self._key(run_id), self._ttl_seconds)
            logger.debug(
                "RedisStateStore: TTL set for run '%s' — %d seconds",
                run_id,
                self._ttl_seconds,
            )

    async def delete(self, run_id: str) -> None:
        client = await self._get_client()
        await client.delete(self._key(run_id))

    async def exists(self, run_id: str) -> bool:
        client = await self._get_client()
        return bool(await client.exists(self._key(run_id)))

    async def list_runs(self, status: str | None = None) -> list[str]:
        client = await self._get_client()
        keys = []
        async for key in client.scan_iter(match=f"{_KEY_PREFIX}*", count=100):
            keys.append(key)

        run_ids = [k.removeprefix(_KEY_PREFIX) for k in keys]

        if status is None:
            return run_ids

        # Filter by status (requires fetching each run's data)
        filtered = []
        for run_id in run_ids:
            data = await self.get(run_id)
            if data and data.get("status") == status:
                filtered.append(run_id)
        return filtered
