"""
tests/test_speculative_planner.py
====================================
Unit tests for backend/engine/speculative_planner.py (TASK-080-P3C).

Tests cover:
- SpeculativePlanner.start_prefetch(): spawns asyncio.Task for step N+1
- SpeculativePlanner.get_plan(): returns cached plan when ready
- Poison signal: plan is discarded when current step N fails
- Concurrent access: plan is not used after discard (no stale state)
- Feature flag: SPECULATIVE_PLANNING_ENABLED=false → no prefetch spawned
- Happy path: step N succeeds → speculative plan applied immediately
- Fallback: if prefetch not ready when needed, returns None gracefully

AC Coverage:
- AC-EDGE-1: Speculative plan discarded on step N failure
- AC-ENTRY-1: SPECULATIVE_PLANNING_ENABLED=false → no background tasks
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm_caller():
    """Async callable simulating an LLM plan generation call."""
    caller = AsyncMock()
    caller.return_value = {"action": "click", "target": "Submit"}
    return caller


@pytest.fixture()
def speculative_planner(mock_llm_caller):
    """Return a SpeculativePlanner with the feature flag enabled."""
    from backend.engine.speculative_planner import SpeculativePlanner

    return SpeculativePlanner(enabled=True, llm_caller=mock_llm_caller)


@pytest.fixture()
def disabled_planner(mock_llm_caller):
    """Return a SpeculativePlanner with the feature flag disabled."""
    from backend.engine.speculative_planner import SpeculativePlanner

    return SpeculativePlanner(enabled=False, llm_caller=mock_llm_caller)


# ---------------------------------------------------------------------------
# Tests: Initial state
# ---------------------------------------------------------------------------


class TestSpeculativePlannerInit:
    """SpeculativePlanner initializes with clean state."""

    def test_no_pending_task_on_init(self, speculative_planner):
        assert speculative_planner._pending_task is None

    def test_no_cached_plan_on_init(self, speculative_planner):
        assert speculative_planner._cached_plan is None

    def test_step_index_is_none_on_init(self, speculative_planner):
        assert speculative_planner._prefetch_step_index is None


# ---------------------------------------------------------------------------
# Tests: Feature flag — disabled path
# ---------------------------------------------------------------------------


class TestFeatureFlagDisabled:
    """PARALLEL_PLANNING_ENABLED=false → no background tasks spawned."""

    @pytest.mark.asyncio
    async def test_start_prefetch_does_nothing_when_disabled(self, disabled_planner):
        """Disabled planner should not start any asyncio.Task."""
        disabled_planner.start_prefetch(step_index=1, context={})
        assert disabled_planner._pending_task is None

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_when_disabled(self, disabled_planner):
        result = await disabled_planner.get_plan(step_index=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_discard_is_noop_when_disabled(self, disabled_planner):
        """Discard should not raise when disabled."""
        disabled_planner.discard(step_index=0)  # no-op
        assert disabled_planner._cached_plan is None


# ---------------------------------------------------------------------------
# Tests: Happy path — start_prefetch + get_plan
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Speculative plan is generated and retrieved correctly."""

    @pytest.mark.asyncio
    async def test_start_prefetch_spawns_task(self, speculative_planner):
        """start_prefetch() creates an asyncio.Task."""
        speculative_planner.start_prefetch(step_index=1, context={"ac_step": "Click Submit"})
        assert speculative_planner._pending_task is not None
        # Cancel to clean up
        speculative_planner._pending_task.cancel()
        try:
            await speculative_planner._pending_task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_get_plan_returns_cached_plan_when_ready(self, speculative_planner, mock_llm_caller):
        """get_plan() returns the LLM result once the prefetch completes."""
        mock_llm_caller.return_value = {"action": "fill", "target": "email"}

        speculative_planner.start_prefetch(step_index=2, context={"ac_step": "Fill email"})
        # Wait for the task to complete
        if speculative_planner._pending_task:
            await speculative_planner._pending_task

        plan = await speculative_planner.get_plan(step_index=2)
        assert plan is not None
        assert plan.get("action") == "fill"

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_for_wrong_step_index(self, speculative_planner, mock_llm_caller):
        """Plan for step 2 should not be returned when requesting step 5."""
        mock_llm_caller.return_value = {"action": "click", "target": "btn"}

        speculative_planner.start_prefetch(step_index=2, context={})
        if speculative_planner._pending_task:
            await speculative_planner._pending_task

        plan = await speculative_planner.get_plan(step_index=5)
        assert plan is None  # Wrong index → no plan returned

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_when_prefetch_not_started(self, speculative_planner):
        """No prefetch running → get_plan() returns None immediately."""
        plan = await speculative_planner.get_plan(step_index=3)
        assert plan is None

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_when_task_not_complete(self, speculative_planner):
        """If task is still running, get_plan() returns None (no blocking)."""
        # Simulate a long-running prefetch
        async def _slow_llm(context):
            await asyncio.sleep(10)  # Very slow — won't complete in test
            return {"action": "click"}

        speculative_planner._llm_caller = _slow_llm
        speculative_planner.start_prefetch(step_index=1, context={})

        # Should not block — returns None immediately
        plan = await speculative_planner.get_plan(step_index=1)
        assert plan is None

        # Cleanup
        if speculative_planner._pending_task:
            speculative_planner._pending_task.cancel()
            try:
                await speculative_planner._pending_task
            except (asyncio.CancelledError, Exception):
                pass


