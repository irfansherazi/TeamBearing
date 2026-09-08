"""
TASK-006: HITL Threshold Tuning — Unit Tests
=============================================

Tests for failure-type aware HITL thresholds:
  - General threshold (default 4)
  - Intercepted threshold (default 2)
  - Strict Mode threshold (default 3)

Run: .venv/bin/python -m pytest backend/engine/test_hitl_thresholds.py -v
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.engine.evaluator import evaluator_node
from backend.engine.test_evaluator_hardening import _make_state


def _run_async(coro):
    return asyncio.run(coro)


def _make_failed_step(error_msg: str):
    return {
        "step_index": 5,
        "ac_step_index": 1,
        "timestamp": "2026-05-12T00:00:00Z",
        "action_type": "click",
        "action_payload": {"action": "click", "strategy": "get_by_text", "name": "Target"},
        "locator_strategy": "get_by_text",
        "locator_value": "get_by_text('Target')",
        "success": False,
        "error_message": error_msg,
        "llm_reasoning": "test",
    }


def test_hitl_general_threshold_escalates_at_4():
    """TIMEOUT should escalate at 4 failures (default)."""
    # Note: Must be in vision_mode to bypass the 2-failure vision escalation
    # Note: recovery_attempted=True to bypass the recovery router
    state = _make_state(
        ac_step_action_fail_count=3,  # Next will be 4
        ac_step_index=1,
        vision_mode="som_coordinates",
        recovery_attempted=True,
        ac_step_iteration_budget=10,
    )
    state["detailed_execution_log"] = [_make_failed_step("Timeout 15000ms exceeded")]

    with patch("backend.engine.evaluator.settings") as mock_settings:
        mock_settings.hitl_threshold_general = 4
        mock_settings.hitl_threshold_intercepted = 2
        mock_settings.hitl_threshold_strict_mode = 3
        mock_settings.auto_escalate_threshold = 0

        result = _run_async(evaluator_node(state))

    assert result["_next_node"] == "debugger"


def test_hitl_intercepted_threshold_escalates_at_2():
    """INTERCEPTED should escalate at 2 failures."""
    state = _make_state(
        ac_step_action_fail_count=1,  # Next will be 2
        ac_step_index=1,
        vision_mode="som_coordinates",
        recovery_attempted=True,
        ac_step_iteration_budget=10,
    )
    state["detailed_execution_log"] = [_make_failed_step("click intercepted by <div class='overlay'>")]

    with patch("backend.engine.evaluator.settings") as mock_settings:
        mock_settings.hitl_threshold_general = 4
        mock_settings.hitl_threshold_intercepted = 2
        mock_settings.hitl_threshold_strict_mode = 3
        mock_settings.auto_escalate_threshold = 0

        result = _run_async(evaluator_node(state))

    assert result["_next_node"] == "debugger"


def test_hitl_strict_mode_threshold_escalates_at_3():
    """STRICT_MODE should escalate at 3 failures."""
    state = _make_state(
        ac_step_action_fail_count=2,  # Next will be 3
        ac_step_index=1,
        vision_mode="som_coordinates",
        recovery_attempted=True,
        ac_step_iteration_budget=10,
    )
    state["detailed_execution_log"] = [_make_failed_step("strict mode violation: 5 elements found")]

    with patch("backend.engine.evaluator.settings") as mock_settings:
        mock_settings.hitl_threshold_general = 4
        mock_settings.hitl_threshold_intercepted = 2
        mock_settings.hitl_threshold_strict_mode = 3
        mock_settings.auto_escalate_threshold = 0

        result = _run_async(evaluator_node(state))

    assert result["_next_node"] == "debugger"


def test_hitl_timeout_below_threshold_does_not_escalate():
    """TIMEOUT at 3 failures should still route to planner."""
    state = _make_state(
        ac_step_action_fail_count=2,  # Next will be 3 (threshold is 4)
        ac_step_index=1,
        vision_mode="som_coordinates",
        recovery_attempted=True,
        ac_step_iteration_budget=10,
    )
    state["detailed_execution_log"] = [_make_failed_step("Timeout 15000ms exceeded")]

    with patch("backend.engine.evaluator.settings") as mock_settings:
        mock_settings.hitl_threshold_general = 4
        mock_settings.hitl_threshold_intercepted = 2
        mock_settings.hitl_threshold_strict_mode = 3
        mock_settings.auto_escalate_threshold = 0

        result = _run_async(evaluator_node(state))

    assert result["_next_node"] == "planner"


def test_hitl_thresholds_configurable():
    """Verify that thresholds are read from settings and not hardcoded."""
    state = _make_state(
        ac_step_action_fail_count=9,  # Next will be 10
        ac_step_index=1,
        vision_mode="som_coordinates",
        recovery_attempted=True,
        ac_step_iteration_budget=20,
    )
    state["detailed_execution_log"] = [_make_failed_step("Some random error")]

    with patch("backend.engine.evaluator.settings") as mock_settings:
        mock_settings.hitl_threshold_general = 10
        mock_settings.hitl_threshold_intercepted = 2
        mock_settings.hitl_threshold_strict_mode = 3
        mock_settings.auto_escalate_threshold = 0

        result = _run_async(evaluator_node(state))

    assert result["_next_node"] == "debugger"
