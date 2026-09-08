from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_overlay_classification_functional_vs_blocking():
    from backend.engine.state_tracker import OverlayInfo, PageStateTracker

    tracker = PageStateTracker(run_id="test")
    # Test functional overlay (dropdown)
    tracker._last_state.open_overlays = [
        OverlayInfo(overlay_type="dropdown", selector=".p-dropdown-panel", is_functional=True)
    ]
    constraint = tracker.get_overlay_constraint()
    assert constraint.get("is_functional") is True

    # Test blocking overlay (dialog)
    tracker._last_state.open_overlays = [OverlayInfo(overlay_type="dialog", selector=".p-dialog", is_functional=False)]
    constraint = tracker.get_overlay_constraint()
    assert constraint.get("is_functional") is False


@pytest.mark.anyio
async def test_overlay_dismissal_skipped_for_functional():
    from backend.engine.executor import _dispatch_action

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {
        "active": True,
        "type": "dropdown",
        "selector": ".p-dropdown-panel",
        "is_functional": True,
    }

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        action = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": "Outside Element",
            "_run_id": "test",
        }
        with patch("backend.engine.executor._resolve_locator") as mock_resolve:
            mock_locator = AsyncMock()
            mock_resolve.return_value = mock_locator
            await _dispatch_action(mock_page, action)

    mock_page.keyboard.press.assert_not_called()


@pytest.mark.anyio
async def test_overlay_dismissal_triggered_for_modal():
    from backend.engine.executor import _dispatch_action

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {
        "active": True,
        "type": "dialog",
        "selector": ".p-dialog",
        "is_functional": False,
    }
    mock_tracker.refresh = AsyncMock()

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        action = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": "Outside Element",
            "_run_id": "test",
        }
        with patch("backend.engine.executor._resolve_locator") as mock_resolve:
            mock_locator = AsyncMock()
            mock_resolve.return_value = mock_locator
            await _dispatch_action(mock_page, action)

    mock_page.keyboard.press.assert_called_with("Escape")


@pytest.mark.anyio
async def test_unknown_overlay_falls_back_to_dismissal():
    from backend.engine.executor import _dispatch_action

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    # Missing is_functional defaults to False (safe default)
    mock_tracker.get_overlay_constraint.return_value = {
        "active": True,
        "type": "unknown",
        "selector": ".some-unknown",
    }
    mock_tracker.refresh = AsyncMock()

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        action = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": "Outside Element",
            "_run_id": "test",
        }
        with patch("backend.engine.executor._resolve_locator") as mock_resolve:
            mock_locator = AsyncMock()
            mock_resolve.return_value = mock_locator
            await _dispatch_action(mock_page, action)

    mock_page.keyboard.press.assert_called_with("Escape")


@pytest.mark.anyio
async def test_overlay_oscillation_loop_prevented():
    from backend.engine.executor import _dispatch_action

    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()

    mock_tracker = MagicMock()
    mock_tracker.has_open_overlay.return_value = True
    mock_tracker.get_overlay_constraint.return_value = {
        "active": True,
        "type": "dropdown",
        "selector": ".p-dropdown-panel",
        "is_functional": True,
    }

    with patch("backend.engine.executor.get_tracker", return_value=mock_tracker):
        action = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": "Dropdown Trigger",
            "_run_id": "test",
        }
        with patch("backend.engine.executor._resolve_locator") as mock_resolve:
            mock_locator = AsyncMock()
            mock_resolve.return_value = mock_locator
            await _dispatch_action(mock_page, action)

    mock_page.keyboard.press.assert_not_called()
