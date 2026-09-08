"""
vQA — Jira Ticket and AC Step In-Memory Cache
================================================
Module: backend/jira/cache.py

Simple TTL-based in-memory caches for Jira data.
1. JiraCache: Caches raw Jira ticket context (prevents redundant API calls).
2. ACStepCache: Caches parsed AC steps/test plans (prevents redundant LLM calls).
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class JiraCache:
    """
    Process-local TTL in-memory cache for Jira ticket data.
    Thread-safety: asyncio.Lock.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[dict[str, Any], float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, ticket_id: str, domain: str = "") -> dict[str, Any] | None:
        key = f"{domain}:{ticket_id.upper()}" if domain else ticket_id.upper()
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                logger.info("[jira-cache] MISS %s", key)
                return None

            data, stored_at = entry
            age = time.monotonic() - stored_at

            if age > self._ttl:
                del self._store[key]
                logger.info("[jira-cache] EVICT %s (age=%.1fs)", key, age)
                return None

            logger.info("[jira-cache] HIT %s (age=%.1fs)", key, age)
            return data

    async def set(self, ticket_id: str, data: dict[str, Any], domain: str = "") -> None:
        key = f"{domain}:{ticket_id.upper()}" if domain else ticket_id.upper()
        async with self._lock:
            self._store[key] = (data, time.monotonic())
            logger.info("[jira-cache] SET %s", key)

    async def invalidate(self, ticket_id: str, domain: str = "") -> None:
        key = f"{domain}:{ticket_id.upper()}" if domain else ticket_id.upper()
        async with self._lock:
            if key in self._store:
                del self._store[key]
                logger.info("[jira-cache] INVALIDATE %s", key)

    def size(self) -> int:
        return len(self._store)


class ACStepCache:
    """
    Cache for parsed AC steps (LLM output).
    Prevents redundant LLM calls for the same ticket + guidance.
    """

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[dict[str, Any], float]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, domain: str, ticket_id: str, guidance: str, ticket_data: dict) -> str:
        # Extract only fields that affect LLM parsing
        parse_inputs = {
            "ac": ticket_data.get("acceptance_criteria", ""),
            "summary": ticket_data.get("summary", ""),
            "desc": ticket_data.get("description", ""),
            "attachments": [a.get("id") for a in ticket_data.get("attachments", [])],
            "guidance": guidance.strip(),
        }
        inputs_json = json.dumps(parse_inputs, sort_keys=True)
        inputs_hash = hashlib.sha256(inputs_json.encode()).hexdigest()[:16]

        return f"{domain}:{ticket_id.upper()}:{inputs_hash}"

    async def get(
        self, domain: str, ticket_id: str, guidance: str, ticket_data: dict
    ) -> dict[str, Any] | None:
        key = self._make_key(domain, ticket_id, guidance, ticket_data)
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                logger.info("[ac-cache] MISS %s", key)
                return None

            data, stored_at = entry
            age = time.monotonic() - stored_at
            if age > self._ttl:
                del self._store[key]
                logger.info("[ac-cache] EVICT %s (age=%.1fs)", key, age)
                return None

            logger.info("[ac-cache] HIT %s (age=%.1fs)", key, age)
            return data

    async def set(
        self, domain: str, ticket_id: str, guidance: str, ticket_data: dict, result: dict
    ) -> None:
        key = self._make_key(domain, ticket_id, guidance, ticket_data)
        async with self._lock:
            self._store[key] = (result, time.monotonic())
            logger.info("[ac-cache] SET %s", key)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_cache: JiraCache | None = None
_ac_cache: ACStepCache | None = None


def get_jira_cache() -> JiraCache:
    global _cache
    if _cache is None:
        try:
            from backend.config import settings
            ttl = getattr(settings, "jira_cache_ttl_seconds", 60.0)
        except Exception:
            ttl = 60.0
        _cache = JiraCache(ttl_seconds=float(ttl))
    return _cache


def get_ac_step_cache() -> ACStepCache:
    global _ac_cache
    if _ac_cache is None:
        try:
            from backend.config import settings
            ttl = getattr(settings, "ac_cache_ttl_seconds", 3600.0)
        except Exception:
            ttl = 3600.0
        _ac_cache = ACStepCache(ttl_seconds=float(ttl))
    return _ac_cache
