"""
TASK-101: DVQ Re-Check Loop Evaluator Integration — Unit and Integration Tests
=============================================================================

Tests for the final DVQ re-check loop in evaluator_node and custom styled badges,
and overriding completed step results dynamically in backend/engine/reporter.py.

Run: .venv/bin/pytest tests/test_task_101_dvq_recheck.py -v
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.engine.state import make_initial_state
from backend.engine.evaluator import evaluator_node
from backend.engine.reporter import _render_header, _render_ac_table


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _run_async(coro):
    """Helper to run async tests without pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_state(ac_step_index: int = 2, **overrides) -> dict:
    """Create a minimal VQAState dict suitable for final DVQ re-check tests."""
    state = make_initial_state(
        run_id="test-run-task-101",
        jira_ticket_id="TASK-101",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    
    # Configure minimum steps
    state["jira_ticket"] = {
        "ticket_id": "TASK-101",
        "summary": "DVQ Integration Test",
        "acceptance_criteria_steps": [
            "Step 1: Check something",
            "Step 2: Check another thing",
        ],
    }
    state["ac_step_index"] = ac_step_index
    state["ac_steps_completed"] = list(range(ac_step_index))
    state["role_queue"] = ["account_executive"]  # No remaining roles to complete the run
    
    # Add other typical fields
    state["detailed_execution_log"] = [
        {
            "step_index": 0,
            "action_type": "done",
            "success": True,
            "ac_step_index": ac_step_index,
        }
    ]
    state["planned_action"] = {"action": "done"}
    state["recovery_attempted_types"] = set()
    
    for k, v in overrides.items():
        state[k] = v
    return state


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTASK101EvaluatorDVQRecheck:
    """Verifies evaluator routing, state transitions, and logging for DVQ final rechecks."""

    def test_final_recheck_success_and_failure(self):
        """Verify that when the run is complete, remaining DVQ entries are re-checked.
        
        Passing rechecks should go to deferred_verification_successes.
        Failing rechecks should go to deferred_verification_failures.
        The deferred_verification_queue should be emptied.
        """
        # Set ac_step_index=2 which matches length of ac_steps, i.e., primary steps complete.
        dvq = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "verification": {"type": "element_visible", "selector_hint": ".success-element"},
            },
            {
                "ac_step_index": 1,
                "bypass_type": "sparse_dataset",
                "verification": {"type": "element_visible", "selector_hint": ".failing-element"},
            }
        ]
        
        state = _make_state(ac_step_index=2, deferred_verification_queue=dvq)
        
        # We expect two verifications: 
        # First one (.success-element) returns "satisfied" (PASS)
        # Second one (.failing-element) returns "not_yet" (FAIL)
        with (
            patch("backend.browser.context.get_manager") as mock_get_manager,
            patch("backend.engine.verifier._check_single_verification", new_callable=AsyncMock) as mock_verify,
        ):
            mock_manager = MagicMock()
            mock_manager.page = MagicMock()
            mock_get_manager.return_value = mock_manager
            
            # Side effect for the two sequential rechecks
            mock_verify.side_effect = [
                ("satisfied", "Element found", None),
                ("not_yet", "Element not found", None)
            ]
            
            result = _run_async(evaluator_node(state))
            
        # Verify the queue is now empty
        assert len(result["deferred_verification_queue"]) == 0
        
        # Verify successes list
        successes = result["deferred_verification_successes"]
        assert len(successes) == 1
        assert successes[0]["ac_step_index"] == 0
        assert "satisfied" in successes[0]["reason"]
        
        # Verify failures list
        failures = result["deferred_verification_failures"]
        assert len(failures) == 1
        assert failures[0]["ac_step_index"] == 1
        assert "not_yet" in failures[0]["failure_reason"]
        
        # Verify correct transition node
        assert result["_next_node"] == "reporter"


