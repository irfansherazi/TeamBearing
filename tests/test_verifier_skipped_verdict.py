import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.engine.verifier import step_verifier_node

@pytest.mark.asyncio
async def test_step_verifier_loop_prevention_skips():
    """Verify that verifier emits 'skipped' after enough NOT_YETs and goal_satisfiable_check fails."""
    state = {
        "run_id": "test-run",
        "jira_ticket": {"acceptance_criteria_steps": ["Step 1"]},
        "ac_step_index": 0,
        "test_plan": {
            "steps": [
                {
                    "step_id": 1,
                    "goal": "Verify invisible button",
                    "verification": [{"type": "element_visible", "selector_hint": "#invisible"}]
                }
            ]
        },
        "current_screenshot_b64": "fake-b64",
        "planned_action": {"action": "wait"},
        "verifier_not_yet_count": 2, # Next one will be the 3rd
        "verifier_total_not_yet_count": 2
    }
    
    with patch("backend.engine.verifier.get_manager") as mock_get_manager, \
         patch("backend.engine.verifier._run_programmatic_verifications", new_callable=AsyncMock) as mock_prog:
        
        mock_page = AsyncMock()
        mock_get_manager.return_value.page = mock_page
        # Programmatic fails with not_yet
        mock_prog.return_value = ("not_yet", "element not found", [])
        
        # We need to mock goal_satisfiable_check to return False (not satisfiable)
        with patch("backend.engine.verifier.goal_satisfiable_check", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = False
            
            result = await step_verifier_node(state)
            
            assert result["_verifier_verdict"] == "skipped"
            assert result["_next_node"] == "evaluator"
            assert result["ac_step_index"] == 1 # Advanced
