
import pytest
from unittest.mock import MagicMock, patch
from backend.engine.evaluator import evaluator_node
from backend.engine.state import VQAState, JiraTicketContext, ExecutionStep

@pytest.mark.asyncio
async def test_evaluator_defers_verification_for_sub_steps():
    """
    Test that evaluator routes back to planner if more sub_steps remain.
    """
    # 1. Setup state with a compound step
    state = {
        "run_id": "test-run",
        "jira_ticket": {
            "acceptance_criteria_steps": ["Compound Step"]
        },
        "ac_step_index": 0,
        "structured_step_index": 0,
        "current_sub_step_index": 0,
        "test_plan": {
            "steps": [
                {
                    "step_id": 1,
                    "goal": "Compound Step",
                    "sub_steps": ["Sub-step 1", "Sub-step 2"]
                }
            ]
        },
        "detailed_execution_log": [
            {
                "step_index": 0,
                "action_type": "click",
                "success": True
            }
        ],
        "planner_iteration": 1,
        "max_planner_iterations": 10,
        "ac_step_iteration_budget": 5,
        "ac_step_iterations_used": 1,
        "retry_count": 0
    }
    
    # 2. Call evaluator
    result = await evaluator_node(state)
    
    # 3. Assertions
    assert result["_next_node"] == "planner"
    assert result["current_sub_step_index"] == 1
    assert "Next sub-step: Sub-step 2" in result["agent_critique"]

@pytest.mark.asyncio
async def test_evaluator_routes_to_verifier_after_last_sub_step():
    """
    Test that evaluator routes to verifier when the final sub_step is reached.
    """
    # 1. Setup state at the LAST sub-step
    state = {
        "run_id": "test-run",
        "jira_ticket": {
            "acceptance_criteria_steps": ["Compound Step"]
        },
        "ac_step_index": 0,
        "structured_step_index": 0,
        "current_sub_step_index": 1, # Last sub-step (0-indexed, length 2)
        "test_plan": {
            "steps": [
                {
                    "step_id": 1,
                    "goal": "Compound Step",
                    "sub_steps": ["Sub-step 1", "Sub-step 2"]
                }
            ]
        },
        "detailed_execution_log": [
            {
                "step_index": 1,
                "action_type": "click",
                "success": True
            }
        ],
        "planner_iteration": 2,
        "max_planner_iterations": 10,
        "ac_step_iteration_budget": 5,
        "ac_step_iterations_used": 2,
        "retry_count": 0
    }
    
    # 2. Call evaluator
    result = await evaluator_node(state)
    
    # 3. Assertions
    assert result["_next_node"] == "verifier"
    # current_sub_step_index should NOT be in the result (stay at 1 until AC step advances)
    # or it should not be incremented further.
    assert result.get("current_sub_step_index") is None 
