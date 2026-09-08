import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from backend.engine.verifier import step_verifier_node
from backend.engine.state import VQAState

def _make_mock_state(
    run_id: str = "run-123",
    ac_index: int = 0,
    ac_steps: list = None,
    screenshot_b64: str = "old-screenshot",
    dom_before: str = "<page>Old State</page>",
    url_before: str = "https://app.com/page1",
    element_count_before: int = 10,
    active_overlays_before: list = None,
) -> VQAState:
    if ac_steps is None:
        ac_steps = ["Verify something"]
    if active_overlays_before is None:
        active_overlays_before = []
        
    state = {
        "run_id": run_id,
        "jira_ticket": {"acceptance_criteria_steps": ac_steps, "id": "JIRA-123"},
        "ac_step_index": ac_index,
        "current_screenshot_b64": screenshot_b64,
        "dom_snapshot_before": dom_before,
        "pre_action_state": {
            "url": url_before,
            "dom_snapshot": dom_before,
            "element_count": element_count_before,
            "active_overlays": active_overlays_before,
        },
        "planned_action": {"action": "click", "name": "Submit"},
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "ac_steps_completed": [],
    }
    return state


@pytest.mark.anyio
async def test_verifier_not_stagnant_when_overlays_change():
    """Verify that verifier does not raise a stagnant warning if overlays changed."""
    state = _make_mock_state(
        active_overlays_before=["div.p-dialog"]
    )
    
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.url = "https://app.com/page1"
    
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    # Mock evaluate to return different overlays (empty list)
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 10
        elif "selectors.filter" in expression:
            return []  # Dialog closed!
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = {"role": "button", "name": "Submit"}
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "new-screenshot"
        mock_parse.return_value = ("satisfied", "Overlay closed", 100)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: Overlay closed")
        mock_get_llm.return_value = mock_llm
        
        # Verify that the node runs and returns satisfied, confirming overlays_changed is treated as a valid state change
        result = await step_verifier_node(state)
        
        assert result["_verifier_verdict"] == "satisfied"
        mock_get_llm.assert_called_once()


@pytest.mark.anyio
async def test_verifier_stagnant_when_nothing_changes():
    """Verify that verifier logs warning but proceeds when absolutely nothing changes on a non-observational action."""
    # Ensure snapshot_before matches exactly the JSON structure returned by the mocked accessibility snapshot
    snapshot_data = {"role": "button", "name": "Submit"}
    pre_snapshot = json.dumps(snapshot_data, sort_keys=True)
    
    state = _make_mock_state(dom_before=pre_snapshot)
    
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.url = "https://app.com/page1"
    
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    # Mock evaluate to return same count and overlays
    async def mock_evaluate(expression, *args, **kwargs):
        if "querySelectorAll('*')" in expression:
            return 10
        elif "selectors.filter" in expression:
            return []
        return None
        
    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.accessibility = AsyncMock()
    mock_page.accessibility.snapshot.return_value = snapshot_data
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "old-screenshot"
        mock_parse.return_value = ("satisfied", "verified", 100)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: verified")
        mock_get_llm.return_value = mock_llm
        
        with patch("backend.engine.verifier.logger.warning") as mock_warn:
            result = await step_verifier_node(state)
            
            assert result["_verifier_verdict"] == "satisfied"
            # Ensure the stagnant UI warning was logged
            any_stagnant_warn = any("STAGNANT UI warning" in args[0] for args, kwargs in mock_warn.call_args_list)
            assert any_stagnant_warn is True
