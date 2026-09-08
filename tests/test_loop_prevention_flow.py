import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.engine.verifier import step_verifier_node
from backend.engine.evaluator import evaluator_node

@pytest.mark.asyncio
async def test_loop_prevention_to_evaluator_flow():
    """Verify the full flow from verifier skip to evaluator logging."""
    state = {
        "run_id": "flow-test",
        "jira_ticket": {"acceptance_criteria_steps": ["Step 1", "Step 2"]},
        "ac_step_index": 0,
        "test_plan": {
            "steps": [
                {"step_id": 1, "goal": "Step 1", "verification": []},
                {"step_id": 2, "goal": "Step 2", "verification": []}
            ]
        },
        "current_screenshot_b64": "fake",
        "planned_action": {"action": "wait"},
        "detailed_execution_log": [{"step_index": 1, "action_type": "wait", "success": True}],
        "verifier_not_yet_count": 2,
        "verifier_total_not_yet_count": 2,
        "bug_log": [],
        "ac_steps_skipped": []
    }
    
    # 1. Verifier Phase
    with patch("backend.engine.verifier.get_manager") as mock_get_manager, \
         patch("backend.engine.verifier._run_programmatic_verifications", new_callable=AsyncMock) as mock_prog, \
         patch("backend.engine.verifier.goal_satisfiable_check", new_callable=AsyncMock) as mock_check:
        
        mock_page = AsyncMock()
        mock_get_manager.return_value.page = mock_page
        mock_prog.return_value = ("not_yet", "still waiting", [])
        mock_check.return_value = False # Not satisfiable
        
        verifier_update = await step_verifier_node(state)
        
        assert verifier_update["_verifier_verdict"] == "skipped"
        assert verifier_update["ac_step_index"] == 1
        
        # Merge update for evaluator
        state.update(verifier_update)
        
    # 2. Evaluator Phase
    evaluator_update = await evaluator_node(state)
    
    assert evaluator_update["_next_node"] == "planner"
    assert evaluator_update["ac_step_index"] == 1
    assert len(evaluator_update["ac_steps_skipped"]) == 1
    assert evaluator_update["ac_steps_skipped"][0] == 0
    assert any(bug["type"] == "COVERAGE_GAP" for bug in evaluator_update["bug_log"])
    assert any(bug["reason"] == "UNSATISFIABLE_GOAL" for bug in evaluator_update["bug_log"])
