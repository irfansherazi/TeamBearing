"""
tests/test_task_103_max_actions.py
==================================
Unit and integration tests for TASK-103/FEAT-104.

Verifies that:
1. StructuredACStep.max_actions defaults to 15 (raised from 8).
2. evaluator_node fallbacks to 20 when no structured plan exists.
"""

import pytest
from backend.engine.schemas import StructuredACStep, TestPlan
from backend.engine.evaluator import evaluator_node

class TestMaxActionsDefaults:
    """Verify max_actions defaults across schemas and evaluator."""

    def test_structured_ac_step_default_max_actions(self):
        """StructuredACStep should default max_actions to 15 (FEAT-104)."""
        step = StructuredACStep(
            step_id=1,
            goal="Locate a spot with a raw script in the Files column",
            step_type="CLICK",
            target_component="production_orders_table",
        )
        assert step.max_actions == 15

    def test_structured_ac_step_custom_max_actions(self):
        """StructuredACStep should accept custom max_actions value."""
        step = StructuredACStep(
            step_id=1,
            goal="Locate a spot with a raw script in the Files column",
            step_type="CLICK",
            target_component="production_orders_table",
            max_actions=25,
        )
        assert step.max_actions == 25


@pytest.fixture
def base_evaluator_state():
    return {
        "run_id": "test-task-103",
        "jira_ticket": {"id": "QA-100", "acceptance_criteria_steps": ["Step 1"]},
        "ac_step_index": 0,
        "role_context": {"role_name": "producer", "permissions": {}},
        "detailed_execution_log": [{"success": True, "action_type": "click"}],
        "ac_step_fail_counts": {},
        "action_repeat_counts": {},
        "current_ac_step_action_count": 0,
        "retry_count": 0,
        "amnesic_loop_count": 0,
        "_prev_page_state_snapshot": {},
    }


class TestEvaluatorFallbackAcCap:
    """Verify evaluator_node fallback logic for _ac_cap."""

    @pytest.mark.anyio
    async def test_ac_cap_below_fallback_threshold(self, base_evaluator_state):
        """At 19 actions (below fallback cap of 20), it should not trigger human takeover."""
        base_evaluator_state["current_ac_step_action_count"] = 19
        result = await evaluator_node(base_evaluator_state)
        
        # Should not trigger takeover circuit breaker
        assert result.get("_next_node") != "human_takeover"
        assert result.get("awaiting_human_takeover") is not True

    @pytest.mark.anyio
    async def test_ac_cap_reaches_fallback_threshold(self, base_evaluator_state):
        """At 20 actions (equal to fallback cap of 20), it should trigger human takeover."""
        base_evaluator_state["current_ac_step_action_count"] = 20
        result = await evaluator_node(base_evaluator_state)
        
        # Reaches fallback cap -> human takeover
        assert result.get("_next_node") == "human_takeover"
        assert result.get("awaiting_human_takeover") is True
        assert "too many actions" in result.get("agent_critique", "")

    @pytest.mark.anyio
    async def test_ac_cap_respects_custom_plan_max_actions(self, base_evaluator_state):
        """If a test plan is provided, the evaluator should respect its custom max_actions (e.g. 25)."""
        base_evaluator_state["test_plan"] = {
            "steps": [{"max_actions": 25}]
        }
        base_evaluator_state["current_ac_step_action_count"] = 24
        
        # 24 is below step cap of 25, should be fine
        result = await evaluator_node(base_evaluator_state)
        assert result.get("_next_node") != "human_takeover"
        
        # 25 reaches step cap of 25 -> human takeover
        base_evaluator_state["current_ac_step_action_count"] = 25
        result = await evaluator_node(base_evaluator_state)
        assert result.get("_next_node") == "human_takeover"
        assert result.get("awaiting_human_takeover") is True
