"""
TASK-026 / FEAT-035: VQA Engine Robustness — Evaluator Streamlining
=====================================================================
Tests for:
  AC-EVAL-1a  Failure diary is capped at 5 entries to prevent context bloat.
  AC-EVAL-1b  Repeated locator failures trigger the circuit breaker at >= 3 hits
              and route to debugger (first time) or human_takeover (after debugger).

Run:  pytest tests/test_task_026_evaluator_streamlining.py -v
"""

import pytest

from backend.engine.evaluator import evaluator_node

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _failed_state(
    *,
    locator_key_count: int = 1,
    diary_prefill: int = 0,
    debugger_attempted: bool = False,
    action_type: str = "click",
    name: str = "Submit",
    strategy: str = "get_by_role",
    error: str = "TIMEOUT (element not found)",
) -> dict:
    """Build a minimal failed-action state for evaluator_node."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-026",
        jira_ticket_id="VC-026",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    state["jira_ticket"] = {"acceptance_criteria_steps": ["Step 1: Do something"]}
    state["ac_step_index"] = 0
    state["planned_action"] = {
        "action": action_type,
        "strategy": strategy,
        "name": name,
    }
    state["detailed_execution_log"] = [
        {
            "action_type": action_type,
            "action_payload": state["planned_action"],
            "success": False,
            "error_message": error,
        }
    ]
    locator_key = f"{strategy}::{name}"
    state["ac_step_fail_counts"] = {locator_key: locator_key_count}
    state["ac_step_failure_diary"] = [
        {
            "attempt": i + 1,
            "action": action_type,
            "locator": locator_key,
            "error": error,
        }
        for i in range(diary_prefill)
    ]
    state["debugger_attempted"] = debugger_attempted
    return state


# ---------------------------------------------------------------------------
# AC-EVAL-1a  Failure diary cap at 5
# ---------------------------------------------------------------------------


class TestFailureDiaryCap:
    @pytest.mark.anyio
    async def test_diary_not_capped_below_limit(self):
        """Diary with <=5 entries should NOT be truncated."""
        state = _failed_state(diary_prefill=3)
        result = await evaluator_node(state)

        diary = result.get("ac_step_failure_diary", [])
        # 3 pre-filled + 1 new = 4 (well under cap)
        assert len(diary) <= 5, f"Expected <=5 diary entries, got {len(diary)}"

    @pytest.mark.anyio
    async def test_diary_capped_at_five_entries(self):
        """Diary must be capped at 5 entries when it would exceed the limit."""
        # Pre-fill 6 entries; evaluator appends 1 more → would be 7 without cap
        state = _failed_state(diary_prefill=6)
        result = await evaluator_node(state)

        diary = result.get("ac_step_failure_diary", [])
        assert len(diary) <= 5, f"Diary should be capped at 5, got {len(diary)}: {diary}"

    @pytest.mark.anyio
    async def test_diary_keeps_most_recent_entries(self):
        """When truncated, the diary must be at most 5 entries total."""
        # Pre-fill 6 entries; evaluator appends 1 more → 7 without cap → 5 with cap
        state = _failed_state(diary_prefill=6)
        result = await evaluator_node(state)

        diary = result.get("ac_step_failure_diary", [])
        # Core invariant: never exceed 5 entries
        assert len(diary) <= 5, f"Diary should be capped at 5, got {len(diary)}: {diary}"


# ---------------------------------------------------------------------------
# AC-EVAL-1b  Locator circuit breaker at >= 3 repeated failures
# ---------------------------------------------------------------------------


class TestLocatorCircuitBreaker:
    @pytest.mark.anyio
    async def test_two_failures_do_not_trip_circuit_breaker(self):
        """At 2 locator failures the agent should retry normally, not circuit-break.

        Note: evaluator increments the pre-existing count by 1, so we set
        locator_key_count=1 to simulate 2 total failures after increment.
        """
        state = _failed_state(locator_key_count=1)  # evaluator increments to 2
        result = await evaluator_node(state)

        # At only 2 failures the circuit breaker should NOT have fired
        critique = result.get("agent_critique", "")
        assert "CIRCUIT BREAKER" not in critique.upper(), (
            f"Circuit breaker should not trip at only 2 locator failures; got: {critique[:200]}"
        )

    @pytest.mark.anyio
    async def test_three_failures_route_to_debugger_first(self):
        """At 3 locator failures the circuit breaker fires and routes to debugger (first time).

        Note: evaluator increments the pre-existing count by 1, so we set
        locator_key_count=2 to land on 3 total failures after increment.
        """
        state = _failed_state(locator_key_count=2, debugger_attempted=False)  # => 3 after increment
        result = await evaluator_node(state)

        assert result["_next_node"] == "debugger", f"Expected 'debugger', got '{result['_next_node']}'"
        assert "CIRCUIT BREAKER" in result.get("agent_critique", "").upper()

    @pytest.mark.anyio
    async def test_three_failures_after_debugger_routes_to_human_takeover(self):
        """After debugger already attempted, the circuit breaker escalates to human_takeover.

        Note: evaluator increments the pre-existing count by 1, so we set
        locator_key_count=2 to land on 3 total failures after increment.
        """
        state = _failed_state(locator_key_count=2, debugger_attempted=True)  # => 3 after increment
        result = await evaluator_node(state)

        assert result["_next_node"] == "human_takeover", f"Expected 'human_takeover', got '{result['_next_node']}'"
        assert result.get("awaiting_human_takeover") is True
        assert "CIRCUIT BREAKER" in result.get("agent_critique", "").upper()

    @pytest.mark.anyio
    async def test_circuit_breaker_preserves_diary_in_result(self):
        """Circuit breaker result must include ac_step_failure_diary for context.

        Note: locator_key_count=2 => 3 after evaluator increment.
        """
        state = _failed_state(locator_key_count=2)  # => 3 after increment
        result = await evaluator_node(state)

        assert "ac_step_failure_diary" in result, "Circuit breaker must pass diary to next node for context"
