from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.anyio
async def test_overlay_and_hallucination_integration():
    """
    Verify that functional overlay dismissal exemption and the dropdown hallucination
    verbatim constraints work together during a simulated step execution.
    """
    from backend.engine.executor import _dispatch_action
    from backend.engine.planner import _STATUS_RULES
    from backend.engine.state_tracker import OverlayInfo, PageStateTracker

    # 1. Verify rules contain the verbatim constraint
    assert "verbatim" in _STATUS_RULES.lower()

    # 2. Simulate executor dispensing action with open dropdown
    mock_page = AsyncMock()
    mock_page.keyboard.press = AsyncMock()

    tracker = PageStateTracker(run_id="test_integration")
    tracker._last_state.open_overlays = [
        OverlayInfo(overlay_type="dropdown", selector=".p-dropdown-panel", is_functional=True)
    ]

    action = {"action": "click", "strategy": "get_by_text", "name": "Valid Option", "_run_id": "test_integration"}

    with patch("backend.engine.executor.get_tracker", return_value=tracker):
        with patch("backend.engine.executor._resolve_locator") as mock_resolve:
            mock_locator = AsyncMock()
            mock_resolve.return_value = mock_locator
            await _dispatch_action(mock_page, action)

    # Proactive dismissal should NOT be triggered
    mock_page.keyboard.press.assert_not_called()
    # The actual click action should be dispatched to the verified element
    mock_locator.click.assert_called_once()
