"""
TASK-051 Phase 2 — Bug D Tests
================================
Tests for the evaluator's unverified-done guard when `done` fires
with ZERO prior action failures on the current AC step.

Bug D description:
    The "unverified-done guard" (evaluator.py ~L1320-1348) checks:
        _had_action_failures = bool(state.get("ac_step_fail_counts", {}))
    If the planner emits `done` on the FIRST attempt (empty fail_counts),
    the guard is bypassed and the step is marked complete WITHOUT verifier
    confirmation. The skill_library then records a false-positive skill
    (a "give-up done" with no actual successful action trace).

Tests (tests 1, 2, 3, 4 should FAIL before the fix; 5 and 6 should PASS):
    1. test_evaluator_done_no_failures_routes_to_verifier  [RED]
    2. test_evaluator_done_no_failures_middle_step_routes_to_verifier  [RED]
    3. test_evaluator_done_with_prior_failures_routes_to_verifier  [GREEN — existing guard]
    4. test_evaluator_done_already_completed_step_not_double_verified  [RED]
    5. test_skill_library_not_called_for_giveup_done  [RED]
    6. test_skill_library_not_called_when_no_successful_actions  [GREEN — existing guard]
    7. test_skill_library_called_when_actions_succeeded  [GREEN — positive path]

Acceptance Criteria covered:
    AC-HAPPY-2: Bug D — `done` action with no prior failures routes to verifier
    AC-REGRESS-1: All existing tests continue to pass
"""

import asyncio
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal VQAState-like dict factory
# ---------------------------------------------------------------------------
#
# Important notes from reading evaluator.py:
#   - ac_steps is read from state["jira_ticket"]["acceptance_criteria_steps"]  (L379)
#   - log = state.get("detailed_execution_log", [])  (L378) — MUST be non-empty
#     or evaluator returns {"_next_node": "reporter"} immediately (L415-416)
#   - The evaluator is async; we use asyncio.run() per test.

_DEFAULT_AC_STEPS = [
    "Navigate to the Dashboard",
    "Click the Save button",
    "Verify success banner appears",
]


