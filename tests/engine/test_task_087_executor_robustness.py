
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.engine.executor import _resolve_locator

@pytest.mark.anyio
async def test_resolve_locator_handles_new_strategies():
    """TASK-087: _resolve_locator should return None for window and coordinate_action."""
    mock_page = AsyncMock()
    
    # Test 'window'
    action_window = {"strategy": "window"}
    locator_window = await _resolve_locator(mock_page, action_window)
    assert locator_window is None
    
    # Test 'coordinate_action'
    action_coord = {"strategy": "coordinate_action"}
    locator_coord = await _resolve_locator(mock_page, action_coord)
    assert locator_coord is None

@pytest.mark.anyio
async def test_resolve_locator_standard_strategy():
    """Sanity check: standard strategies still work."""
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_page.get_by_role.return_value = mock_locator
    
    action = {"strategy": "get_by_role", "role": "button", "name": "Submit"}
    locator = await _resolve_locator(mock_page, action)
    assert locator == mock_locator
    mock_page.get_by_role.assert_called_with("button", name="Submit")
