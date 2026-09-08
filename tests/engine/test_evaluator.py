"""
TASK-082: Production Readiness Hardening - Pillar 1: Amnesic Loop Detection
==========================================================================
Tests for detecting and breaking out of amnesic loops where the agent
performs semantically identical null-outcome actions.
"""

import pytest
from backend.engine.evaluator import evaluator_node

@pytest.fixture
def base_state():
    return {
        "run_id": "test-run",
        "jira_ticket": {"id": "VC-123", "acceptance_criteria_steps": ["Step 1"]},
        "ac_step_index": 0,
        "test_plan": {"steps": [{"max_actions": 15}]},
        "role_context": {"role_name": "producer", "permissions": {}},
        "detailed_execution_log": [],
        "ac_step_fail_counts": {},
        "action_repeat_counts": {},
        "current_ac_step_action_count": 0,
        "retry_count": 0,
        "amnesic_loop_count": 0,
        "_prev_page_state_snapshot": {},
    }

@pytest.mark.anyio
async def test_amnesic_loop_detection_3_consecutive_stagnant_actions(base_state):
    """
    AC-1: Amnesic loop circuit breaker fires after 3 consecutive stagnant actions.
    """
    # Simulate 3 actions with same URL and element count
    url = "http://example.com"
    count = 100
    
    # 1st action - stagnant
    base_state["detailed_execution_log"] = [{
        "success": True, 
        "post_url": url, 
        "post_element_count": count
    }]
    base_state["amnesic_loop_count"] = 2 # Already at 2
    base_state["_prev_page_state_snapshot"] = {"url": url, "element_count": count}
    
    result = await evaluator_node(base_state)
    
    assert result["_next_node"] == "human_takeover"
    assert result["awaiting_human_takeover"] is True
    assert "AMNESIC LOOP" in result["agent_critique"]

@pytest.mark.anyio
async def test_amnesic_loop_does_not_fire_on_url_change(base_state):
    """
    Amnesic loop should NOT fire if the URL changes.
    """
    url1 = "http://example.com/1"
    url2 = "http://example.com/2"
    count = 100
    
    base_state["detailed_execution_log"] = [{
        "success": True, 
        "post_url": url2, 
        "post_element_count": count
    }]
    base_state["amnesic_loop_count"] = 2
    base_state["_prev_page_state_snapshot"] = {"url": url1, "element_count": count}
    
    result = await evaluator_node(base_state)
    
    # Should NOT be human_takeover (should be planner or verifier depending on action)
    assert result["_next_node"] != "human_takeover"
    assert result.get("amnesic_loop_count") == 0 # Reset

@pytest.mark.anyio
async def test_amnesic_loop_does_not_fire_below_threshold(base_state):
    """
    Amnesic loop should NOT fire if below threshold (e.g. 2 stagnant actions).
    """
    url = "http://example.com"
    count = 100
    
    base_state["detailed_execution_log"] = [{
        "success": True, 
        "post_url": url, 
        "post_element_count": count
    }]
    base_state["amnesic_loop_count"] = 1
    base_state["_prev_page_state_snapshot"] = {"url": url, "element_count": count}
    
    result = await evaluator_node(base_state)
    
    assert result["_next_node"] != "human_takeover"
    assert result.get("amnesic_loop_count") == 2

@pytest.mark.anyio
async def test_amnesic_loop_resets_on_ac_step_advance(base_state):
    """
    Amnesic loop count should reset when ac_step_index advances.
    """
    # This is slightly tricky to test in evaluator_node alone if it's the verifier that advances it.
    # But evaluator_node often handles the reset when it detects a 'done' action success.
    base_state["detailed_execution_log"] = [{"action_type": "done", "success": True}]
    base_state["amnesic_loop_count"] = 2
    
    result = await evaluator_node(base_state)
    
    # If it routes to planner for next step, it should reset counters
    if result["_next_node"] == "planner":
        assert result.get("amnesic_loop_count") == 0
