import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.browser.context import BrowserManager

@pytest.mark.anyio
async def test_get_cdp_session_success():
    """
    WI-085-001: Ensure BrowserManager can create and return a CDP session for its active page.
    """
    bm = BrowserManager(run_id="test-run-085")
    bm.page = MagicMock()
    bm.page.context = AsyncMock()
    
    # Mock new_cdp_session to return a dummy CDP session
    mock_session = AsyncMock()
    bm.page.context.new_cdp_session.return_value = mock_session
    
    session = await bm.get_cdp_session()
    
    assert session == mock_session
    bm.page.context.new_cdp_session.assert_called_once_with(bm.page)

@pytest.mark.anyio
async def test_get_cdp_session_no_page_raises():
    """
    Ensure get_cdp_session fails gracefully if no page is active.
    """
    bm = BrowserManager(run_id="test-run-085")
    bm.page = None
    
    with pytest.raises(RuntimeError, match="Browser not started or page closed"):
        await bm.get_cdp_session()