class TestTASK101ReporterDVFOverride:
    """Verifies that failed deferred rechecks correctly override step status and FAILED overall status."""

    def test_failed_recheck_overrides_status(self):
        """A failed deferred recheck should result in overall FAILED status in _render_header
        and the failed step index displaying as a fail in _render_ac_table.
        """
        # Let's say both steps were marked completed, but step 1 (index 1) failed its deferred recheck.
        state = _make_state(ac_step_index=2)
        state["ac_steps_completed"] = [0, 1]
        state["deferred_verification_failures"] = [
            {
                "ac_step_index": 1,
                "bypass_type": "sparse_dataset",
                "failure_reason": "Deferred final re-check failed (verdict=not_yet)",
            }
        ]
        
        # Verify header status rendering
        header_html = _render_header(state, duration_ms=5000)
        assert "FAILED" in header_html
        assert "1/2 passed" in header_html  # Excluded failed recheck from count
        
        # Verify AC table rendering
        table_html = _render_ac_table(state)
        # Step 2 (index 1) should be a failure row
        # Since it's failed, it should render under "fail" class and contain "✗" icon
        assert '<tr class="fail">' in table_html
        assert '✗' in table_html


class TestTASK101ReporterReverifiedBadge:
    """Verifies that successful deferred rechecks display the 🔁 Re-verified badge with class reverified-badge."""

    def test_successful_recheck_shows_badge(self):
        """A successful deferred recheck should render with 'reverified-badge' class in the AC table."""
        state = _make_state(ac_step_index=2)
        state["ac_steps_completed"] = [0, 1]
        state["deferred_verification_successes"] = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "reason": "Deferred final re-check passed (verdict=satisfied)",
            }
        ]
        
        # Render AC table and check for class and text
        table_html = _render_ac_table(state)
        assert "reverified-badge" in table_html
        assert "🔁 Re-verified" in table_html


class TestTASK101EndToEndIntegration:
    """Runs a complete dual-outcome verification flow end-to-end using mock state and verifier outcomes."""

    def test_dual_outcome_flow(self):
        """End-to-end integration test with one success and one failure deferred re-checks."""
        dvq = [
            {
                "ac_step_index": 0,
                "bypass_type": "transient_selector",
                "verification": {"type": "element_visible", "selector_hint": ".btn-submit"},
            },
            {
                "ac_step_index": 1,
                "bypass_type": "sparse_dataset",
                "verification": {"type": "element_visible", "selector_hint": ".btn-cancel"},
            }
        ]
        state = _make_state(ac_step_index=2, deferred_verification_queue=dvq)
        
        with (
            patch("backend.browser.context.get_manager") as mock_get_manager,
            patch("backend.engine.verifier._check_single_verification", new_callable=AsyncMock) as mock_verify,
        ):
            mock_manager = MagicMock()
            mock_manager.page = MagicMock()
            mock_get_manager.return_value = mock_manager
            
            # Side effect for the two sequential rechecks
            mock_verify.side_effect = [
                ("satisfied", "Element found", None),
                ("not_yet", "Element not found", None)
            ]
            
            # 1. Run Evaluator Node
            result = _run_async(evaluator_node(state))
            
        # State transitions should be successfully written
        assert len(result["deferred_verification_queue"]) == 0
        assert len(result["deferred_verification_successes"]) == 1
        assert len(result["deferred_verification_failures"]) == 1
        
        # Merge updates back into full state to simulate LangGraph's state merging
        for k, v in result.items():
            state[k] = v
        
        # 2. Render report header and table
        header_html = _render_header(state, duration_ms=1000)
        table_html = _render_ac_table(state)
        
        # Header should reflect failure
        assert "FAILED" in header_html
        assert "1/2 passed" in header_html
        
        # Table should have both pass and fail rows, and the reverified-badge class
        assert "reverified-badge" in table_html
        assert "🔁 Re-verified" in table_html
        assert '<tr class="fail">' in table_html
        assert '<tr class="pass">' in table_html
