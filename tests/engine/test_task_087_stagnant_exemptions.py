
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.verifier import step_verifier_node
from backend.engine.state import VQAState

def _make_mock_state(
    run_id: str = "run-123",
    ac_index: int = 0,
    ac_steps: list = None,
    screenshot_b64: str = "old-screenshot",
    dom_before: str = "<page>Old State</page>",
    action_type: str = "click",
) -> VQAState:
    if ac_steps is None:
        ac_steps = ["Verify button is visible"]
    
    state = {
        "run_id": run_id,
        "jira_ticket": {"acceptance_criteria_steps": ac_steps, "id": "JIRA-123"},
        "ac_step_index": ac_index,
        "current_screenshot_b64": screenshot_b64,
        "dom_snapshot_before": dom_before,
        "planned_action": {"action": action_type, "name": "Submit"},
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "ac_steps_completed": [],
    }
    return state

@pytest.mark.anyio
@pytest.mark.parametrize("exempt_action", ["scroll", "press_key", "coordinate_action"])
async def test_step_verifier_bypasses_delta_check_for_exempt_actions(exempt_action):
    """TASK-087: Exempt actions shouldn't trigger stagnant UI check even with zero DOM delta."""
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(dom_before=dom_content, action_type=exempt_action)
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier._harvest_dom_snapshot", new_callable=AsyncMock) as mock_harvest, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "some-screenshot"
        mock_harvest.return_value = dom_content # NO DELTA
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: Action complete. I see the result clearly in the screenshot and the page is in the expected state after the action was performed.")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        # Should NOT return not_yet immediately, should call LLM
        assert result["_verifier_verdict"] == "satisfied"
        mock_get_llm.assert_called_once()
