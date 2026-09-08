from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_dismiss_overlays_calls_escape():
    # Import inside test to allow test to fail cleanly before function is defined
    try:
        from backend.engine.executor import _dismiss_overlays
    except ImportError:
        pytest.fail("_dismiss_overlays is not imported or defined")

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {"is_functional": False}
    mock_tracker.refresh = AsyncMock()

    with patch("backend.engine.state_tracker.get_tracker", return_value=mock_tracker):
        await _dismiss_overlays(mock_page, run_id="test_run")

    mock_page.keyboard.press.assert_called_with("Escape")
    mock_page.wait_for_timeout.assert_called_with(300)
    mock_tracker.refresh.assert_called_once_with(mock_page)


@pytest.mark.anyio
async def test_dismiss_overlays_no_overlay_open():
    try:
        from backend.engine.executor import _dismiss_overlays
    except ImportError:
        pytest.fail("_dismiss_overlays is not imported or defined")

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = False
    mock_tracker.refresh = AsyncMock()

    with patch("backend.engine.state_tracker.get_tracker", return_value=mock_tracker):
        await _dismiss_overlays(mock_page, run_id="test_run")

    mock_page.keyboard.press.assert_not_called()
