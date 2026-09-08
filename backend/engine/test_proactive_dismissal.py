from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.executor import _dispatch_action


@pytest.mark.anyio
async def test_proactive_dismissal_outside_overlay():
    """
    AC-HAPPY-1: If an overlay is open and the target is outside,
    'Escape' is pressed and then the action is executed.
    """
    page = AsyncMock()
    # Mocking a simple click action
    action = {
        "action": "click",
        "strategy": "get_by_role",
        "role": "button",
        "name": "Submit",
        "container_selector": "",  # Target is outside because it's empty
        "_run_id": "test-run-123",
    }

    # Mock PageStateTracker
    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {"active": True, "selector": ".p-select-overlay"}

    with (
        patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
        patch("backend.engine.executor._resolve_locator", return_value=AsyncMock()),
    ):
        # We need to mock _resolve_locator to return a locator that has a click method
        mock_locator = AsyncMock()
        with patch("backend.engine.executor._resolve_locator", return_value=mock_locator):
            await _dispatch_action(page, action)

            # Verify Escape was pressed
            page.keyboard.press.assert_any_call("Escape")
            # Verify action was still executed
            mock_locator.click.assert_called()


@pytest.mark.anyio
async def test_proactive_dismissal_inside_overlay():
    """
    AC-HAPPY-2: If an overlay is open and the target is INSIDE
    (e.g., selecting an option), no dismissal occurs.
    """
    page = AsyncMock()
    # Mocking a click inside the overlay
    action = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Option 1",
        "container_selector": ".p-select-overlay",  # Matches exactly
        "_run_id": "test-run-123",
    }

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {"active": True, "selector": ".p-select-overlay"}

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        mock_locator = AsyncMock()
        with patch("backend.engine.executor._resolve_locator", return_value=mock_locator):
            await _dispatch_action(page, action)

            # Verify Escape was NOT pressed
            page.keyboard.press.assert_not_called()
            # Verify action was executed
            mock_locator.click.assert_called()


@pytest.mark.anyio
async def test_proactive_dismissal_child_of_overlay():
    """
    AC-HAPPY-2 Extension: If the target is a child of the overlay selector,
    no dismissal occurs.
    """
    page = AsyncMock()
    action = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Option 1",
        "container_selector": ".p-select-overlay li",  # Child selector
        "_run_id": "test-run-123",
    }

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {"active": True, "selector": ".p-select-overlay"}

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        mock_locator = AsyncMock()
        with patch("backend.engine.executor._resolve_locator", return_value=mock_locator):
            await _dispatch_action(page, action)

            # Verify Escape was NOT pressed
            page.keyboard.press.assert_not_called()


@pytest.mark.anyio
async def test_proactive_dismissal_no_overlay():
    """
    AC-HAPPY-3: If no overlay is open, executor proceeds normally.
    """
    page = AsyncMock()
    action = {
        "action": "click",
        "strategy": "get_by_role",
        "role": "button",
        "name": "Submit",
        "_run_id": "test-run-123",
    }

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        mock_locator = AsyncMock()
        with patch("backend.engine.executor._resolve_locator", return_value=mock_locator):
            await _dispatch_action(page, action)

            # Verify Escape was NOT pressed
            page.keyboard.press.assert_not_called()
            # Verify action was executed
            mock_locator.click.assert_called()


@pytest.mark.anyio
async def test_proactive_dismissal_escape_action():
    """
    Edge case: If the action IS pressing Escape, don't press it again.
    """
    page = AsyncMock()
    action = {"action": "press_key", "value": "Escape", "_run_id": "test-run-123"}

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {"active": True, "selector": ".p-select-overlay"}

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        await _dispatch_action(page, action)

        # Verify Escape was pressed exactly once (for the action itself)
        assert page.keyboard.press.call_count == 1
        page.keyboard.press.assert_called_with("Escape")
