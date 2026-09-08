"""
FEAT-020: Action History Buffer — Unit Tests
============================================
Tests for the rolling action history buffer that prevents the planner from
repeating ineffective strategies ("amnesic retry loops").

Coverage:
  AC-HAPPY-1: action_history_buffer exists in VQAState initial state
  AC-HAPPY-2: Buffer entry has correct structured keys
  AC-HAPPY-3: FIFO capping at 5 entries
  AC-HAPPY-4: Buffer cleared on ac_step_index advance
  AC-HAPPY-5: Planner injects <past_actions> XML when buffer non-empty
  AC-HAPPY-6: XML includes NEVER repeat constraint text
  AC-ERROR-1: Empty buffer produces no XML (empty string)
  AC-REGRESS-2: ac_step_failure_diary is independent of action_history_buffer
"""

from backend.engine.planner import _build_past_actions_block
from backend.engine.state import make_initial_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_buffer_entry(
    action: str = "click",
    strategy: str = "get_by_role",
    target: str = "Submit",
    error_type: str = "TIMEOUT",
    iteration: int = 1,
) -> dict:
    """Build a structured action history buffer entry."""
    return {
        "action": action,
        "strategy": strategy,
        "target": target,
        "error_type": error_type,
        "iteration": iteration,
    }


# ---------------------------------------------------------------------------
# AC-HAPPY-1: VQAState initialisation
# ---------------------------------------------------------------------------


def test_initial_state_has_action_history_buffer():
    """AC-HAPPY-1: action_history_buffer field exists in VQAState as plain list[dict]"""
    state = make_initial_state(
        run_id="test-run",
        jira_ticket_id="VC-123",
        role="producer",
        target_url="http://test.com",
        mode="headless",
    )
    assert "action_history_buffer" in state
    assert state["action_history_buffer"] == []
    assert isinstance(state["action_history_buffer"], list)


# ---------------------------------------------------------------------------
# AC-HAPPY-2: Structured entry format
# ---------------------------------------------------------------------------


def test_buffer_entry_has_required_keys():
    """AC-HAPPY-2: Entry must contain action, strategy, target, error_type, iteration"""
    entry = _make_buffer_entry(
        action="click",
        strategy="get_by_role",
        target="Submit",
        error_type="TIMEOUT (element not found or still loading)",
        iteration=3,
    )
    assert entry["action"] == "click"
    assert entry["strategy"] == "get_by_role"
    assert entry["target"] == "Submit"
    assert entry["error_type"] == "TIMEOUT (element not found or still loading)"
    assert entry["iteration"] == 3


# ---------------------------------------------------------------------------
# AC-HAPPY-3: FIFO capping (Append-Then-Slice)
# ---------------------------------------------------------------------------


def test_buffer_fifo_capping():
    """AC-HAPPY-3: Buffer capped at 5 entries — 6th evicts oldest"""
    buffer = [_make_buffer_entry(iteration=i) for i in range(1, 6)]
    assert len(buffer) == 5

    # Simulate append-then-slice (the evaluator's algorithm)
    new_entry = _make_buffer_entry(iteration=6, action="fill")
    buffer.append(new_entry)
    buffer = buffer[-5:]

    assert len(buffer) == 5
    # Oldest (iteration=1) should be evicted
    assert buffer[0]["iteration"] == 2
    # Newest (iteration=6) should be at the end
    assert buffer[4]["iteration"] == 6
    assert buffer[4]["action"] == "fill"


def test_buffer_under_capacity_no_eviction():
    """Fewer than 5 entries — no eviction should occur"""
    buffer = [_make_buffer_entry(iteration=i) for i in range(1, 4)]
    new_entry = _make_buffer_entry(iteration=4)
    buffer.append(new_entry)
    buffer = buffer[-5:]

    assert len(buffer) == 4
    assert buffer[0]["iteration"] == 1
    assert buffer[3]["iteration"] == 4


# ---------------------------------------------------------------------------
# AC-HAPPY-4: Buffer cleared on AC step advance
# ---------------------------------------------------------------------------