# ---------------------------------------------------------------------------
# Tests: Poison signal — AC-EDGE-1
# ---------------------------------------------------------------------------


class TestPoisonSignal:
    """AC-EDGE-1: Speculative plan discarded when step N fails."""

    @pytest.mark.asyncio
    async def test_discard_cancels_pending_task(self, speculative_planner, mock_llm_caller):
        """discard() cancels the in-flight prefetch task."""

        async def _blocking_llm(context):
            await asyncio.sleep(100)
            return {}

        speculative_planner._llm_caller = _blocking_llm
        speculative_planner.start_prefetch(step_index=1, context={})
        task = speculative_planner._pending_task
        assert task is not None

        speculative_planner.discard(step_index=0)  # Step 0 failed → discard step 1 prefetch

        # Task should be cancelled
        assert task.cancelled() or speculative_planner._pending_task is None

        # Cleanup
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_discard_clears_cached_plan(self, speculative_planner, mock_llm_caller):
        """After discard, cached plan is wiped."""
        mock_llm_caller.return_value = {"action": "click"}

        speculative_planner.start_prefetch(step_index=1, context={})
        if speculative_planner._pending_task:
            await speculative_planner._pending_task

        # Plan is cached
        plan = await speculative_planner.get_plan(step_index=1)
        assert plan is not None

        # Now discard due to failure
        speculative_planner.discard(step_index=0)

        assert speculative_planner._cached_plan is None

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_after_discard(self, speculative_planner, mock_llm_caller):
        """Plan cannot be used after discard — zero stale state."""
        mock_llm_caller.return_value = {"action": "navigate", "url": "https://example.com"}

        speculative_planner.start_prefetch(step_index=2, context={})
        if speculative_planner._pending_task:
            await speculative_planner._pending_task

        # Discard because step 1 failed
        speculative_planner.discard(step_index=1)

        # Plan should not be available
        plan = await speculative_planner.get_plan(step_index=2)
        assert plan is None

    @pytest.mark.asyncio
    async def test_new_prefetch_after_discard_works(self, speculative_planner, mock_llm_caller):
        """After discard, a fresh prefetch for the corrected state works."""
        mock_llm_caller.return_value = {"action": "fill"}

        # Start, then discard
        speculative_planner.start_prefetch(step_index=1, context={})
        speculative_planner.discard(step_index=0)

        # Now start a new prefetch for the corrected step
        mock_llm_caller.return_value = {"action": "navigate", "corrected": True}
        speculative_planner.start_prefetch(step_index=1, context={"corrected_state": True})

        if speculative_planner._pending_task:
            await speculative_planner._pending_task

        plan = await speculative_planner.get_plan(step_index=1)
        assert plan is not None
        assert plan.get("corrected") is True


# ---------------------------------------------------------------------------
# Tests: LLM caller error handling
# ---------------------------------------------------------------------------


class TestLLMErrorHandling:
    """If the LLM call fails, plan is None (no crash)."""

    @pytest.mark.asyncio
    async def test_llm_exception_results_in_none_plan(self, speculative_planner, mock_llm_caller):
        """LLM failures are swallowed — get_plan() returns None gracefully."""
        mock_llm_caller.side_effect = RuntimeError("LLM unavailable")

        speculative_planner.start_prefetch(step_index=3, context={})
        # Wait for task (it will fail internally)
        if speculative_planner._pending_task:
            try:
                await speculative_planner._pending_task
            except Exception:
                pass

        # Plan should be None — error was swallowed
        plan = await speculative_planner.get_plan(step_index=3)
        assert plan is None

    @pytest.mark.asyncio
    async def test_llm_timeout_results_in_none_plan(self, speculative_planner):
        """LLM timeout doesn't block get_plan() — returns None immediately."""
        import asyncio

        async def _timeout_llm(context):
            await asyncio.sleep(100)  # Simulated timeout
            return {}

        speculative_planner._llm_caller = _timeout_llm
        speculative_planner.start_prefetch(step_index=4, context={})

        # get_plan() must not wait
        plan = await speculative_planner.get_plan(step_index=4)
        assert plan is None

        # Cleanup
        if speculative_planner._pending_task:
            speculative_planner._pending_task.cancel()
            try:
                await speculative_planner._pending_task
            except (asyncio.CancelledError, Exception):
                pass
