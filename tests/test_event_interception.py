from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from backend.engine.human_takeover import _human_action_sequence, _inject_click_capture_listener


def _make_mock_page():
    page = AsyncMock()
    # Playwright's page.on and page.remove_listener are synchronous
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    page.main_frame = MagicMock()
    page.is_closed = MagicMock(return_value=False)
    return page


@pytest.mark.anyio
async def test_on_human_action_callback():
    """Verify that the Python callback correctly stores action records."""
    run_id = "test-run-123"
    _human_action_sequence[run_id] = []

    mock_page = _make_mock_page()

    # Capture the callback passed to expose_function
    exposed_fn = None

    async def side_effect(name, fn):
        nonlocal exposed_fn
        if name == "__vqa_record_human_action__":
            exposed_fn = fn

    mock_page.expose_function.side_effect = side_effect

    await _inject_click_capture_listener(mock_page, run_id)

    assert exposed_fn is not None

    # Simulate a click event record from JS
    click_record = {
        "run_id": run_id,
        "event_type": "click",
        "tag": "button",
        "best_selector": "Submit",
        "strategy": "get_by_text",
        "timestamp": "2026-05-20T12:00:00Z",
    }

    await exposed_fn(click_record)

    assert len(_human_action_sequence[run_id]) == 1
    assert _human_action_sequence[run_id][0]["event_type"] == "click"
    assert _human_action_sequence[run_id][0]["best_selector"] == "Submit"


@pytest.mark.anyio
async def test_js_injection_content():
    """Verify the JS script contains expected event listeners (scroll, keyup, click, change)."""
    mock_page = _make_mock_page()
    run_id = "test-run-456"

    await _inject_click_capture_listener(mock_page, run_id)

    # Check if page.evaluate was called with the script
    # The second evaluate call contains the main script
    script_call = None
    for call in mock_page.evaluate.call_args_list:
        if "document.addEventListener" in str(call) or "window.addEventListener('scroll'" in str(call):
            script_call = call
            break

    assert script_call is not None
    script_text = script_call.args[0]

    assert "document.addEventListener('click'" in script_text
    assert "document.addEventListener('change'" in script_text
    assert "window.addEventListener('scroll'" in script_text
    assert "document.addEventListener('keyup'" in script_text


@pytest.mark.anyio
async def test_navigation_reinjection_registration():
    """Verify that a navigation listener is registered on the page."""
    mock_page = _make_mock_page()
    run_id = "test-run-789"

    await _inject_click_capture_listener(mock_page, run_id)

    # Verify page.on("framenavigated", ...) was called
    mock_page.on.assert_called_with("framenavigated", ANY)


@pytest.mark.anyio
async def test_cleanup_removes_listener():
    """Verify that _clear removes the navigation listener."""
    from backend.engine.human_takeover import _clear, _nav_listeners

    mock_page = _make_mock_page()
    run_id = "test-run-cleanup"

    await _inject_click_capture_listener(mock_page, run_id)
    assert run_id in _nav_listeners

    _clear(run_id)

    assert run_id not in _nav_listeners
    mock_page.remove_listener.assert_called_with("framenavigated", ANY)
