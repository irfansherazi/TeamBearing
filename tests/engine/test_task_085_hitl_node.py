import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.human_takeover import human_takeover_node

@pytest.mark.anyio
async def test_human_takeover_node_starts_screencast():
    """
    WI-085-001: Verify that human_takeover_node initiates a CDP screencast.
    """
    state = {
        "run_id": "test-run-085-screencast",
        "jira_ticket": {
            "ticket_id": "VC2-123",
            "acceptance_criteria_steps": ["Step 1"]
        },
        "ac_step_index": 0,
        "execution_mode": "interactive"
    }
    
    mock_manager = MagicMock()
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.on = MagicMock()
    mock_manager.page = mock_page
    
    mock_cdp = AsyncMock()
    mock_cdp.on = MagicMock()
    # Ensure get_cdp_session is an AsyncMock so it can be awaited
    mock_manager.get_cdp_session = AsyncMock(return_value=mock_cdp)
    
    # Mock broadcast callback to avoid errors
    mock_broadcast = AsyncMock()
    
    with patch("backend.engine.human_takeover.get_manager", return_value=mock_manager), \
         patch("backend.engine.human_takeover._WS_BROADCAST_FN", mock_broadcast), \
         patch("backend.engine.human_takeover.register_takeover") as mock_reg, \
         patch("backend.engine.human_takeover._inject_click_capture_listener", AsyncMock()), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        
        mock_event = AsyncMock()
        mock_reg.return_value = mock_event
        
        await human_takeover_node(state)
        
        # Verify screencast started
        mock_cdp.send.assert_any_call("Page.startScreencast", {"format": "jpeg", "quality": 80, "everyNthFrame": 1})
        # Verify screencast stopped in finally block
        mock_cdp.send.assert_any_call("Page.stopScreencast")
        mock_cdp.detach.assert_called_once()

@pytest.mark.anyio
async def test_human_takeover_node_intercepts_dialog():
    """
    WI-085-001: Verify that human_takeover_node intercepts browser dialogs.
    """
    state = {
        "run_id": "test-run-085-dialog",
        "jira_ticket": {
            "ticket_id": "VC2-123",
            "acceptance_criteria_steps": ["Step 1"]
        },
        "ac_step_index": 0,
        "execution_mode": "interactive"
    }
    
    mock_manager = MagicMock()
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.on = MagicMock()
    mock_manager.page = mock_page
    
    # Capture the dialog handler
    dialog_handler = None
    def mock_on(event, handler):
        nonlocal dialog_handler
        if event == "dialog":
            dialog_handler = handler
    mock_page.on.side_effect = mock_on
    
    mock_cdp = AsyncMock()
    mock_cdp.on = MagicMock()
    mock_manager.get_cdp_session = AsyncMock(return_value=mock_cdp)
    
    mock_dialog_broadcast = AsyncMock()
    
    with patch("backend.engine.human_takeover.get_manager", return_value=mock_manager), \
         patch("backend.engine.human_takeover._WS_BROADCAST_FN", AsyncMock()), \
         patch("backend.engine.human_takeover._WS_DIALOG_FN", mock_dialog_broadcast), \
         patch("backend.engine.human_takeover.register_takeover") as mock_reg, \
         patch("backend.engine.human_takeover._inject_click_capture_listener", AsyncMock()), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        
        mock_reg.return_value = AsyncMock()
        
        await human_takeover_node(state)
        
        assert dialog_handler is not None
        
        # Simulate a dialog
        mock_dialog = MagicMock()
        mock_dialog.message = "Are you sure?"
        mock_dialog.type = "confirm"
        mock_dialog.default_value = ""
        
        await dialog_handler(mock_dialog)
        
        mock_dialog_broadcast.assert_called_once_with(
            run_id="test-run-085-dialog",
            message="Are you sure?",
            dialog_type="confirm",
            default_value=""
        )
        
        from backend.engine.human_takeover import _pending_dialogs
        assert _pending_dialogs["test-run-085-dialog"] == mock_dialog
