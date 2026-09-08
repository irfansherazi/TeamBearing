
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
    test_plan: dict = None,
) -> VQAState:
    if ac_steps is None:
        ac_steps = ["Verify button is visible"]
    
    state = {
        "run_id": run_id,
        "jira_ticket": {"acceptance_criteria_steps": ac_steps, "id": "JIRA-123"},
        "ac_step_index": ac_index,
        "current_screenshot_b64": screenshot_b64,
        "dom_snapshot_before": dom_before,
        "test_plan": test_plan,
        "planned_action": {"action": "click", "name": "Submit"},
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "ac_steps_completed": [],
    }
    return state

@pytest.mark.anyio
async def test_step_verifier_captures_fresh_screenshot():
    """AC-2: Verifier must always fetch and use a fresh post-action screenshot."""
    state = _make_mock_state()
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier._harvest_dom_snapshot", new_callable=AsyncMock) as mock_harvest, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "fresh-screenshot"
        mock_harvest.return_value = "<page>New State</page>" # Delta!
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: I see the button")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        # Verify fresh capture was called
        mock_capture.assert_called_once()
        # Verify result used fresh screenshot (if we check the llm call args)
        assert mock_llm.ainvoke.called
        human_msg = mock_llm.ainvoke.call_args[0][0][1] # Second message, HumanMessage
        assert human_msg.content[0]["source"]["data"] == "fresh-screenshot"

@pytest.mark.anyio
async def test_step_verifier_returns_not_yet_on_zero_delta():
    """AC-3: Zero DOM delta should NOT short-circuit — verification proceeds.

    Fix 2: Stagnant-UI no longer blocks verification. The verifier must proceed
    to LLM evaluation even when DOM/URL/count signals show no change, because
    CSS animations (PrimeNG slide-ins) don't trigger DOM delta.
    """
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(dom_before=dom_content)
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier._harvest_dom_snapshot", new_callable=AsyncMock) as mock_harvest, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "some-screenshot"
        mock_harvest.return_value = dom_content  # NO DELTA
        
        # LLM should be called now (Fix 2: no short-circuit)
        mock_parse.return_value = ("not_yet", "Page unchanged", 60)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="NOT_YET: Page unchanged")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        # Key assertion: LLM IS called even with zero delta
        # (previously assert_not_called — that was the bug)
        mock_get_llm.assert_called_once()

@pytest.mark.anyio
async def test_step_verifier_bypasses_delta_check_for_wait_actions():
    """Wait actions aren't expected to change DOM, so they should bypass the delta check."""
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(dom_before=dom_content)
    state["planned_action"] = {"action": "wait", "value": 1000}
    
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
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: The wait action is complete and the page state is stable. I see all expected elements present.")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        # Should NOT return not_yet immediately, should call LLM
        assert result["_verifier_verdict"] == "satisfied"
        mock_get_llm.assert_called_once()
