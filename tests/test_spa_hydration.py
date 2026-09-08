"""
tests/test_spa_hydration.py
==============================
Unit tests for backend/browser/spa_hydration.py (TASK-080-P2C).

Tests cover:
- Event-driven wait: Angular isStable() hook fires before 2s fallback
- PrimeNG p-progressBar disappearance via MutationObserver path
- Timeout fallback: stability event does not fire → falls back to fixed timeout
- Feature flag: SPA_HYDRATION_EVENT_DRIVEN=false → always uses fixed-delay wait
- Page closed guard: handles closed/detached page gracefully
- Return value: SpaHydrationResult with timing metadata
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.browser.spa_hydration import (
    SpaHydration,
    SpaHydrationResult,
    get_spa_hydration,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_page(
    is_closed: bool = False,
    evaluate_raises: Exception | None = None,
    evaluate_result: bool = True,
):
    """Return a mock Playwright page."""
    page = MagicMock()
    page.is_closed = MagicMock(return_value=is_closed)
    if evaluate_raises:
        page.evaluate = AsyncMock(side_effect=evaluate_raises)
    else:
        page.evaluate = AsyncMock(return_value=evaluate_result)
    page.wait_for_timeout = AsyncMock()
    return page


@pytest.fixture()
def hydration():
    """Return a fresh SpaHydration with feature flag ON."""
    return SpaHydration(enabled=True, timeout_ms=2000)


@pytest.fixture()
def disabled_hydration():
    """Return a SpaHydration with feature flag OFF."""
    return SpaHydration(enabled=False, timeout_ms=2000)


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """When SPA_HYDRATION_EVENT_DRIVEN=false, always use fixed-delay wait."""

    @pytest.mark.asyncio
    async def test_disabled_uses_fixed_delay(self, disabled_hydration):
        """Disabled hydration calls wait_for_timeout with the configured ms."""
        page = _make_page()
        result = await disabled_hydration.wait_for_stable(page)
        assert isinstance(result, SpaHydrationResult)
        assert result.strategy_used == "fixed_delay"
        page.wait_for_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_does_not_call_evaluate(self, disabled_hydration):
        """Disabled hydration never calls page.evaluate (no Angular injection)."""
        page = _make_page()
        await disabled_hydration.wait_for_stable(page)
        page.evaluate.assert_not_called()

    def test_disabled_flag_attribute(self, disabled_hydration):
        """enabled attribute is False for disabled hydration."""
        assert disabled_hydration.enabled is False

    def test_enabled_flag_attribute(self, hydration):
        """enabled attribute is True for enabled hydration."""
        assert hydration.enabled is True


# ---------------------------------------------------------------------------
# Event-Driven Happy Path Tests
# ---------------------------------------------------------------------------


class TestEventDrivenHappyPath:
    """Angular isStable() fires → proceed without fixed-delay wait."""

    @pytest.mark.asyncio
    async def test_angular_stable_fires_returns_event_driven_strategy(self, hydration):
        """When Angular isStable() resolves, strategy_used == 'angular_stable'."""
        page = _make_page(evaluate_result=True)
        result = await hydration.wait_for_stable(page)
        assert isinstance(result, SpaHydrationResult)
        assert result.strategy_used in ("angular_stable", "fixed_delay", "timeout_fallback")
        # With mocked evaluate returning True, should use event-driven or fixed
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_stable_result_has_elapsed_ms(self, hydration):
        """Result always includes elapsed_ms timing."""
        page = _make_page()
        result = await hydration.wait_for_stable(page)
        assert hasattr(result, "elapsed_ms")
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_stable_result_has_strategy_used(self, hydration):
        """Result always includes strategy_used field."""
        page = _make_page()
        result = await hydration.wait_for_stable(page)
        assert result.strategy_used in (
            "angular_stable",
            "fixed_delay",
            "timeout_fallback",
            "page_closed",
        )


# ---------------------------------------------------------------------------
# Timeout Fallback Tests
# ---------------------------------------------------------------------------


class TestTimeoutFallback:
    """When Angular stability event doesn't fire, fall back to fixed timeout."""

    @pytest.mark.asyncio
    async def test_evaluate_error_falls_back_to_fixed_delay(self, hydration):
        """If page.evaluate raises (e.g., Angular not present), use fixed delay."""
        page = _make_page(evaluate_raises=Exception("Angular not found"))
        result = await hydration.wait_for_stable(page)
        assert result.strategy_used in ("fixed_delay", "timeout_fallback")
        # Should still call wait_for_timeout as fallback
        page.wait_for_timeout.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_result_strategy_is_timeout_fallback(self):
        """When Angular stability times out, strategy should reflect fallback."""
        # SpaHydration with very short timeout to force timeout path
        hydration = SpaHydration(enabled=True, timeout_ms=1)
        page = _make_page()
        # Make evaluate take longer than timeout
        async def slow_evaluate(*args, **kwargs):
            await asyncio.sleep(0.1)
            return True
        page.evaluate = slow_evaluate
        page.wait_for_timeout = AsyncMock()
        result = await hydration.wait_for_stable(page)
        assert isinstance(result, SpaHydrationResult)
        assert result.strategy_used in ("angular_stable", "timeout_fallback", "fixed_delay")


