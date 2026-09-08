"""
FEAT-031: Stabilize vQA list sorting — Circuit Breaker Unit Tests
=================================================================
Tests for the loop-breaking circuit breaker in the evaluator node.
This circuit breaker detects repeated failures on sort-related actions
and escalates to human takeover before hitting Python recursion limits.

Coverage:
  - AC-VERIFY-1: Circuit breaker prevents infinite loops on sort operations
"""

import pytest

from backend.engine.evaluator import evaluator_node
from backend.engine.state import VQAState


@pytest.fixture
def base_state() -> VQAState:
    """Provides a basic VQAState for testing evaluator_node."""
    return {
        "run_id": "test-run",
        "jira_ticket": {"id": "VC-123", "acceptance_criteria_steps": ["Step 1: Sort by Client"]},
        "ac_step_index": 0,
        "test_plan": {"steps": [{"max_actions": 15}]},
        "role_context": {"role_name": "producer", "permissions": {}},
        "detailed_execution_log": [],
        "ac_step_fail_counts": {},
        "action_repeat_counts": {},
        "current_ac_step_action_count": 0,
        "retry_count": 0,
    }


@pytest.mark.anyio
async def test_circuit_breaker_tracks_sort_action_failures(base_state):
    """
    Test that a failed sort action increments the sort-specific repeat count.
    """
    base_state["planned_action"] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Client",
    }
    base_state["detailed_execution_log"] = [
        {
            "action_type": "click",
            "action_payload": base_state["planned_action"],
            "success": False,
            "error_message": "TIMEOUT (element not found)",
        }
    ]

    # Initially empty
    assert not base_state.get("action_repeat_counts")

    result = await evaluator_node(base_state)

    # Should route to planner for retry and increment repeat count
    assert result["_next_node"] == "planner"
    assert "action_repeat_counts" in result

    # Check that a sort action failure was tracked
    # We expect a key like "sort_action_failure" or the locator key to have count = 1
    assert any(count == 1 for count in result["action_repeat_counts"].values()), (
        "Expected action_repeat_counts to track the failed sort action"
    )


@pytest.mark.anyio
async def test_circuit_breaker_triggers_on_threshold(base_state):
    """
    AC-VERIFY-1: Test that the circuit breaker trips after 5 repeated sort failures
    and escalates to human_takeover.
    """
    base_state["planned_action"] = {
        "action": "click",
        "strategy": "get_by_text",
        "name": "Client",  # A known sort option name
    }
    base_state["detailed_execution_log"] = [
        {
            "action_type": "click",
            "action_payload": base_state["planned_action"],
            "success": False,
            "error_message": "STRICT_MODE (multiple elements)",
        }
    ]
    # Simulate 5 prior failures of sort actions
    base_state["action_repeat_counts"] = {"sort_action_failure": 5}
    # Set a lower threshold for standard failures so it doesn't trigger generic hits
    base_state["ac_step_action_fail_count"] = 2

    result = await evaluator_node(base_state)

    # Circuit breaker should route to human_takeover
    assert result["_next_node"] == "human_takeover"
    assert result.get("awaiting_human_takeover") is True
    assert (
        "CIRCUIT BREAKER" in result.get("agent_critique", "").upper()
        or "REPEATED" in result.get("agent_critique", "").upper()
    )


@pytest.mark.anyio
async def test_circuit_breaker_error_logging(base_state):
    """
    Test that the circuit breaker critique clearly logs that it was a sort loop.
    """
    base_state["planned_action"] = {
        "action": "click",
        "strategy": "get_by_role",
        "name": "Date Sort",
    }
    base_state["detailed_execution_log"] = [
        {
            "action_type": "click",
            "success": False,
            "error_message": "TIMEOUT (element not found)",
        }
    ]
    base_state["action_repeat_counts"] = {"sort_action_failure": 5}
    base_state["ac_step_action_fail_count"] = 2

    result = await evaluator_node(base_state)

    critique = result.get("agent_critique", "").lower()
    assert "sort" in critique or "repeated" in critique
    assert "human" in critique


@pytest.mark.anyio
async def test_circuit_breaker_counter_reset_on_step_advance(base_state):
    """
    Test that the action_repeat_counts reset when an AC step advances.
    """
    base_state["planned_action"] = {"action": "done"}
    base_state["detailed_execution_log"] = [
        {
            "action_type": "done",
            "success": True,
        }
    ]
    # Simulate existing repeat counts
    base_state["action_repeat_counts"] = {"sort_action_failure": 3}

    result = await evaluator_node(base_state)

    # When AC step advances, the circuit breaker counter should clear
    # Note: If it routes to verifier, the verifier will handle step advance eventually.
    # But if done passes straight to planner for next step:
    if result["_next_node"] == "planner":
        assert result.get("action_repeat_counts") == {}
    elif result["_next_node"] == "verifier":
        # Evaluator keeps it until verifier returns true
        pass
    else:
        # reporter or setup_role
        assert result.get("action_repeat_counts") == {}
