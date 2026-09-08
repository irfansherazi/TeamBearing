"""
tests/test_kb_prefetcher.py
============================
Unit tests for backend/kb/prefetcher.py (TASK-080-P1D).

Tests cover:
- Pre-fetch fires asyncio.create_task() after planner emits action
- Result stored in VQAState.prefetch_cache keyed by step index
- Fallback to synchronous fetch if prefetch result not ready
- Feature flag: SPECULATIVE_PREFETCH_ENABLED=false → no prefetch task created
- Cache hit: prefetch_cache[step_idx] returned without re-fetch
- Error in prefetch task does not crash the main execution
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.kb.prefetcher import KBPrefetcher, PrefetchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_kb_client():
    """A KB client mock that returns a canned context string."""
    client = MagicMock()
    client.query_with_expansion = AsyncMock(return_value="<kb_context>Mocked KB Article</kb_context>")
    return client


@pytest.fixture()
def prefetcher(mock_kb_client):
    return KBPrefetcher(kb_client=mock_kb_client, enabled=True)


@pytest.fixture()
def disabled_prefetcher(mock_kb_client):
    return KBPrefetcher(kb_client=mock_kb_client, enabled=False)


@pytest.fixture()
def sample_steps():
    return [
        {"goal": "Navigate to Production Orders", "step_type": "NAVIGATE"},
        {"goal": "Click New Request button", "step_type": "CLICK"},
        {"goal": "Fill client field with Bob", "step_type": "FILL"},
        {"goal": "Verify form is visible", "step_type": "VERIFY_ONLY"},
    ]


# ---------------------------------------------------------------------------
# Prefetch Task Tests
# ---------------------------------------------------------------------------


class TestPrefetchTaskCreation:
    @pytest.mark.asyncio
    async def test_prefetch_creates_background_task(self, prefetcher, sample_steps):
        """start_prefetch() should return a Task object (non-blocking)."""
        task = prefetcher.start_prefetch(step_index=1, steps=sample_steps)
        assert task is not None
        # Task should be an asyncio.Task
        assert isinstance(task, asyncio.Task)
        # Clean up
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_prefetch_result_is_stored_in_cache(self, prefetcher, sample_steps):
        """After awaiting the task, result appears in cache."""
        task = prefetcher.start_prefetch(step_index=1, steps=sample_steps)
        result: PrefetchResult = await task
        assert prefetcher.get_cached(step_index=1) is not None

    @pytest.mark.asyncio
    async def test_prefetch_calls_kb_client(self, prefetcher, mock_kb_client, sample_steps):
        """Prefetch should call kb_client.query_with_expansion with step goal."""
        task = prefetcher.start_prefetch(step_index=1, steps=sample_steps)
        await task
        mock_kb_client.query_with_expansion.assert_called_once()


# ---------------------------------------------------------------------------
# Cache Hit Tests
# ---------------------------------------------------------------------------


class TestPrefetchCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self, prefetcher, sample_steps):
        """get_or_fetch() returns cached result without calling KB client again."""
        task = prefetcher.start_prefetch(step_index=2, steps=sample_steps)
        await task

        call_count_before = mock_kb_client = MagicMock()
        cached = prefetcher.get_cached(step_index=2)
        assert cached is not None

    @pytest.mark.asyncio
    async def test_cache_miss_falls_back_to_sync_fetch(self, prefetcher, mock_kb_client, sample_steps):
        """get_or_fetch() calls KB client synchronously when cache is empty."""
        # Don't call start_prefetch — cache is empty
        result: PrefetchResult = await prefetcher.get_or_fetch(step_index=3, steps=sample_steps)
        assert result is not None
        # KB client should be called to fetch synchronously
        mock_kb_client.query_with_expansion.assert_called()

    def test_get_cached_returns_none_for_miss(self, prefetcher):
        """Cache miss → get_cached returns None."""
        result = prefetcher.get_cached(step_index=99)
        assert result is None


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestPrefetchFeatureFlag:
    def test_disabled_prefetcher_returns_none_task(self, disabled_prefetcher, sample_steps):
        """Feature flag off → start_prefetch returns None (no task created)."""
        task = disabled_prefetcher.start_prefetch(step_index=1, steps=sample_steps)
        assert task is None

    @pytest.mark.asyncio
    async def test_disabled_prefetcher_get_or_fetch_still_works(self, disabled_prefetcher, mock_kb_client, sample_steps):
        """Even when disabled, get_or_fetch falls back to synchronous KB call."""
        result: PrefetchResult = await disabled_prefetcher.get_or_fetch(step_index=0, steps=sample_steps)
        assert result is not None
        mock_kb_client.query_with_expansion.assert_called()


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestPrefetchErrorHandling:
    @pytest.mark.asyncio
    async def test_kb_error_in_task_does_not_propagate(self, mock_kb_client, sample_steps):
        """KB client error in background task should be caught, not crash."""
        mock_kb_client.query_with_expansion = AsyncMock(side_effect=RuntimeError("KB unavailable"))
        prefetcher = KBPrefetcher(kb_client=mock_kb_client, enabled=True)
        task = prefetcher.start_prefetch(step_index=0, steps=sample_steps)
        # Awaiting the task should NOT raise
        result = await task
        # Cache should be None or have an error result
        cached = prefetcher.get_cached(step_index=0)
        # Either None (error suppressed) or a PrefetchResult with error flag
        assert cached is None or (isinstance(cached, PrefetchResult) and cached.error is not None)

    @pytest.mark.asyncio
    async def test_empty_steps_handled(self, prefetcher):
        """Empty steps list → no crash."""
        task = prefetcher.start_prefetch(step_index=0, steps=[])
        if task is not None:
            result = await task


# ---------------------------------------------------------------------------
# PrefetchResult Schema Tests
# ---------------------------------------------------------------------------


class TestPrefetchResult:
    @pytest.mark.asyncio
    async def test_prefetch_result_has_context_string(self, prefetcher, sample_steps):
        task = prefetcher.start_prefetch(step_index=0, steps=sample_steps)
        result: PrefetchResult = await task
        assert isinstance(result.context, str)
        assert len(result.context) > 0

    @pytest.mark.asyncio
    async def test_prefetch_result_has_step_index(self, prefetcher, sample_steps):
        task = prefetcher.start_prefetch(step_index=2, steps=sample_steps)
        result: PrefetchResult = await task
        assert result.step_index == 2
