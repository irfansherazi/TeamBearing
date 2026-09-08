import pytest
from unittest.mock import AsyncMock, MagicMock
import json
from backend.engine.ui_delta import capture_pre_action_state, compute_ui_delta

def _make_mock_page(*, is_closed: bool = False, url: str = "https://two-test.vcreative.net/dashboard"):
    page = AsyncMock()
    # is_closed() is synchronous, must use MagicMock
    page.is_closed = MagicMock(return_value=is_closed)
    page.url = url
    return page

@pytest.mark.anyio
async def test_capture_pre_action_state_all_signals():
    """Verify that capture_pre_action_state successfully queries URL, count, snapshot, and overlays."""
    mock_page = _make_mock_page(url="https://two-test.vcreative.net/dashboard")
    
    # Mock evaluate to return element count for document query and active overlays list
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 42
        elif "selectors.filter" in expression:
            return ["div.p-dialog", "div.p-toast"]
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    
    # Mock accessibility snapshot
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = {"role": "button", "name": "Submit"}
    
    state = await capture_pre_action_state(mock_page)
    
    assert state["url"] == "https://two-test.vcreative.net/dashboard"
    assert state["element_count"] == 42
    assert state["active_overlays"] == ["div.p-dialog", "div.p-toast"]
    assert "role" in state["aria_snapshot"]
    assert "button" in state["aria_snapshot"]


@pytest.mark.anyio
async def test_compute_ui_delta_no_changes():
    """Verify compute_ui_delta returns has_changed=False when all 4 signals are identical."""
    mock_page = _make_mock_page(url="https://two-test.vcreative.net/dashboard")
    
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 42
        elif "selectors.filter" in expression:
            return ["div.p-dialog"]
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = {"role": "button", "name": "Submit"}
    
    pre_state = {
        "url": "https://two-test.vcreative.net/dashboard",
        "element_count": 42,
        "aria_snapshot": json.dumps({"role": "button", "name": "Submit"}, sort_keys=True),
        "active_overlays": ["div.p-dialog"]
    }
    
    delta = await compute_ui_delta(mock_page, pre_state)
    
    assert delta["has_changed"] is False
    assert delta["url_changed"] is False
    assert delta["element_count_changed"] is False
    assert delta["snapshot_changed"] is False
    assert delta["overlays_changed"] is False


@pytest.mark.anyio
async def test_compute_ui_delta_url_changed():
    """Verify compute_ui_delta detects URL change."""
    mock_page = _make_mock_page(url="https://two-test.vcreative.net/new-page")
    
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 42
        elif "selectors.filter" in expression:
            return []
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = {"role": "button", "name": "Submit"}
    
    pre_state = {
        "url": "https://two-test.vcreative.net/dashboard",
        "element_count": 42,
        "aria_snapshot": json.dumps({"role": "button", "name": "Submit"}, sort_keys=True),
        "active_overlays": []
    }
    
    delta = await compute_ui_delta(mock_page, pre_state)
    
    assert delta["has_changed"] is True
    assert delta["url_changed"] is True
    assert delta["element_count_changed"] is False


@pytest.mark.anyio
async def test_compute_ui_delta_overlays_changed():
    """Verify compute_ui_delta detects active overlay markers change."""
    mock_page = _make_mock_page(url="https://two-test.vcreative.net/dashboard")
    
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 42
        elif "selectors.filter" in expression:
            # Toast appears now
            return ["div.p-toast"]
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = {"role": "button", "name": "Submit"}
    
    pre_state = {
        "url": "https://two-test.vcreative.net/dashboard",
        "element_count": 42,
        "aria_snapshot": json.dumps({"role": "button", "name": "Submit"}, sort_keys=True),
        "active_overlays": []
    }
    
    delta = await compute_ui_delta(mock_page, pre_state)
    
    assert delta["has_changed"] is True
    assert delta["overlays_changed"] is True
    assert delta["url_changed"] is False
    assert delta["element_count_changed"] is False
