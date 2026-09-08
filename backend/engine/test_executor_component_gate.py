"""
Phase 4 — T1-a: Component-Aware Precondition Check

Tests for _is_target_in_open_container and its integration into _dispatch_action.
When a click target's text is found inside a known closed container (PrimeNG
p-select, p-dropdown, native select, p-autocomplete), the executor must return
TARGET_INSIDE_CLOSED_CONTAINER with a non-empty trigger_selector — not a
Playwright strict-mode stack trace.

AC-VERIFY-1 coverage:
  1. Returns TARGET_INSIDE_CLOSED_CONTAINER when target is inside a closed p-select
  2. trigger_selector is non-empty and non-placeholder
  3. Does NOT raise strict-mode exception on the closed-container path
  4. Returns True (is_inside_closed) + trigger_selector from _is_target_in_open_container
     when a closed container holds the target
  5. Returns False + None from _is_target_in_open_container when no closed container holds target
  6. _dispatch_action falls through to normal click when no closed container detected
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.executor import _dispatch_action, _is_target_in_open_container

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _click_action(name: str = "Contest") -> dict:
    return {
        "action": "click",
        "strategy": "get_by_text",
        "name": name,
        "_run_id": "test-component-gate",
    }


def _make_page_with_closed_container(
    *,
    container_selector: str,
    target_text: str = "Contest",
    trigger_selector: str = "p-select.prf-category",
) -> AsyncMock:
    """
    Build a Playwright page mock where `container_selector` matches 1 element
    (closed container present) that contains target_text.
    """
    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    # The closed container locator has count=1 (present, closed)
    container_loc = AsyncMock()
    container_loc.count = AsyncMock(return_value=1)

    # The target-within-container locator has count=1 (text found inside container)
    target_in_container_loc = AsyncMock()
    target_in_container_loc.count = AsyncMock(return_value=1)
    container_loc.get_by_text = MagicMock(return_value=target_in_container_loc)

    # query_selector returns the trigger element for trigger_selector extraction
    trigger_el = AsyncMock()
    trigger_el.evaluate = AsyncMock(return_value=trigger_selector)

    def _locator_side_effect(selector: str):
        if selector == container_selector:
            return container_loc
        # Default: return empty locator (count=0)
        empty = AsyncMock()
        empty.count = AsyncMock(return_value=0)
        return empty

    page.locator = MagicMock(side_effect=_locator_side_effect)
    page.query_selector = AsyncMock(return_value=trigger_el)

    return page


def _make_page_no_closed_container() -> AsyncMock:
    """
    Build a Playwright page mock where no closed container matches.
    """
    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    empty_loc = AsyncMock()
    empty_loc.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=empty_loc)
    page.query_selector = AsyncMock(return_value=None)
    return page


# ---------------------------------------------------------------------------
# Unit tests for _is_target_in_open_container
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_is_target_in_open_container_detects_closed_p_select():
    """
    AC-VERIFY-1 (unit): _is_target_in_open_container returns (True, trigger_selector)
    when target text is found inside a closed p-select container.
    """
    # p-select-overlay not open is the first CLOSED_CONTAINER_SELECTORS entry
    container_selector = "p-select-overlay:not(.p-select-overlay-open)"
    trigger_selector_value = "p-select.prf-category"
    page = _make_page_with_closed_container(
        container_selector=container_selector,
        trigger_selector=trigger_selector_value,
    )

    is_inside, trigger_sel = await _is_target_in_open_container(page, "Contest")

    assert is_inside is True, "Expected is_inside_closed=True for a closed p-select container"
    assert trigger_sel is not None, "trigger_selector must not be None when container is closed"
    assert len(trigger_sel) > 0, "trigger_selector must be a non-empty string"


@pytest.mark.anyio
async def test_is_target_in_open_container_returns_false_when_no_closed_container():
    """
    AC-VERIFY-1 (unit): _is_target_in_open_container returns (False, None)
    when no closed container holds the target text.
    """
    page = _make_page_no_closed_container()

    is_inside, trigger_sel = await _is_target_in_open_container(page, "Contest")

    assert is_inside is False, "Expected is_inside_closed=False when no closed container present"
    assert trigger_sel is None, "trigger_selector must be None when no closed container"


# ---------------------------------------------------------------------------
# Integration tests for _dispatch_action (component gate in click path)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dispatch_click_returns_target_inside_closed_container_error():
    """
    AC-VERIFY-1: When _is_target_in_open_container returns (True, selector),
    _dispatch_action must return TARGET_INSIDE_CLOSED_CONTAINER with trigger_selector
    in error_message — NOT raise a strict-mode exception.
    """
    trigger_selector_value = "p-select.prf-category"

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    initial_locator = AsyncMock()
    initial_locator.scroll_into_view_if_needed = AsyncMock()
    initial_locator.click = AsyncMock()  # should never be reached

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=initial_locator),
        patch(
            "backend.engine.executor._is_target_in_open_container",
            new_callable=AsyncMock,
            return_value=(True, trigger_selector_value),
        ),
    ):
        result = await _dispatch_action(page, _click_action("Contest"))

    assert result["success"] is False, "Click on closed-container target must fail"
    assert "TARGET_INSIDE_CLOSED_CONTAINER" in result["error_message"], (
        f"error_message must contain TARGET_INSIDE_CLOSED_CONTAINER, got: {result['error_message']!r}"
    )
    assert trigger_selector_value in result["error_message"], (
        f"error_message must include the trigger_selector, got: {result['error_message']!r}"
    )


@pytest.mark.anyio
async def test_dispatch_click_trigger_selector_non_empty():
    """
    AC-VERIFY-1: The trigger_selector in the error_message must be a non-placeholder,
    non-empty CSS selector string.
    """
    trigger_selector_value = "p-select[ng-reflect-name='prf-category']"

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    initial_locator = AsyncMock()
    initial_locator.scroll_into_view_if_needed = AsyncMock()
    initial_locator.click = AsyncMock()

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=initial_locator),
        patch(
            "backend.engine.executor._is_target_in_open_container",
            new_callable=AsyncMock,
            return_value=(True, trigger_selector_value),
        ),
    ):
        result = await _dispatch_action(page, _click_action("Contest"))

    msg = result.get("error_message", "")
    # trigger_selector must not be a placeholder like "<trigger_selector>" or empty string
    assert "<trigger_selector>" not in msg, "Placeholder trigger_selector found in error_message"
    assert trigger_selector_value in msg, (
        f"Real trigger_selector missing from error_message. Got: {msg!r}"
    )


@pytest.mark.anyio
async def test_dispatch_click_no_closed_container_falls_through_to_normal_click():
    """
    AC-VERIFY-5 (regression guard): When _is_target_in_open_container returns (False, None),
    _dispatch_action must proceed to the normal click path — not short-circuit.
    """
    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    initial_locator = AsyncMock()
    initial_locator.scroll_into_view_if_needed = AsyncMock()
    # Make click succeed so we can confirm it was reached
    initial_locator.click = AsyncMock(return_value=None)

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=initial_locator),
        patch(
            "backend.engine.executor._is_target_in_open_container",
            new_callable=AsyncMock,
            return_value=(False, None),
        ),
    ):
        result = await _dispatch_action(page, _click_action("Submit"))

    # Click should have been called (normal path)
    initial_locator.click.assert_called_once()
    assert result["success"] is True


@pytest.mark.anyio
async def test_dispatch_click_gate_checked_before_click_dispatch():
    """
    AC-VERIFY-1: The component gate (_is_target_in_open_container) must be called
    BEFORE the click is dispatched (i.e., click is never attempted on closed-container path).
    """
    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    initial_locator = AsyncMock()
    initial_locator.scroll_into_view_if_needed = AsyncMock()
    # click should never be called when gate fires
    initial_locator.click = AsyncMock(side_effect=AssertionError("click dispatched on closed-container path"))

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=initial_locator),
        patch(
            "backend.engine.executor._is_target_in_open_container",
            new_callable=AsyncMock,
            return_value=(True, "p-select.prf-category"),
        ),
    ):
        result = await _dispatch_action(page, _click_action("Contest"))

    # Must NOT have raised the AssertionError (click was never dispatched)
    assert "TARGET_INSIDE_CLOSED_CONTAINER" in result["error_message"]
    initial_locator.click.assert_not_called()


@pytest.mark.anyio
async def test_dispatch_non_click_action_skips_component_gate():
    """
    AC-VERIFY-5 (regression guard): Non-click actions (fill, navigate, etc.) must not
    be affected by the component gate. _is_target_in_open_container should not be
    called for non-click actions.
    """
    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    page = AsyncMock()
    page.url = "https://qa.vcreative.net/vpromotions"

    fill_locator = AsyncMock()
    fill_locator.fill = AsyncMock(return_value=None)

    gate_spy = AsyncMock(return_value=(False, None))

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=fill_locator),
        patch("backend.engine.executor._is_target_in_open_container", gate_spy),
    ):
        fill_action = {
            "action": "fill",
            "strategy": "get_by_label",
            "name": "Search",
            "value": "vPromotion",
            "_run_id": "test-component-gate",
        }
        await _dispatch_action(page, fill_action)

    gate_spy.assert_not_called()