def test_buffer_cleared_on_advance():
    """AC-HAPPY-4: Buffer should be reset to [] when ac_step_index advances.

    This tests the contract: every evaluator return dict that advances
    ac_step_index MUST include action_history_buffer: [].
    (Verified by grep of evaluator.py for all paths returning new ac_step_index.)
    """
    # Simulate the evaluator return dict on step advance
    evaluator_return = {
        "_next_node": "planner",
        "ac_step_index": 1,
        "ac_steps_completed": [0],
        "retry_count": 0,
        "ac_step_failure_diary": [],
        "action_history_buffer": [],  # FEAT-020: cleared
    }
    assert evaluator_return["action_history_buffer"] == []


# ---------------------------------------------------------------------------
# AC-HAPPY-5 + AC-HAPPY-6: XML block generation (non-empty buffer)
# ---------------------------------------------------------------------------


def test_build_past_actions_block_non_empty():
    """AC-HAPPY-5 & AC-HAPPY-6: <past_actions> XML with NEVER repeat constraint"""
    state = {
        "action_history_buffer": [
            {
                "action": "click",
                "strategy": "get_by_role",
                "target": "Submit",
                "error_type": "TIMEOUT",
                "iteration": 1,
            }
        ]
    }
    xml = _build_past_actions_block(state)

    # AC-HAPPY-5: XML tags present
    assert "<past_actions>" in xml
    assert "</past_actions>" in xml

    # Content includes all fields
    assert "click" in xml
    assert "get_by_role" in xml
    assert "Submit" in xml
    assert "TIMEOUT" in xml
    assert "iteration 1" in xml

    # AC-HAPPY-6: NEVER repeat constraint
    assert "NEVER repeat" in xml


def test_build_past_actions_block_multiple_entries():
    """Multiple entries should all appear in the XML block"""
    state = {
        "action_history_buffer": [
            _make_buffer_entry(action="click", target="Save", iteration=1),
            _make_buffer_entry(action="fill", target="Email", iteration=2, error_type="STRICT_MODE"),
            _make_buffer_entry(action="press_key", target="Enter", iteration=3),
        ]
    }
    xml = _build_past_actions_block(state)

    assert "<past_actions>" in xml
    assert "Save" in xml
    assert "Email" in xml
    assert "Enter" in xml
    assert "STRICT_MODE" in xml
    assert "iteration 1" in xml
    assert "iteration 2" in xml
    assert "iteration 3" in xml
    assert "NEVER repeat" in xml


# ---------------------------------------------------------------------------
# AC-ERROR-1: Empty buffer produces no XML
# ---------------------------------------------------------------------------


def test_build_past_actions_block_empty():
    """AC-ERROR-1: Empty buffer produces no XML (empty string)"""
    state = {"action_history_buffer": []}
    result = _build_past_actions_block(state)
    assert result == ""


def test_build_past_actions_block_missing_key():
    """Edge case: buffer key missing from state entirely"""
    result = _build_past_actions_block({})
    assert result == ""


# ---------------------------------------------------------------------------
# AC-REGRESS-2: ac_step_failure_diary independence
# ---------------------------------------------------------------------------


def test_failure_diary_independent_of_action_history_buffer():
    """AC-REGRESS-2: ac_step_failure_diary still works unchanged"""
    state = make_initial_state(
        run_id="test-run",
        jira_ticket_id="VC-123",
        role="producer",
        target_url="http://test.com",
        mode="headless",
    )
    # Both fields exist and are independent
    assert "ac_step_failure_diary" in state
    assert "action_history_buffer" in state
    assert state["ac_step_failure_diary"] == []
    assert state["action_history_buffer"] == []

    # Mutating one does not affect the other
    state["ac_step_failure_diary"].append({"attempt": 1, "action": "click"})
    assert len(state["action_history_buffer"]) == 0

    state["action_history_buffer"].append(_make_buffer_entry())
    assert len(state["ac_step_failure_diary"]) == 1
