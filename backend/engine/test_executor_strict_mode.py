"""
Phase 3 — T1-b: Kill Futile Scroll Fallback in Strict-Mode Branch

Tests for the Stage 2.5 short-circuit: when visible_count == 0 and
total_count > 5, the executor must NOT call scroll_into_view_if_needed
and must immediately return STRICT_MODE_AMBIGUOUS with a strategy hint.

AC-VERIFY-2 coverage:
  1. Returns STRICT_MODE_AMBIGUOUS in <=500ms when total_count > 5 and visible_count == 0
  2. scroll_into_view_if_needed is NEVER called on the short-circuit path
  3. error_message contains the strategy-switch hint
  4. When total_count <= 5, the existing scroll fallback path runs (scroll IS called)
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.executor import _dispatch_action


def _make_action(name: str = "Contest") -> dict:
    return {
        "action": "click",
        "strategy": "get_by_text",
        "name": name,
        "_run_id": "test-strict-mode",
    }


def _build_page_mock_strict(*, total_count: int, visible_count: int = 0) -> AsyncMock:
    """
    Build a page mock whose get_by_text raises 'strict mode violation' on click,
    then whose filter+count/locator.count sequence returns the supplied counts.
    """
    page = AsyncMock()
    page.url = "https://qa.vcreative.net/test"

    # The initial locator returned by _resolve_locator (called for the outer click)
    initial_locator = AsyncMock()
    initial_locator.scroll_into_view_if_needed = AsyncMock()  # pre-click scroll (non-fatal)
    initial_locator.click = AsyncMock(
        side_effect=Exception("strict mode violation: get_by_text('Contest') resolved to 41 elements")
    )

    # Stage 1 filter (visible elements)
    visible_locator = AsyncMock()
    visible_locator.count = AsyncMock(return_value=visible_count)
    visible_locator.first = AsyncMock()
    initial_locator.filter = MagicMock(return_value=visible_locator)

    # Stage 2.5 base_loc for total_count (returned by second _resolve_locator call)
    total_locator = AsyncMock()
    total_locator.count = AsyncMock(return_value=total_count)
    # .first on the total locator — should NOT be called on the short-circuit path
    first_el = AsyncMock()
    first_el.scroll_into_view_if_needed = AsyncMock()
    first_el.click = AsyncMock()
    total_locator.first = first_el

    return page, initial_locator, total_locator


@pytest.mark.anyio
async def test_strict_mode_shortcircuit_returns_ambiguous_fast():
    """
    AC-VERIFY-2: When total_count > 5 and visible_count == 0, STRICT_MODE_AMBIGUOUS
    is returned and the entire branch completes in <= 500 ms.
    """
    page, initial_locator, total_locator = _build_page_mock_strict(total_count=41)

    call_count = [0]

    async def resolve_side_effect(p, action):
        call_count[0] += 1
        if call_count[0] == 1:
            return initial_locator
        # Second call (Stage 2.5 total count check) and any subsequent
        return total_locator

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    t0 = time.monotonic()
    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", side_effect=resolve_side_effect),
    ):
        result = await _dispatch_action(page, _make_action())
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert result["success"] is False
    assert "STRICT_MODE_AMBIGUOUS" in result["error_message"], (
        f"Expected STRICT_MODE_AMBIGUOUS in error_message, got: {result['error_message']}"
    )
    assert elapsed_ms <= 500, (
        f"Branch took {elapsed_ms:.1f} ms — must complete in <= 500 ms (T1-b spec)"
    )


@pytest.mark.anyio
async def test_strict_mode_shortcircuit_no_scroll_called():
    """
    AC-VERIFY-2: scroll_into_view_if_needed on .first must NEVER be called
    when total_count > 5 and visible_count == 0.
    """
    page, initial_locator, total_locator = _build_page_mock_strict(total_count=41)

    call_count = [0]

    async def resolve_side_effect(p, action):
        call_count[0] += 1
        if call_count[0] == 1:
            return initial_locator
        return total_locator

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", side_effect=resolve_side_effect),
    ):
        await _dispatch_action(page, _make_action())

    # The .first.scroll_into_view_if_needed on the total_count locator must never fire
    total_locator.first.scroll_into_view_if_needed.assert_not_called()


@pytest.mark.anyio
async def test_strict_mode_shortcircuit_error_message_has_strategy_hint():
    """
    AC-VERIFY-2: The returned error_message must contain a concrete strategy-switch
    hint so the planner knows what to do next.
    """
    page, initial_locator, total_locator = _build_page_mock_strict(total_count=41)

    call_count = [0]

    async def resolve_side_effect(p, action):
        call_count[0] += 1
        if call_count[0] == 1:
            return initial_locator
        return total_locator

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", side_effect=resolve_side_effect),
    ):
        result = await _dispatch_action(page, _make_action())

    msg = result.get("error_message", "")
    # Must contain at least one of the canonical strategy hints
    hint_present = any(
        hint in msg
        for hint in ("container_selector", "get_by_role", "option", "strategy")
    )
    assert hint_present, (
        f"error_message lacks a strategy-switch hint. Got: {msg!r}"
    )


@pytest.mark.anyio
async def test_strict_mode_small_count_still_scrolls():
    """
    AC-VERIFY-5: When total_count <= 5, the existing scroll-fallback path
    runs unchanged — scroll_into_view_if_needed IS called on .first.
    This confirms the short-circuit only fires for high-count (pre-render) scenarios.
    """
    # total_count = 3 — below the threshold; scroll path should run
    page, initial_locator, total_locator = _build_page_mock_strict(total_count=3)

    # Make scroll succeed so the executor can reach click
    total_locator.first.scroll_into_view_if_needed = AsyncMock()
    total_locator.first.click = AsyncMock()

    call_count = [0]

    async def resolve_side_effect(p, action):
        call_count[0] += 1
        if call_count[0] == 1:
            return initial_locator
        return total_locator

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", side_effect=resolve_side_effect),
    ):
        await _dispatch_action(page, _make_action())

    # scroll_into_view_if_needed MUST have been called on the small-count path
    total_locator.first.scroll_into_view_if_needed.assert_called_once()