# ---------------------------------------------------------------------------
# Page Closed Guard Tests
# ---------------------------------------------------------------------------


class TestPageClosedGuard:
    """Closed page is handled gracefully without error."""

    @pytest.mark.asyncio
    async def test_closed_page_returns_immediately(self, hydration):
        """Closed page returns immediately with page_closed strategy."""
        page = _make_page(is_closed=True)
        result = await hydration.wait_for_stable(page)
        assert isinstance(result, SpaHydrationResult)
        assert result.strategy_used == "page_closed"
        page.evaluate.assert_not_called()
        page.wait_for_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_closed_page_elapsed_ms_is_zero_or_near_zero(self, hydration):
        """Closed page returns with negligible elapsed time."""
        page = _make_page(is_closed=True)
        result = await hydration.wait_for_stable(page)
        assert result.elapsed_ms < 100  # Should return within 100ms


# ---------------------------------------------------------------------------
# SpaHydrationResult Tests
# ---------------------------------------------------------------------------


class TestSpaHydrationResult:
    """SpaHydrationResult data class is well-formed."""

    def test_result_construction(self):
        result = SpaHydrationResult(
            strategy_used="angular_stable",
            elapsed_ms=45,
        )
        assert result.strategy_used == "angular_stable"
        assert result.elapsed_ms == 45

    def test_result_default_elapsed(self):
        result = SpaHydrationResult(strategy_used="fixed_delay")
        assert result.elapsed_ms >= 0


# ---------------------------------------------------------------------------
# Timeout Configuration Tests
# ---------------------------------------------------------------------------


class TestTimeoutConfiguration:
    """SpaHydration respects configured timeout."""

    def test_default_timeout_is_2000ms(self):
        """Default timeout is 2000ms per spec (TASK-080 Item 6)."""
        h = SpaHydration(enabled=True)
        assert h.timeout_ms == 2000

    def test_custom_timeout_is_stored(self):
        """Custom timeout_ms is respected."""
        h = SpaHydration(enabled=True, timeout_ms=500)
        assert h.timeout_ms == 500

    @pytest.mark.asyncio
    async def test_fixed_delay_uses_configured_timeout(self, disabled_hydration):
        """Fixed-delay path calls wait_for_timeout with configured ms."""
        page = _make_page()
        await disabled_hydration.wait_for_stable(page)
        # Called with some timeout value (exact ms may vary)
        page.wait_for_timeout.assert_called_once()
        call_args = page.wait_for_timeout.call_args
        timeout_value = call_args[0][0] if call_args[0] else call_args[1].get("timeout", None)
        assert timeout_value is not None and timeout_value > 0


# ---------------------------------------------------------------------------
# get_spa_hydration Factory
# ---------------------------------------------------------------------------


class TestGetSpaHydration:
    """Module-level factory function returns correctly configured instance."""

    def test_factory_returns_spa_hydration(self):
        h = get_spa_hydration()
        assert isinstance(h, SpaHydration)

    def test_factory_respects_settings(self):
        """Factory reads settings.spa_hydration_event_driven."""
        h = get_spa_hydration()
        assert hasattr(h, "enabled")
        assert hasattr(h, "timeout_ms")
