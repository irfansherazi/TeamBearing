
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
    url_before: str = "https://app.com/page1",
    element_count_before: int = 10,
) -> VQAState:
    if ac_steps is None:
        ac_steps = ["Verify something"]
    
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
        },
        "planned_action": {"action": "click", "name": "Submit"},
        "verifier_not_yet_count": 0,
        "verifier_total_not_yet_count": 0,
        "ac_steps_completed": [],
    }
    return state

@pytest.mark.anyio
async def test_step_verifier_not_stagnant_if_url_changed():
    """AC-VERIFY-1: Verifier should NOT flag stagnant UI if URL changed."""
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(
        dom_before=dom_content, 
        url_before="https://app.com/page1"
    )
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier.cv_fallback_state_change_check", new_callable=AsyncMock) as mock_check, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "some-screenshot"
        # Simulate URL change detected by cv_fallback_state_change_check
        mock_check.return_value = {
            "has_changed": True,
            "url_changed": True,
            "snapshot_changed": False,
            "element_count_changed": False,
            "visual_delta": 0.0,
            "snapshot_after": dom_content
        }
        
        mock_parse.return_value = ("satisfied", "URL changed", 100)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: URL changed")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        assert result["_verifier_verdict"] == "satisfied"
        mock_get_llm.assert_called_once()

@pytest.mark.anyio
async def test_step_verifier_not_stagnant_if_element_count_changed():
    """AC-VERIFY-1: Verifier should NOT flag stagnant UI if element count changed."""
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(
        dom_before=dom_content, 
        element_count_before=10
    )
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier.cv_fallback_state_change_check", new_callable=AsyncMock) as mock_check, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        mock_capture.return_value = "some-screenshot"
        # Simulate element count change detected
        mock_check.return_value = {
            "has_changed": True,
            "url_changed": False,
            "snapshot_changed": False,
            "element_count_changed": True,
            "visual_delta": 0.0,
            "snapshot_after": dom_content
        }
        
        mock_parse.return_value = ("satisfied", "Elements changed", 100)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="SATISFIED: Elements changed")
        mock_get_llm.return_value = mock_llm
        
        result = await step_verifier_node(state)
        
        assert result["_verifier_verdict"] == "satisfied"
        mock_get_llm.assert_called_once()

@pytest.mark.anyio
async def test_step_verifier_stagnant_if_nothing_changed():
    """AC-VERIFY-1: Stagnant UI should NOT short-circuit — verification proceeds.

    Fix 2: Stagnant-UI was previously short-circuiting and returning NOT_YET
    without running programmatic or LLM checks. This violated the GEMINI.md rule:
    "NEVER use visual delta as the sole success signal." CSS slide-in animations
    don't trigger DOM delta, so the verifier must always proceed to actual checks.
    """
    dom_content = "<page>Same State</page>"
    state = _make_mock_state(dom_before=dom_content)

    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page

    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture, \
         patch("backend.engine.verifier.cv_fallback_state_change_check", new_callable=AsyncMock) as mock_check, \
         patch("backend.engine.verifier._parse_verdict") as mock_parse, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:

        mock_capture.return_value = "some-screenshot"
        # Simulate NO change detected — stagnant-UI condition
        mock_check.return_value = {
            "has_changed": False,
            "url_changed": False,
            "snapshot_changed": False,
            "element_count_changed": False,
            "visual_delta": 0.0,
            "snapshot_after": dom_content
        }

        # LLM should now be called (Fix 2: no short-circuit)
        mock_parse.return_value = ("not_yet", "Page has not changed", 60)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="NOT_YET: Page has not changed")
        mock_get_llm.return_value = mock_llm

        result = await step_verifier_node(state)

        # Key assertion: LLM IS called even with stagnant UI
        # (previously it was assert_not_called — that was the bug)
        mock_get_llm.assert_called_once()

