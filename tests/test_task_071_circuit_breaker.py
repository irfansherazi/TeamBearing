import pytest
from backend.engine.evaluator import evaluator_node
from backend.engine.state import make_initial_state

@pytest.mark.anyio
async def test_circuit_breaker_exempts_done_action():
    """
    TASK-071: Verify that the AC-LEVEL CIRCUIT BREAKER does NOT trip
    when the 10th action is a successful 'done' action.
    """
    state = make_initial_state(
        run_id="run-071-test",
        jira_ticket_id="VC-071",
        role="account_executive",
        target_url="https://test.vcreative.net",
        mode="interactive",
    )
    state["jira_ticket"] = {"acceptance_criteria_steps": ["Step 1: Login"]}
    state["ac_step_index"] = 0
    state["current_ac_step_action_count"] = 20  # Already at the cap (default _ac_cap=20)

    # Successful 'done' action
    state["planned_action"] = {"action": "done", "reasoning": "Finished login"}
    state["detailed_execution_log"] = [
        {
            "action_type": "done",
            "action_payload": state["planned_action"],
            "success": True,
            "step_index": 19
        }
    ]
    
    result = await evaluator_node(state)
    
    # Should NOT be human_takeover (circuit breaker)
    # It should route to 'verifier' (Case 2: done handler -> Unverified-done guard)
    assert result["_next_node"] == "verifier", f"Expected 'verifier', got '{result['_next_node']}'"
    assert "CIRCUIT BREAKER" not in result.get("agent_critique", "").upper()

@pytest.mark.anyio
async def test_circuit_breaker_trips_on_other_actions_at_cap():
    """
    Verify that the AC-LEVEL CIRCUIT BREAKER STILL trips for non-done actions
    at the cap.
    """
    state = make_initial_state(
        run_id="run-071-test",
        jira_ticket_id="VC-071",
        role="account_executive",
        target_url="https://test.vcreative.net",
        mode="interactive",
    )
    state["jira_ticket"] = {"acceptance_criteria_steps": ["Step 1: Login"]}
    state["ac_step_index"] = 0
    state["current_ac_step_action_count"] = 20  # At the cap (default _ac_cap=20)

    # Successful 'click' action (not finishing the step)
    state["planned_action"] = {"action": "click", "role": "button", "name": "Settings"}
    state["detailed_execution_log"] = [
        {
            "action_type": "click",
            "action_payload": state["planned_action"],
            "success": True,
            "step_index": 19
        }
    ]
    
    result = await evaluator_node(state)

    # Should trip the circuit breaker and fail the run
    assert result["_next_node"] == "reporter", f"Expected 'reporter', got '{result['_next_node']}'"
    assert result.get("failure_type") == "AGENT_STUCK"
    assert "consumed" in result.get("agent_critique", "").lower()

@pytest.mark.anyio
async def test_circuit_breaker_trips_on_failed_done_at_cap():
    """
    Verify that a FAILED 'done' action at the cap trips the circuit breaker.
    (If done failed, we are definitely stuck).
    """
    state = make_initial_state(
        run_id="run-071-test",
        jira_ticket_id="VC-071",
        role="account_executive",
        target_url="https://test.vcreative.net",
        mode="interactive",
    )
    state["jira_ticket"] = {"acceptance_criteria_steps": ["Step 1: Login"]}
    state["ac_step_index"] = 0
    state["current_ac_step_action_count"] = 20  # At the cap (default _ac_cap=20)

    # FAILED 'done' action
    state["planned_action"] = {"action": "done", "reasoning": "Finished login"}
    state["detailed_execution_log"] = [
        {
            "action_type": "done",
            "action_payload": state["planned_action"],
            "success": False,
            "error_message": "TIMEOUT",
            "step_index": 19
        }
    ]

    result = await evaluator_node(state)

    # Should trip the circuit breaker and fail the run
    assert result["_next_node"] == "reporter", f"Expected 'reporter', got '{result['_next_node']}'"
    assert result.get("failure_type") == "AGENT_STUCK"