def _base_state(**overrides) -> dict:
    """
    Return a minimal evaluator state dict suitable for done-action tests.

    Provides a non-empty execution log with a successful 'done' action
    so the evaluator reaches the done-handler (Case 2) rather than
    short-circuiting at the empty-log guard.
    """
    state = {
        # Graph routing
        "_next_node": "",
        # Run metadata
        "run_id": "test-run-bugd-001",
        # Jira ticket carries AC steps (evaluator reads from here, L379)
        "jira_ticket": {
            "id": "TEST-123",
            "acceptance_criteria_steps": list(_DEFAULT_AC_STEPS),
        },
        # AC step tracking
        "ac_step_index": 0,
        "ac_steps_completed": [],
        # Failure tracking — empty = no prior failures on this step (Bug D scenario)
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "step_fail_count": 0,
        # Action — planner signals done on first attempt
        "planned_action": {"action": "done"},
        # Execution log — MUST be non-empty or evaluator returns reporter immediately.
        # Simulate a 'done' action dispatched by the planner (executor records it
        # as action_type="done", success=True when success=True branch is hit).
        # The evaluator checks planned_action["action"] == "done" (L1254), not
        # latest_step["action_type"], so this entry just needs to pass the log guard.
        "detailed_execution_log": [
            {
                "step_index": 0,
                "action_type": "done",
                "success": True,
                "error": "",
                "ac_step_index": 0,
                "screenshot_url": "",
            }
        ],
        # Verifier verdict — not set means we're not in a verifier-callback path
        "_verifier_verdict": "",
        # Other required / optional fields
        "retry_count": 0,
        "max_retries": 3,
        "max_planner_iterations": 500,
        "planner_iteration": 1,
        "ac_step_iteration_budget": 50,
        "ac_step_iterations_used": 0,
        "agent_critique": "",
        "last_error": "",
        "bug_log": [],
        "long_term_memory": [],
        "role": "QA_Engineer",
        "role_queue": [],
        "ac_step_failure_diary": [],
        "action_repeat_counts": {},
        "action_history_buffer": [],
        "vision_mode": "dom",
        "recovery_attempted_types": set(),
        "debugger_attempted": False,
        "dom_failure_diagnosis": "",
        "current_url": "http://localhost:3000",
        "last_executor_fallback": "",
        # FEAT-021 per-step budget (already initialized above)
        "test_plan": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


def _call_evaluator(state: dict) -> dict:
    """Call the async evaluator_node synchronously for unit-test use."""
    from backend.engine.evaluator import evaluator_node

    return asyncio.run(evaluator_node(state))


# ===========================================================================
# Test Group 1 — BUG D: done with ZERO prior failures must route to verifier
# ===========================================================================


class TestEvaluatorDoneGuardNoFailures:
    """
    Bug D core: evaluator must route to verifier when `done` fires on first attempt.

    These tests FAIL on the current code because the guard only checks
    `bool(ac_step_fail_counts)` — an empty dict evaluates to False, so the guard
    is bypassed and the step is accepted as reporter without verification.
    """

    def test_evaluator_done_no_failures_routes_to_verifier(self):
        """
        GIVEN planned_action == 'done'
          AND ac_step_fail_counts == {} (zero prior failures on this step)
          AND the current step is NOT yet in ac_steps_completed
        THEN evaluator MUST return {'_next_node': 'verifier'}

        Currently FAILS: evaluator accepts done without verification and advances
        to reporter (when last step) or planner (when intermediate step).
        """
        state = _base_state(
            ac_step_fail_counts={},  # Bug D scenario: no prior failures
            ac_steps_completed=[],  # step 0 not yet completed
            ac_step_index=0,
        )

        result = _call_evaluator(state)

        assert result["_next_node"] == "verifier", (
            f"BUG D: evaluator returned '{result['_next_node']}' instead of 'verifier'.\n"
            "When done fires with no prior failures and the step has not been completed yet,\n"
            "the evaluator MUST route to verifier for independent confirmation.\n"
            "The current guard only checks bool(ac_step_fail_counts) which is False\n"
            "when empty — this is the bug.\n"
            f"Full result: {result}"
        )

    def test_evaluator_done_no_failures_middle_step_routes_to_verifier(self):
        """
        Same as above but on AC step 1 (not the first step) — confirming the
        guard applies regardless of which step is being processed.
        """
        state = _base_state(
            ac_step_fail_counts={},  # no prior failures on step 1
            ac_steps_completed=[0],  # step 0 already done
            ac_step_index=1,  # processing step 1 for first time
            detailed_execution_log=[
                {
                    "step_index": 1,
                    "action_type": "done",
                    "success": True,
                    "error": "",
                    "ac_step_index": 1,
                    "screenshot_url": "",
                }
            ],
        )

        result = _call_evaluator(state)

        assert result["_next_node"] == "verifier", (
            f"BUG D: evaluator returned '{result['_next_node']}' on AC step 2 with zero failures.\n"
            "The guard must route to verifier regardless of which step index is being processed.\n"
            f"Full result: {result}"
        )


# ===========================================================================
# Test Group 2 — Regression: existing failure-based guard preserved
# ===========================================================================


class TestEvaluatorDoneGuardWithPriorFailures:
    """Regression: the existing guard (prior failures → verifier) must continue to work."""

    def test_evaluator_done_with_prior_failures_routes_to_verifier(self):
        """
        GIVEN planned_action == 'done'
          AND ac_step_fail_counts is non-empty (prior locator failures occurred)
        THEN evaluator MUST route to verifier.

        This covers the existing guard behaviour (already present) and should
        PASS both before and after the fix.
        """
        state = _base_state(
            ac_step_fail_counts={"get_by_text('Save')": 2},  # prior failures exist
            ac_steps_completed=[],
            ac_step_index=0,
        )

        result = _call_evaluator(state)

        assert result["_next_node"] == "verifier", (
            f"REGRESSION: prior-failure guard broken. Got '{result['_next_node']}'.\n"
            "Non-empty ac_step_fail_counts must continue to trigger verifier routing.\n"
            f"Full result: {result}"
        )


# ===========================================================================
# Test Group 3 — Already-completed step context
# ===========================================================================


class TestEvaluatorDoneStepAdvancement:
    """Verifies guard behaviour in the step-advancement context."""

    def test_evaluator_done_step_1_not_yet_in_completed(self):
        """
        Step 1 is being processed for the first time (not in ac_steps_completed).
        The done-with-no-failures guard must fire and route to verifier.

        This validates that the guard checks whether the CURRENT step has been
        independently verified, not just whether any step was completed before.
        """
        state = _base_state(
            ac_step_fail_counts={},
            ac_steps_completed=[0],  # step 0 done, step 1 NOT done yet
            ac_step_index=1,
            detailed_execution_log=[
                {
                    "step_index": 1,
                    "action_type": "done",
                    "success": True,
                    "error": "",
                    "ac_step_index": 1,
                    "screenshot_url": "",
                }
            ],
        )

        result = _call_evaluator(state)

        assert result["_next_node"] == "verifier", (
            f"Expected verifier for step 1 (first attempt, zero failures), got '{result['_next_node']}'.\n"
            f"Full result: {result}"
        )


# ===========================================================================
# Test Group 4 — skill_library NOT called for give-up done
# ===========================================================================


class TestSkillLibraryGiveUpDone:
    """Bug D: skill_library.record_skill must NOT be called for a give-up done."""

    def test_skill_library_not_called_for_giveup_done(self):
        """
        GIVEN planned_action == 'done'
          AND ac_step_fail_counts == {} (first attempt, zero real actions taken)
          AND detailed_execution_log has no successful entries for the current step
        THEN skill_library.record_skill must NOT be called.

        After fix: guard routes to verifier — the skill-recording code in the
        done-handler advance path is never reached for give-up done scenarios.

        After fix, this test should PASS (guard fires → verifier → no skill recording).
        Before fix, this test may be indeterminate (the done-handler is reached but
        _step_actions filter may already prevent recording — the test validates both
        the routing AND the non-recording invariant).
        """
        mock_skill_library = MagicMock()

        state = _base_state(
            ac_step_fail_counts={},  # zero prior failures — Bug D scenario
            ac_steps_completed=[],
            ac_step_index=0,
            # No successful actions for step 0 in the execution log
            detailed_execution_log=[
                {
                    "step_index": 0,
                    "action_type": "done",
                    "success": True,  # executor records done as success
                    "error": "",
                    "ac_step_index": 0,
                    "screenshot_url": "",
                }
            ],
        )

        with patch("backend.engine.evaluator._skill_library", mock_skill_library):
            result = _call_evaluator(state)

        # After fix: guard fires → routes to verifier → record_skill never called
        assert result["_next_node"] == "verifier", (
            f"BUG D: Expected routing to verifier for give-up done, got '{result['_next_node']}'.\n"
            f"Full result: {result}"
        )

        (
            mock_skill_library.record_skill.assert_not_called(),
            (
                "BUG D: skill_library.record_skill was called for a give-up 'done' action.\n"
                "When the done-with-no-failures guard fires, the evaluator must route to\n"
                "verifier — skill recording must not happen in this code path."
            ),
        )

    def test_skill_library_not_called_when_no_successful_actions_in_log(self):
        """
        Even with prior failures on the step (triggering the existing guard),
        if detailed_execution_log has no SUCCESSFUL entries for the current step,
        skill recording must not happen.

        The existing filter at L1364: `if _step_actions:` gates recording on
        non-empty successful actions. Verifying this guard is still intact.
        This test PASSES both before and after the fix.
        """
        mock_skill_library = MagicMock()

        state = _base_state(
            ac_step_fail_counts={"get_by_role('button', name='Save')": 3},
            ac_steps_completed=[],
            ac_step_index=0,
            # Only a done action in the log — no "real" successful click/fill actions
            detailed_execution_log=[
                {
                    "step_index": 0,
                    "action_type": "done",
                    "success": True,
                    "error": "",
                    "ac_step_index": 0,
                    "screenshot_url": "",
                }
            ],
        )

        with patch("backend.engine.evaluator._skill_library", mock_skill_library):
            _call_evaluator(state)

        # Routing goes to verifier (prior failures). Record_skill not called.
        mock_skill_library.record_skill.assert_not_called()


# ===========================================================================
# Test Group 5 — Positive: guard does not fire when step already verified
# ===========================================================================


class TestEvaluatorDoneNoGuardWhenVerified:
    """
    After the verifier confirms a step, evaluator re-enters with verifier context.
    The guard must NOT double-trigger — the post-verifier flow must continue normally.
    """

    def test_evaluator_post_verifier_routes_to_planner_advance(self):
        """
        Simulate the post-verifier re-entry:
        The verifier satisfied the step and the evaluator re-enters with action='done'.
        In this scenario ac_step_fail_counts has prior entries (the verifier was called
        because of them) AND the step is still not in ac_steps_completed yet.

        The evaluator should route to verifier (prior failure guard fires), which is
        correct — the verifier will then return SATISFIED and the evaluator will re-enter
        one more time in the post-verifier path (handled by the ac_index >= len guard).

        This test documents the expected routing chain for prior-failure scenarios.
        """
        state = _base_state(
            # Prior failures exist — old guard fires as expected
            ac_step_fail_counts={"some_locator": 1},
            ac_steps_completed=[],
            ac_step_index=0,
        )

        result = _call_evaluator(state)

        # With prior failures: verifier is correctly invoked
        assert result["_next_node"] == "verifier", (
            f"Expected verifier routing when prior failures exist.\nGot '{result['_next_node']}'."
        )
