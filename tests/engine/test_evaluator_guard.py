
import pytest
from unittest.mock import MagicMock
from backend.engine.evaluator import evaluator_node
from backend.engine.state import VQAState


def _done_spin_state(consecutive_done_count: int) -> dict:
    """Build a minimal state where the planner has emitted `done` N times in a
    row on AC step 0, the verifier has rejected at least once, and the step is
    not in ac_steps_completed. Preconditions for the done-spinning guard.
    """
    log = [
        {"ac_step_index": 0, "action_type": "done", "success": True, "step_index": i}
        for i in range(consecutive_done_count)
    ]
    return {
        "run_id": "run-spin",
        "detailed_execution_log": log,
        "jira_ticket": {"acceptance_criteria_steps": ["Log in to vPromotions"]},
        "ac_step_index": 0,
        "planned_action": {"action": "done"},
        "planner_iteration": consecutive_done_count,
        "max_planner_iterations": 500,
        "retry_count": 0,
        "ac_step_iteration_budget": 20,
        "ac_step_iterations_used": consecutive_done_count,
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "vision_mode_fail_count": 0,
        "verifier_total_not_yet_count": 2,  # verifier has rejected
        "ac_steps_completed": [],           # step unverified
        "current_ac_step_action_count": consecutive_done_count,
    }


@pytest.mark.asyncio
async def test_done_spin_trip_1_routes_to_planner_with_warning_1():
    """3 consecutive dones + prior verifier rejection → planner critique 1/2."""
    result = await evaluator_node(_done_spin_state(3))
    assert result["_next_node"] == "planner"
    assert "warning 1/2" in result["agent_critique"]
    assert "done-spinning" in result["last_error"]


@pytest.mark.asyncio
async def test_done_spin_trip_2_routes_to_planner_with_warning_2():
    """4 consecutive dones → planner critique 2/2 (still recoverable)."""
    result = await evaluator_node(_done_spin_state(4))
    assert result["_next_node"] == "planner"
    assert "warning 2/2" in result["agent_critique"]


@pytest.mark.asyncio
async def test_done_spin_trip_3_hard_fails_to_reporter_with_agent_stuck():
    """5 consecutive dones → hard-fail: reporter + failure_type=AGENT_STUCK.

    Regression guard for QA-359: without escalation, the flat guard looped to
    max_planner_iterations because 'done' is exempt from the AC-level circuit
    breaker and the guard's return dict does not persist ac_step_iterations_used.
    """
    result = await evaluator_node(_done_spin_state(5))
    assert result["_next_node"] == "reporter"
    assert result["failure_type"] == "AGENT_STUCK"
    assert "done-spinning escalated" in result["last_error"]


@pytest.mark.asyncio
async def test_done_spin_guard_does_not_fire_without_verifier_rejection():
    """If verifier never rejected, the done-spinning guard is dormant — a
    normal 'done' on an unverified step must still route to verifier (Bug D
    guard), never to reporter.
    """
    state = _done_spin_state(5)
    state["verifier_total_not_yet_count"] = 0  # no verifier rejections
    result = await evaluator_node(state)
    assert result["_next_node"] != "reporter" or result.get("failure_type") != "AGENT_STUCK"


@pytest.mark.asyncio
async def test_done_spin_guard_does_not_fire_when_streak_broken():
    """A non-done action in the streak breaks the counter — guard stays dormant."""
    state = _done_spin_state(5)
    # Splice a click between the 3rd and 4th done — the reverse-scan sees only
    # 2 recent dones (< 3) and the guard should not fire.
    state["detailed_execution_log"].insert(
        3, {"ac_step_index": 0, "action_type": "click", "success": True, "step_index": 99}
    )
    result = await evaluator_node(state)
    assert not (
        result["_next_node"] == "reporter"
        and result.get("failure_type") == "AGENT_STUCK"
    )

@pytest.mark.asyncio
async def test_evaluator_blocks_wait_only_success():
    """
    AC-1: If 'wait' is the only action taken for an AC step, 
    evaluator should route to planner, not verifier.
    """
    # Mock state
    state = {
        "run_id": "run-123",
        "detailed_execution_log": [
            {
                "ac_step_index": 0,
                "action_type": "wait",
                "success": True,
                "step_index": 0
            }
        ],
        "jira_ticket": {
            "acceptance_criteria_steps": ["Step 1", "Step 2"]
        },
        "ac_step_index": 0,
        "planned_action": {"action": "wait", "value": 1000},
        "planner_iteration": 1,
        "max_planner_iterations": 50,
        "retry_count": 0,
        "ac_step_iteration_budget": 10,
        "ac_step_iterations_used": 0,
    }
    
    # Run evaluator
    result = await evaluator_node(state)
    
    # Assert routing to planner
    assert result["_next_node"] == "planner"
    assert "You successfully performed a 'wait'" in result["agent_critique"]
    assert "MUST perform a real action" in result["agent_critique"]

@pytest.mark.asyncio
async def test_evaluator_allows_wait_if_other_actions_exist():
    """
    If a real action was already taken, a subsequent 'wait' should 
    still route to verifier.
    """
    # Mock state
    state = {
        "run_id": "run-123",
        "detailed_execution_log": [
            {
                "ac_step_index": 0,
                "action_type": "click",
                "success": True,
                "step_index": 0
            },
            {
                "ac_step_index": 0,
                "action_type": "wait",
                "success": True,
                "step_index": 1
            }
        ],
        "jira_ticket": {
            "acceptance_criteria_steps": ["Step 1", "Step 2"]
        },
        "ac_step_index": 0,
        "planned_action": {"action": "wait", "value": 1000},
        "planner_iteration": 2,
        "max_planner_iterations": 50,
        "retry_count": 0,
        "ac_step_iteration_budget": 10,
        "ac_step_iterations_used": 1,
    }
    
    # Run evaluator
    result = await evaluator_node(state)
    
    # Assert routing to verifier
    assert result["_next_node"] == "verifier"


@pytest.mark.asyncio
async def test_evaluator_handles_none_planned_name_on_failure():
    """
    Ensure the evaluator node doesn't raise an AttributeError if planned_action['name'] is None
    and the action fails.
    """
    state = {
        "run_id": "run-123",
        "detailed_execution_log": [
            {
                "ac_step_index": 0,
                "action_type": "click",
                "success": False,
                "error_message": "click failed: element not found",
                "step_index": 0
            }
        ],
        "jira_ticket": {
            "acceptance_criteria_steps": ["Step 1"]
        },
        "ac_index": 0,
        "ac_step_index": 0,
        "planned_action": {
            "action": "click",
            "strategy": "coordinate_action",
            "name": None,
            "mark_id": 1137
        },
        "planner_iteration": 1,
        "max_planner_iterations": 50,
        "retry_count": 0,
        "ac_step_iteration_budget": 10,
        "ac_step_iterations_used": 0,
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "vision_mode_fail_count": 0,
        "vision_mode": "som_coordinates",
    }
    
    # This should run without throwing an AttributeError
    result = await evaluator_node(state)
    
    assert result is not None
