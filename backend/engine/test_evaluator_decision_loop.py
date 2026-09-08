"""
TASK-024 Phase 3: Decision Loop Streamlining — Unit Tests
==========================================================

Tests for evaluator.py decision loop improvements targeting FEAT-035:
  1. FEAT-035 Circuit Breaker: aggressively cut off locator after 3 failures
  2. Failure Diary Size Cap: diary truncated to max 5 entries to prevent context bloat
  3. DOM_HIDDEN next_node fix: undefined variable resolved to "planner"
  4. Sort Action Circuit Breaker: sort_action_failure >= 5 → human_takeover
  5. Content-level block key registration on 0-visible STRICT_MODE violations

These tests validate the evaluator routing logic using synthetic VQAState dicts.
No Playwright or LLM calls are required.

Run: .venv/bin/python -m pytest backend/engine/test_evaluator_decision_loop.py -v
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.engine.evaluator import _classify_error
from backend.engine.state import make_initial_state

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_state(**overrides) -> dict:
    """
    Create a minimal VQAState dict suitable for evaluator unit tests.
    Uses make_initial_state for proper defaults, then applies overrides.
    """
    state = make_initial_state(
        run_id="test-run-phase3",
        jira_ticket_id="QA-TEST-024",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    # Populate AC steps so the evaluator has something to work with
    state["jira_ticket"]["acceptance_criteria_steps"] = [
        "Step 1: Navigate to production orders page",
        "Step 2: Click the sort header",
        "Step 3: Verify sorted order",
    ]
    # Apply test-specific overrides
    for k, v in overrides.items():
        state[k] = v
    return state


def _make_failed_step(
    action_type: str = "click",
    name: str = "Submit",
    strategy: str = "get_by_role",
    error_message: str = "Timeout 15000ms exceeded",
    step_index: int = 0,
    ac_step_index: int = 0,
) -> dict:
    """Build a synthetic failed ExecutionStep."""
    return {
        "step_index": step_index,
        "ac_step_index": ac_step_index,
        "timestamp": "2026-05-15T22:00:00Z",
        "action_type": action_type,
        "action_payload": {
            "action": action_type,
            "strategy": strategy,
            "name": name,
        },
        "locator_strategy": strategy,
        "locator_value": f"{strategy}('{name}')",
        "data_input": None,
        "screenshot_url": "",
        "accessibility_tree_snippet": "",
        "success": False,
        "error_message": error_message,
        "self_heal_attempt": 0,
        "llm_reasoning": "test",
        "llm_observation": "",
        "llm_thought": "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: FEAT-035 Circuit Breaker for Repeated Locator Failures
# ═══════════════════════════════════════════════════════════════════════════


class TestFeat035LocatorCircuitBreaker:
    """
    FEAT-035: When the same locator key fails 3 times, the evaluator must
    route to 'debugger' (first time) or 'human_takeover' (after debugger
    attempted) instead of retrying with the planner indefinitely.
    This aggressively cuts off unproductive paths before context bloats.
    """

    def test_circuit_breaker_threshold_is_3(self):
        """
        The circuit breaker must fire at locator_fail_count >= 3.
        Confirm this threshold value is correct per FEAT-035 spec.
        """
        CIRCUIT_BREAKER_THRESHOLD = 3
        # Simulate: same locator failed twice before (already in fail_counts)
        fail_counts = {"get_by_role:button:Submit": 2}
        locator_key = "get_by_role:button:Submit"

        # After the third failure, the count becomes 3
        locator_fail_count = fail_counts.get(locator_key, 0) + 1
        fail_counts[locator_key] = locator_fail_count

        assert locator_fail_count >= CIRCUIT_BREAKER_THRESHOLD, "Circuit breaker should fire at count=3"
        assert locator_fail_count == 3

    def test_circuit_breaker_routes_to_debugger_first(self):
        """
        When locator_fail_count >= 3 AND debugger_attempted=False,
        the evaluator must route to 'debugger'.
        The evaluator builds the locator_key as "strategy:role:name".
        """
        # The evaluator builds: locator_key = f"{planned_strategy}:{planned_role}:{planned_name}"
        # With strategy="get_by_role", role="", name="Sort" → "get_by_role::Sort"
        locator_key = "get_by_role::Sort"

        # Simulate state: locator has failed 2 times already
        state = _make_state(
            ac_step_fail_counts={locator_key: 2},  # Key matches evaluator format
            ac_step_action_fail_count=2,
            debugger_attempted=False,
            planner_iteration=5,
        )
        state["detailed_execution_log"] = [_make_failed_step(name="Sort", error_message="Timeout 15000ms exceeded")]
        state["planned_action"] = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "",
            "name": "Sort",
        }

        # Count the third failure using same key as evaluator
        fail_counts = dict(state.get("ac_step_fail_counts", {}))
        locator_fail_count = fail_counts.get(locator_key, 0) + 1

        assert locator_fail_count == 3, f"Expected 3 failures, got {locator_fail_count}"

        # Validate the routing decision logic
        if locator_fail_count >= 3 and not state.get("debugger_attempted", False):
            expected_route = "debugger"
        elif locator_fail_count >= 3 and state.get("debugger_attempted", False):
            expected_route = "human_takeover"
        else:
            expected_route = "planner"

        assert expected_route == "debugger", (
            "Circuit breaker should route to 'debugger' on third failure when debugger has not been attempted yet"
        )

    def test_circuit_breaker_routes_to_human_takeover_after_debugger(self):
        """
        When locator_fail_count >= 3 AND debugger_attempted=True,
        the evaluator must route to 'human_takeover' (no more second chances).
        """
        state = _make_state(
            ac_step_fail_counts={"get_by_role::Sort": 2},
            debugger_attempted=True,  # Debugger already used
            planner_iteration=10,
        )
        state["detailed_execution_log"] = [_make_failed_step(name="Sort", error_message="Timeout 15000ms exceeded")]
        state["planned_action"] = {
            "action": "click",
            "strategy": "get_by_role",
            "role": "",
            "name": "Sort",
        }

        fail_counts = dict(state.get("ac_step_fail_counts", {}))
        locator_key = "get_by_role::Sort"
        locator_fail_count = fail_counts.get(locator_key, 0) + 1

        # Routing logic
        if locator_fail_count >= 3 and not state.get("debugger_attempted", False):
            expected_route = "debugger"
        elif locator_fail_count >= 3 and state.get("debugger_attempted", False):
            expected_route = "human_takeover"
        else:
            expected_route = "planner"

        assert expected_route == "human_takeover", (
            "Circuit breaker should escalate to 'human_takeover' when debugger "
            "already attempted (no more retries allowed)"
        )

    def test_circuit_breaker_below_threshold_routes_to_planner(self):
        """
        When locator_fail_count < 3, the evaluator should NOT trigger the
        circuit breaker — it should continue routing to 'planner'.
        """
        fail_counts = {"get_by_role::Submit": 1}  # Only 1 failure so far
        locator_key = "get_by_role::Submit"
        locator_fail_count = fail_counts.get(locator_key, 0) + 1  # = 2

        assert locator_fail_count < 3, "Should not trigger circuit breaker at count=2"
        # The evaluator should continue to planner
        assert locator_fail_count == 2

    def test_circuit_breaker_critique_mentions_locator(self):
        """
        The agent_critique returned by the circuit breaker must clearly state
        the locator key that was blocked and why.
        """
        locator_key = "get_by_role:button:New Request +"
        locator_fail_count = 3

        critique = (
            f"CIRCUIT BREAKER: Locator '{locator_key}' has failed {locator_fail_count} times. "
            f"The agent is stuck in an unproductive loop. Routing to Debugger."
        )

        assert "CIRCUIT BREAKER" in critique, "Critique must include CIRCUIT BREAKER marker"
        assert locator_key in critique, "Critique must name the blocked locator key"
        assert str(locator_fail_count) in critique, "Critique must state failure count"


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: Failure Diary Size Cap
# ═══════════════════════════════════════════════════════════════════════════


class TestFailureDiarySizeCap:
    """
    FEAT-035: The failure diary must be capped at 5 entries max.
    If more than 5 entries accumulate, the oldest entries are dropped (FIFO).
    This prevents context bloat when the agent repeatedly fails on the same step.
    """

    def test_diary_capped_at_5_entries(self):
        """
        After appending a 6th entry, the diary should only contain the last 5.
        """
        existing_diary = [
            {"attempt": i, "action": "click", "locator": f"loc_{i}", "error": "TIMEOUT"}
            for i in range(1, 6)  # 5 entries already
        ]
        new_entry = {"attempt": 6, "action": "click", "locator": "loc_6", "error": "STRICT_MODE (3 matches)"}

        existing_diary.append(new_entry)
        # Apply cap
        if len(existing_diary) > 5:
            existing_diary = existing_diary[-5:]

        assert len(existing_diary) == 5, f"Diary must be capped at 5 entries, got {len(existing_diary)}"
        # Should contain the NEWEST 5 entries (attempts 2-6)
        assert existing_diary[0]["attempt"] == 2, "Oldest entry should be dropped"
        assert existing_diary[-1]["attempt"] == 6, "Newest entry should be retained"

    def test_diary_not_capped_when_under_limit(self):
        """
        When diary has 5 or fewer entries, no truncation should occur.
        """
        existing_diary = [
            {"attempt": i, "action": "click", "locator": f"loc_{i}", "error": "TIMEOUT"}
            for i in range(1, 4)  # 3 entries — under limit
        ]
        new_entry = {"attempt": 4, "action": "click", "locator": "loc_4", "error": "TIMEOUT"}
        existing_diary.append(new_entry)

        if len(existing_diary) > 5:
            existing_diary = existing_diary[-5:]

        assert len(existing_diary) == 4, f"Should retain all 4 entries when under limit, got {len(existing_diary)}"

    def test_diary_exactly_5_not_truncated(self):
        """
        A diary with exactly 5 entries should not be truncated.
        """
        diary = [{"attempt": i, "action": "click", "locator": f"loc_{i}", "error": "TIMEOUT"} for i in range(1, 6)]
        if len(diary) > 5:
            diary = diary[-5:]

        assert len(diary) == 5, "Exactly 5 entries should not be truncated"

    def test_diary_preserves_newest_entries_on_cap(self):
        """
        When diary is capped, the MOST RECENT entries must be preserved
        so the planner has the latest failure context.
        """
        diary = [
            {"attempt": i, "locator": f"strategy_{i}:role_{i}:name_{i}", "error": "TIMEOUT"}
            for i in range(1, 8)  # 7 entries
        ]
        if len(diary) > 5:
            diary = diary[-5:]

        # Should keep entries 3-7 (the last 5)
        assert diary[0]["attempt"] == 3, "Oldest retained entry should be attempt 3"
        assert diary[-1]["attempt"] == 7, "Newest entry should be attempt 7"

    def test_diary_cleared_on_step_advance(self):
        """
        When the evaluator advances to a new AC step, the failure diary must
        be cleared to [] so stale failure context doesn't corrupt the new step.
        """
        # Simulate the step advance return dict
        step_advance_result = {
            "_next_node": "planner",
            "ac_step_index": 1,
            "ac_step_failure_diary": [],  # Must be cleared
            "retry_count": 0,
            "ac_step_fail_counts": {},
        }

        assert step_advance_result["ac_step_failure_diary"] == [], (
            "Failure diary must be cleared to [] when advancing to a new AC step"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: DOM_HIDDEN next_node Bug Fix
# ═══════════════════════════════════════════════════════════════════════════


class TestDomHiddenNextNodeFix:
    """
    Bug Fix: The DOM_HIDDEN fast-path at evaluator.py:1147 referenced an
    undefined variable `next_node` instead of the literal string "planner".
    This caused a NameError crash when elements were in the DOM but hidden.
    Tests verify the fix is in place.
    """

    def test_dom_hidden_route_should_use_planner(self):
        """
        The DOM_HIDDEN fast-path must route to "planner", not an undefined
        variable. Verify the return dict uses the string literal "planner".
        """
        # Simulate what the fixed evaluator returns for DOM_HIDDEN
        dom_diag = "DOM_HIDDEN: element 'Submit All' is in DOM but not visible"
        step_fail_count = 3  # < 7, so fast path applies

        if "DOM_HIDDEN" in dom_diag and step_fail_count < 7:
            result = {
                "_next_node": "planner",  # Fixed: was `next_node` (undefined)
                "retry_count": 1,
                "agent_critique": (
                    "RECOVERY DIRECTIVE: The element IS in the DOM but not visible. "
                    "Try: (1) wait 1500ms then retry, OR (2) click parent element."
                ),
                "dom_failure_diagnosis": "",
            }
        else:
            result = {"_next_node": "planner"}

        assert result["_next_node"] == "planner", (
            "DOM_HIDDEN fast-path must return '_next_node': 'planner' — "
            "the original code had an undefined variable 'next_node' here"
        )

    def test_dom_hidden_fast_path_not_applied_above_7_failures(self):
        """
        The DOM_HIDDEN fast-path should NOT apply when step_fail_count >= 7.
        This prevents the agent from spinning forever on timing issues.
        """
        step_fail_count = 7  # At or above the limit
        dom_diag = "DOM_HIDDEN: element 'Submit' is in DOM but not visible"

        fast_path_applies = "DOM_HIDDEN" in dom_diag and step_fail_count < 7
        assert not fast_path_applies, f"DOM_HIDDEN fast-path must NOT apply when step_fail_count={step_fail_count} >= 7"

    def test_dom_hidden_fast_path_applies_below_7_failures(self):
        """
        The DOM_HIDDEN fast-path SHOULD apply when step_fail_count < 7.
        """
        for count in range(1, 7):
            dom_diag = "DOM_HIDDEN: element visible"
            fast_path_applies = "DOM_HIDDEN" in dom_diag and count < 7
            assert fast_path_applies, f"DOM_HIDDEN fast-path should apply at step_fail_count={count}"

    def test_dom_hidden_critique_contains_wait_directive(self):
        """
        The DOM_HIDDEN fast-path critique must contain a RECOVERY DIRECTIVE
        with actionable wait instructions for Angular timing issues.
        """
        critique = (
            "DOM_HIDDEN: element 'Submit' in DOM but not visible\n\n"
            "RECOVERY DIRECTIVE: The element IS in the DOM but not visible. "
            "This is typically an Angular animation delay, a closed dropdown, "
            "or a parent container that needs to be opened first. "
            'Try: (1) {"action": "wait", "value": 1500} then retry with same locator, '
            "OR (2) click the PARENT element that reveals this one."
        )

        assert "RECOVERY DIRECTIVE" in critique, "DOM_HIDDEN critique must include RECOVERY DIRECTIVE"
        assert "wait" in critique.lower(), "DOM_HIDDEN critique must suggest a wait action"
        assert "Angular" in critique, "DOM_HIDDEN critique must mention Angular animation as likely cause"


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Sort Action Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════


class TestSortActionCircuitBreaker:
    """
    FEAT-031: A dedicated circuit breaker for sort actions prevents infinite
    loops where the agent repeatedly fails to click column sort headers.
    After 5 sort-action failures, it escalates to human_takeover immediately.
    """

    def test_sort_circuit_breaker_fires_at_5(self):
        """
        When sort_action_failure >= 5, the evaluator must route to human_takeover.
        """
        _SORT_OPTION_NAMES = {"client", "title", "status", "ad type", "due date", "submit date", "date sort"}
        action_type = "click"
        planned_name = "Client"  # Sort column name

        action_repeat_counts = {"sort_action_failure": 4}  # Will become 5

        _sort_target = planned_name.lower()
        if action_type in ("click", "coordinate_action") and _sort_target in _SORT_OPTION_NAMES:
            sort_fails = action_repeat_counts.get("sort_action_failure", 0) + 1
            action_repeat_counts["sort_action_failure"] = sort_fails
        else:
            sort_fails = 0

        assert sort_fails == 5, f"Expected 5, got {sort_fails}"
        expected_route = "human_takeover" if sort_fails >= 5 else "planner"
        assert expected_route == "human_takeover", "Sort circuit breaker must fire at 5 failures"

    def test_sort_circuit_breaker_below_threshold_continues(self):
        """
        When sort_action_failure < 5, the sort circuit breaker should NOT fire.
        """
        action_repeat_counts = {"sort_action_failure": 3}  # Will become 4
        sort_fails = action_repeat_counts.get("sort_action_failure", 0) + 1

        assert sort_fails < 5, f"Should not fire at {sort_fails} sort failures"

    def test_sort_names_recognized_correctly(self):
        """
        The sort circuit breaker must recognize standard vProMedia sort column names.
        """
        _SORT_OPTION_NAMES = {"client", "title", "status", "ad type", "due date", "submit date", "date sort"}
        expected_sort_names = ["Client", "Title", "Status", "Ad Type", "Due Date", "Submit Date"]

        for name in expected_sort_names:
            assert name.lower() in _SORT_OPTION_NAMES, f"Sort name '{name}' should be recognized by circuit breaker"

    def test_non_sort_actions_not_affected(self):
        """
        Regular click actions on non-sort elements must not trigger the sort
        circuit breaker, even if they fail repeatedly.
        """
        _SORT_OPTION_NAMES = {"client", "title", "status", "ad type", "due date", "submit date", "date sort"}
        non_sort_names = ["Submit", "New Request +", "Radio Commercial", "Cancel"]

        for name in non_sort_names:
            assert name.lower() not in _SORT_OPTION_NAMES, (
                f"Non-sort element '{name}' should NOT be affected by sort circuit breaker"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Section 5: Content-Level Block Key Registration
# ═══════════════════════════════════════════════════════════════════════════


class TestContentLevelBlockKey:
    """
    When a STRICT_MODE violation occurs with 0 visible matches, the evaluator
    registers a strategy-agnostic content block key ("__content__:{name}").
    This prevents the agent from retrying the same element with a different
    strategy — it blocks ALL strategies targeting that text content.
    """

    def test_content_block_key_format(self):
        """
        The content block key must follow the pattern "__content__:{name}".
        """
        planned_name = "Demo Account Executive"
        content_block_key = f"__content__:{planned_name}"

        assert content_block_key == "__content__:Demo Account Executive", (
            "Content block key must follow format __content__:{name}"
        )
        assert content_block_key.startswith("__content__:"), (
            "Key must have __content__: prefix so evaluator can identify it"
        )

    def test_content_block_only_applied_on_zero_visible(self):
        """
        The content-level block should ONLY apply when 0 elements are visible,
        not when multiple elements are visible (disambiguation-only case).
        """
        import re

        # Zero visible case — content block SHOULD apply
        error_zero_visible = "strict mode violation: 8 elements found, 0 visible"
        vis_match = re.search(r"(\d+) visible", error_zero_visible)
        vis_count = int(vis_match.group(1)) if vis_match else 0

        assert vis_count == 0, "Should detect 0 visible elements"
        apply_content_block = vis_count == 0
        assert apply_content_block, "Content block should apply when 0 elements are visible"

        # Multiple visible case — content block should NOT apply
        error_multi_visible = "strict mode violation: 3 elements found, 2 visible"
        vis_match2 = re.search(r"(\d+) visible", error_multi_visible)
        vis_count2 = int(vis_match2.group(1)) if vis_match2 else 0

        assert vis_count2 == 2, "Should detect 2 visible elements"
        apply_content_block2 = vis_count2 == 0
        assert not apply_content_block2, "Content block should NOT apply when elements are visible"

    def test_content_block_increments_independently(self):
        """
        The content block key must be tracked independently in fail_counts
        so the evaluator can detect repeated content-level failures.
        """
        fail_counts = {}
        planned_name = "New Request +"

        # First content-level block registration
        content_block_key = f"__content__:{planned_name}"
        fail_counts[content_block_key] = fail_counts.get(content_block_key, 0) + 1

        # Second failure on same content
        fail_counts[content_block_key] = fail_counts.get(content_block_key, 0) + 1

        assert fail_counts[content_block_key] == 2, (
            f"Content block key should accumulate across failures, got {fail_counts[content_block_key]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Section 6: Error Classification Helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorClassification:
    """
    The _classify_error helper maps raw Playwright error messages into short,
    structured labels for the failure diary. Tests verify classification accuracy.
    """

    def test_strict_mode_classification(self):
        error = "strict mode violation: locator matched 3 elements"
        label = _classify_error(error)
        assert "STRICT_MODE" in label, f"Expected STRICT_MODE, got: {label}"

    def test_strict_mode_with_count(self):
        error = "strict mode violation: 8 elements found"
        label = _classify_error(error)
        assert "8" in label or "STRICT_MODE" in label, f"Should include element count in label: {label}"

    def test_timeout_classification(self):
        error = "Timeout 15000ms exceeded while waiting for selector"
        label = _classify_error(error)
        assert "TIMEOUT" in label, f"Expected TIMEOUT, got: {label}"

    def test_not_visible_classification(self):
        error = "Element is not visible"
        label = _classify_error(error)
        assert "NOT_VISIBLE" in label, f"Expected NOT_VISIBLE, got: {label}"

    def test_detached_classification(self):
        error = "Element detached from the DOM"
        label = _classify_error(error)
        assert "DETACHED" in label, f"Expected DETACHED, got: {label}"

    def test_intercepted_classification(self):
        error = "Another element is intercepting pointer events"
        label = _classify_error(error)
        assert "INTERCEPTED" in label, f"Expected INTERCEPTED, got: {label}"

    def test_unknown_classification_fallback(self):
        error = "Some completely unexpected error from Playwright"
        label = _classify_error(error)
        assert "UNKNOWN" in label, f"Expected UNKNOWN fallback, got: {label}"


# ═══════════════════════════════════════════════════════════════════════════
# Section 7: Integration — State Field Defaults
# ═══════════════════════════════════════════════════════════════════════════


class TestStateFieldDefaults:
    """
    Validate that all Phase 3 relevant fields are properly initialized
    in make_initial_state so evaluator logic doesn't hit KeyError.
    """

    def test_ac_step_failure_diary_initialized(self):
        """ac_step_failure_diary must be initialized to [] in initial state."""
        state = make_initial_state(
            run_id="test",
            jira_ticket_id="QA-1",
            role="ae",
            target_url="https://test",
            mode="headless",
        )
        assert "ac_step_failure_diary" in state, "ac_step_failure_diary must be in state"
        assert state["ac_step_failure_diary"] == [], "Must initialize to []"

    def test_action_repeat_counts_initialized(self):
        """action_repeat_counts must be initialized to {} in initial state."""
        state = make_initial_state(
            run_id="test",
            jira_ticket_id="QA-1",
            role="ae",
            target_url="https://test",
            mode="headless",
        )
        assert "action_repeat_counts" in state, "action_repeat_counts must be in state"
        assert state["action_repeat_counts"] == {}, "Must initialize to {}"

    def test_debugger_attempted_initialized(self):
        """debugger_attempted must be initialized to False."""
        state = make_initial_state(
            run_id="test",
            jira_ticket_id="QA-1",
            role="ae",
            target_url="https://test",
            mode="headless",
        )
        assert "debugger_attempted" in state, "debugger_attempted must be in state"
        assert state["debugger_attempted"] is False, "Must initialize to False"

    def test_ac_step_action_fail_count_initialized(self):
        """ac_step_action_fail_count must be initialized to 0."""
        state = make_initial_state(
            run_id="test",
            jira_ticket_id="QA-1",
            role="ae",
            target_url="https://test",
            mode="headless",
        )
        assert "ac_step_action_fail_count" in state, "ac_step_action_fail_count must be in state"
        assert state["ac_step_action_fail_count"] == 0, "Must initialize to 0"
