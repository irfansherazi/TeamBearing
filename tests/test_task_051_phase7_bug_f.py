"""
TASK-051 Phase 7 — Bug F: Jira Ticket In-Memory Cache
=======================================================

Tests for backend/jira/cache.py.

Bug F: Every /execute call and every /preview-steps call independently
fetches the Jira ticket from the Jira API, even when both happen within
seconds of each other (e.g., user clicks "Preview Steps" then "Run").
This doubles the Jira API load and adds latency.

Fix: Add a process-local TTL cache in backend/jira/cache.py that serves
cached ticket data within a 60-second window. jira_fetch_node and the
/preview-steps handler both use this cache.

Tests:
  - test_jira_cache_hit_on_second_call: second call within TTL returns cached data
  - test_jira_cache_miss_after_ttl: call after TTL expiry is a cache miss
  - test_jira_cache_set_stores_data: set() stores data retrievable by get()
  - test_jira_cache_miss_empty_cache: get() on empty cache returns None
  - test_jira_cache_invalidate: invalidate() removes entry
  - test_jira_cache_hit_logs_info: HIT is logged
  - test_jira_cache_miss_logs_info: MISS is logged
  - test_get_jira_cache_returns_singleton: get_jira_cache() returns same instance

Run: python3 -m pytest tests/test_task_051_phase7_bug_f.py -v
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


_SAMPLE_TICKET = {
    "ticket_id": "QA-123",
    "summary": "Test Campaign Creation",
    "acceptance_criteria": "Given I am logged in\nWhen I create a campaign\nThen it appears in the list",
    "acceptance_criteria_steps": ["Navigate to Campaigns", "Create new campaign"],
}


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: JiraCache module importability
# ═══════════════════════════════════════════════════════════════════════════


class TestJiraCacheImportability:
    """JiraCache and get_jira_cache must be importable."""

    def test_jira_cache_class_importable(self):
        from backend.jira.cache import JiraCache

        assert callable(JiraCache)

    def test_get_jira_cache_importable(self):
        from backend.jira.cache import get_jira_cache

        assert callable(get_jira_cache)

    def test_get_jira_cache_returns_singleton(self):
        """get_jira_cache() must return the same instance on repeated calls."""
        # Reset the singleton for a clean test
        import backend.jira.cache as _cache_mod

        _original = _cache_mod._cache
        _cache_mod._cache = None

        from backend.jira.cache import get_jira_cache

        c1 = get_jira_cache()
        c2 = get_jira_cache()
        assert c1 is c2, "get_jira_cache() must return a singleton"

        # Restore original
        _cache_mod._cache = _original


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: JiraCache core functionality
# ═══════════════════════════════════════════════════════════════════════════


class TestJiraCacheCore:
    """Core get/set/invalidate functionality."""

    def _make_cache(self, ttl: float = 60.0):
        from backend.jira.cache import JiraCache

        return JiraCache(ttl_seconds=ttl)

    def test_jira_cache_miss_empty_cache(self):
        """get() on empty cache returns None."""
        cache = self._make_cache()
        result = _run_async(cache.get("QA-123"))
        assert result is None

    def test_jira_cache_set_stores_data(self):
        """set() + get() returns the stored ticket data."""
        cache = self._make_cache()
        _run_async(cache.set("QA-123", _SAMPLE_TICKET))
        result = _run_async(cache.get("QA-123"))
        assert result is not None
        assert result["ticket_id"] == "QA-123"
        assert result["summary"] == "Test Campaign Creation"

    def test_jira_cache_hit_on_second_call(self):
        """
        AC-HAPPY-7 Bug F: second call within TTL returns cached data.
        This is the primary AC — two sequential gets should return the same data
        without re-fetching (simulated by checking the data is identical).
        """
        cache = self._make_cache(ttl=60.0)

        async def run():
            # Simulate /preview-steps: store after first fetch
            await cache.set("QA-456", {"ticket_id": "QA-456", "summary": "Bug Fix"})

            # Simulate /execute: should be a cache HIT
            first = await cache.get("QA-456")
            second = await cache.get("QA-456")
            return first, second

        first, second = _run_async(run())
        assert first is not None, "First get() should be a HIT"
        assert second is not None, "Second get() should also be a HIT (within TTL)"
        assert first["ticket_id"] == second["ticket_id"] == "QA-456"

    def test_jira_cache_miss_after_ttl(self):
        """
        After TTL expires, get() returns None (cache miss / eviction).
        Uses a very short TTL (0.05s) and waits past it.
        """
        cache = self._make_cache(ttl=0.05)  # 50ms TTL

        async def run():
            await cache.set("QA-789", _SAMPLE_TICKET)
            # Wait past TTL
            await asyncio.sleep(0.1)
            return await cache.get("QA-789")

        result = _run_async(run())
        assert result is None, f"Cache entry should have been evicted after TTL expiry. Got: {result!r}"

    def test_jira_cache_invalidate(self):
        """invalidate() removes entry — subsequent get() returns None."""
        cache = self._make_cache()

        async def run():
            await cache.set("QA-123", _SAMPLE_TICKET)
            await cache.invalidate("QA-123")
            return await cache.get("QA-123")

        result = _run_async(run())
        assert result is None, "Invalidated entry should return None on get()"

    def test_jira_cache_size(self):
        """size() returns number of stored entries."""
        cache = self._make_cache()
        assert cache.size() == 0

        _run_async(cache.set("QA-1", {"ticket_id": "QA-1"}))
        assert cache.size() == 1

        _run_async(cache.set("QA-2", {"ticket_id": "QA-2"}))
        assert cache.size() == 2

    def test_jira_cache_different_ticket_ids_independent(self):
        """Different ticket IDs are stored independently."""
        cache = self._make_cache()

        async def run():
            await cache.set("QA-A", {"ticket_id": "QA-A", "summary": "Alpha"})
            await cache.set("QA-B", {"ticket_id": "QA-B", "summary": "Beta"})
            a = await cache.get("QA-A")
            b = await cache.get("QA-B")
            return a, b

        a, b = _run_async(run())
        assert a["summary"] == "Alpha"
        assert b["summary"] == "Beta"

    def test_jira_cache_domain_isolation(self):
        """Entries with same ticket ID but different domains are isolated."""
        cache = self._make_cache()

        async def run():
            # Set same ticket ID on different domains
            await cache.set("QA-1", {"id": "QA-1", "src": "prod"}, domain="prod.atlassian.net")
            await cache.set("QA-1", {"id": "QA-1", "src": "dev"}, domain="dev.atlassian.net")

            # Check isolation
            prod = await cache.get("QA-1", domain="prod.atlassian.net")
            dev = await cache.get("QA-1", domain="dev.atlassian.net")
            no_domain = await cache.get("QA-1")

            return prod, dev, no_domain

        prod, dev, no_domain = _run_async(run())
        assert prod["src"] == "prod"
        assert dev["src"] == "dev"
        assert no_domain is None, "Get without domain should MISS if stored with domain"


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: JiraCache logging
# ═══════════════════════════════════════════════════════════════════════════


class TestJiraCacheLogging:
    """Verify that [jira-cache] HIT/MISS/SET/EVICT are logged."""

    def _make_cache(self, ttl: float = 60.0):
        from backend.jira.cache import JiraCache

        return JiraCache(ttl_seconds=ttl)

    def test_cache_miss_logs_miss(self, caplog):
        """get() on empty cache logs MISS."""
        cache = self._make_cache()
        with caplog.at_level(logging.INFO, logger="backend.jira.cache"):
            _run_async(cache.get("QA-MISS"))
        assert any("MISS" in r.message for r in caplog.records), (
            f"Expected [jira-cache] MISS log. Got: {[r.message for r in caplog.records]}"
        )

    def test_cache_set_logs_set(self, caplog):
        """set() logs SET."""
        cache = self._make_cache()
        with caplog.at_level(logging.INFO, logger="backend.jira.cache"):
            _run_async(cache.set("QA-SET", _SAMPLE_TICKET))
        assert any("SET" in r.message for r in caplog.records)

    def test_cache_hit_logs_hit(self, caplog):
        """get() on populated cache logs HIT."""
        cache = self._make_cache()
        _run_async(cache.set("QA-HIT", _SAMPLE_TICKET))
        with caplog.at_level(logging.INFO, logger="backend.jira.cache"):
            _run_async(cache.get("QA-HIT"))
        assert any("HIT" in r.message for r in caplog.records)

    def test_cache_eviction_logs_evict(self, caplog):
        """get() after TTL expiry logs EVICT."""
        cache = self._make_cache(ttl=0.05)
        _run_async(cache.set("QA-EVICT", _SAMPLE_TICKET))

        async def wait_and_get():
            await asyncio.sleep(0.1)
            return await cache.get("QA-EVICT")

        with caplog.at_level(logging.INFO, logger="backend.jira.cache"):
            _run_async(wait_and_get())
        assert any("EVICT" in r.message for r in caplog.records)
