
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.human_takeover import _inject_click_capture_listener

@pytest.mark.anyio
async def test_inject_click_capture_listener_passes_theme():
    """AC-THEME-1: Verify that theme is passed to JS injection points."""
    mock_page = AsyncMock()
    mock_page.frames = []
    mock_page.is_closed.return_value = False
    
    run_id = "run-123"
    theme = "dark"
    
    with patch("backend.engine.human_takeover.settings") as mock_settings:
        await _inject_click_capture_listener(mock_page, run_id, theme=theme)
        
        # 1. Check add_init_script
        assert mock_page.add_init_script.called
        init_script = mock_page.add_init_script.call_args[1]["script"]
        assert f"const theme = '{theme}';" in init_script
        
        # 2. Check main page evaluate
        # First evaluate resets active flag, second evaluates js_code
        assert mock_page.evaluate.call_count >= 2
        # Check the call where js_code is evaluated with run_id and theme
        # await page.evaluate(js_code, run_id, theme)
        found_theme_eval = False
        for call in mock_page.evaluate.call_args_list:
            if len(call[0]) >= 3 and call[0][1] == run_id and call[0][2] == theme:
                found_theme_eval = True
                break
        assert found_theme_eval, "theme was not passed to page.evaluate"

@pytest.mark.anyio
async def test_inject_click_capture_listener_defaults_to_light():
    """AC-THEME-1: Verify that theme defaults to light if not provided."""
    mock_page = AsyncMock()
    mock_page.frames = []
    mock_page.is_closed.return_value = False
    
    run_id = "run-123"
    
    await _inject_click_capture_listener(mock_page, run_id) # theme defaults to "light"
    
    init_script = mock_page.add_init_script.call_args[1]["script"]
    assert "const theme = 'light';" in init_script
