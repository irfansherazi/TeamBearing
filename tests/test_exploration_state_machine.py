"""
TASK-029 Phase 1 Tests — State Machine & Configuration
=======================================================
Module: tests/test_exploration_state_machine.py

Tests for:
  - AC-TRIGGER-1: should_activate() gate logic (feature flag, debugger, re-entry,
                   failure type classification, minimum fail count)
  - AC-STATE-1:   ExplorationOutcome TypedDict structure and VQAState fields

No live browser or Bedrock calls are made — all tests are pure unit tests
using mocks and dict-based VQAState construction.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.engine.schemas import ExplorationOutcome
from backend.engine.state import make_initial_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """
    Build a minimal VQAState-like dict for testing.

    Uses make_initial_state() as the base and applies overrides so tests
    can precisely control the fields relevant to should_activate().
    """
    state = make_initial_state(
        run_id="test-run-exploration",
        jira_ticket_id="FAKE-001",
        role="account_executive",
        target_url="https://two-test.vcreative.net",
        mode="headless",
    )
    state.update(overrides)
    return state


def _make_runner(state: dict, run_id: str = "test-run-001"):
    """Import and construct an ExplorationRunner with the given state."""
    from backend.engine.exploration_runner import ExplorationRunner

    return ExplorationRunner(state=state, run_id=run_id)


# ===========================================================================
# AC-TRIGGER-1: should_activate() gate logic
# ===========================================================================


class TestShouldActivate:
    """
    AC-TRIGGER-1 — Verify the five gates that control exploration activation.

    The runner should activate ONLY when all of the following hold:
      1. ENABLE_EXPLORATION_MODE feature flag = True
      2. debugger_attempted = True
      3. exploration_attempted = False
      4. failure_type NOT in EXPLORATION_BLOCKED_FAILURE_TYPES
      5. ac_step_action_fail_count >= EXPLORATION_MIN_DOM_FAILURES (default 5)
    """

    @pytest.mark.anyio
    async def test_activates_when_all_conditions_met(self):
        """
        Happy path: all five gates open → should_activate() returns True.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="TIMEOUT",
            ac_step_action_fail_count=5,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is True, "should_activate() should return True when all gates open"

    @pytest.mark.anyio
    async def test_does_not_activate_when_feature_flag_disabled(self):
        """
        Gate 1: ENABLE_EXPLORATION_MODE=False → should_activate() returns False.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="",
            ac_step_action_fail_count=10,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = False
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is False, "should_activate() must return False when feature flag is disabled"

    @pytest.mark.anyio
    async def test_does_not_activate_when_debugger_not_attempted(self):
        """
        Gate 2: debugger_attempted=False → should_activate() returns False.
        The debugger must have run first before exploration kicks in.
        """
        state = _make_state(
            debugger_attempted=False,
            exploration_attempted=False,
            failure_type="NOT_VISIBLE",
            ac_step_action_fail_count=5,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is False, "should_activate() must return False when debugger has not yet been attempted"

    @pytest.mark.anyio
    async def test_does_not_activate_when_exploration_already_attempted(self):
        """
        Gate 3: exploration_attempted=True → should_activate() returns False.
        Prevents infinite re-entry if exploration fails.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=True,  # already ran
            failure_type="TIMEOUT",
            ac_step_action_fail_count=8,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is False, "should_activate() must return False when exploration_attempted=True (re-entry guard)"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "blocked_type",
        [
            "AUTH_GATE_BLOCKED",
            "STRICT_MODE",
            "INTERCEPTED",
            "APP_DEFECT",
            "ENV_BLOCKER",
        ],
    )
    async def test_does_not_activate_for_blocked_failure_types(self, blocked_type: str):
        """
        Gate 4: Blocked failure types (auth, strict mode, intercepted) must NOT
        trigger exploration — these have targeted recovery paths.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type=blocked_type,
            ac_step_action_fail_count=10,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is False, f"should_activate() must return False for blocked failure type '{blocked_type}'"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "explorable_type",
        [
            "NOT_VISIBLE",
            "DOM_ABSENT",
            "TIMEOUT",
            "",  # unclassified — explore conservatively
        ],
    )
    async def test_activates_for_explorable_failure_types(self, explorable_type: str):
        """
        Gate 4 (inverse): Explorable failure types should allow activation.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type=explorable_type,
            ac_step_action_fail_count=5,
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is True, f"should_activate() should return True for explorable failure type '{explorable_type}'"

    @pytest.mark.anyio
    async def test_does_not_activate_below_minimum_fail_count(self):
        """
        Gate 5: action_fail_count < EXPLORATION_MIN_DOM_FAILURES → returns False.
        Ensures exploration only fires after the standard retry chain is exhausted.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="TIMEOUT",
            ac_step_action_fail_count=3,  # below threshold of 5
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is False, (
            "should_activate() must return False when action_fail_count < EXPLORATION_MIN_DOM_FAILURES"
        )

    @pytest.mark.anyio
    async def test_activates_exactly_at_minimum_fail_count(self):
        """
        Gate 5 (boundary): action_fail_count == EXPLORATION_MIN_DOM_FAILURES → True.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="NOT_VISIBLE",
            ac_step_action_fail_count=5,  # exactly at threshold
        )
        runner = _make_runner(state)

        with patch("backend.engine.exploration_runner.settings") as mock_settings:
            mock_settings.enable_exploration_mode = True
            mock_settings.exploration_min_dom_failures = 5
            result = await runner.should_activate()

        assert result is True, (
            "should_activate() must return True when action_fail_count == EXPLORATION_MIN_DOM_FAILURES"
        )


# ===========================================================================
# AC-STATE-1: ExplorationOutcome TypedDict structure
# ===========================================================================


class TestExplorationOutcomeStructure:
    """
    AC-STATE-1 — Verify ExplorationOutcome TypedDict has the required fields.

    The TypedDict must define all fields that evaluator_node and reporter
    depend on so static type checkers and runtime dict construction work.
    """

    def test_exploration_outcome_has_required_fields(self):
        """
        All required fields from the spec must exist in ExplorationOutcome.
        """
        required_fields = {
            "ac_step_index",
            "strategy_used",
            "steps_taken",
            "found",
            "kb_injected",
            "target_element",
            "pathway_summary",
            "error_message",
        }

        # TypedDict exposes __annotations__ as the field registry
        actual_fields = set(ExplorationOutcome.__annotations__.keys())

        missing = required_fields - actual_fields
        assert not missing, f"ExplorationOutcome is missing required fields: {missing}"

    def test_exploration_outcome_can_be_constructed_as_dict(self):
        """
        ExplorationOutcome instances must be constructable as plain dicts
        (TypedDicts are just dicts at runtime — no constructor enforcement).
        """
        outcome: ExplorationOutcome = {
            "ac_step_index": 2,
            "strategy_used": "scroll_to_reveal",
            "steps_taken": 3,
            "found": True,
            "kb_injected": True,
            "target_element": "Submit All button",
            "pathway_summary": "scroll_to_bottom → element visible",
            "error_message": "",
        }

        assert outcome["found"] is True
        assert outcome["strategy_used"] == "scroll_to_reveal"
        assert outcome["ac_step_index"] == 2

    def test_exploration_outcome_failure_structure(self):
        """
        A failure outcome (found=False) must also be constructable.
        """
        outcome: ExplorationOutcome = {
            "ac_step_index": 0,
            "strategy_used": "none",
            "steps_taken": 0,
            "found": False,
            "kb_injected": False,
            "target_element": "some element",
            "pathway_summary": "",
            "error_message": "Phase 1 stub — strategies not yet implemented",
        }

        assert outcome["found"] is False
        assert outcome["kb_injected"] is False
        assert outcome["steps_taken"] == 0


# ===========================================================================
# AC-STATE-1: VQAState exploration fields
# ===========================================================================


class TestVQAStateExplorationFields:
    """
    AC-STATE-1 — Verify exploration_attempted and exploration_outcomes are
    correctly initialised in make_initial_state().
    """

    def test_initial_state_has_exploration_attempted_false(self):
        """
        make_initial_state() must initialise exploration_attempted=False.
        """
        state = make_initial_state(
            run_id="test-init",
            jira_ticket_id="FAKE-002",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

        assert state["exploration_attempted"] is False, "make_initial_state() must set exploration_attempted=False"

    def test_initial_state_has_exploration_outcomes_empty_list(self):
        """
        make_initial_state() must initialise exploration_outcomes=[].
        """
        state = make_initial_state(
            run_id="test-init-2",
            jira_ticket_id="FAKE-003",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

        assert state["exploration_outcomes"] == [], "make_initial_state() must set exploration_outcomes=[]"

    def test_exploration_outcomes_accumulate_via_operator_add(self):
        """
        VQAState.exploration_outcomes uses operator.add reducer, which means
        lists are concatenated (not overwritten).

        Simulate two evaluator patches to verify accumulation.
        """
        import operator

        # Simulate LangGraph's reducer behaviour: operator.add([a], [b]) = [a, b]
        episode_1: ExplorationOutcome = {
            "ac_step_index": 0,
            "strategy_used": "scroll_to_reveal",
            "steps_taken": 2,
            "found": True,
            "kb_injected": True,
            "target_element": "Submit button",
            "pathway_summary": "scroll → visible",
            "error_message": "",
        }
        episode_2: ExplorationOutcome = {
            "ac_step_index": 3,
            "strategy_used": "click_sibling_tab",
            "steps_taken": 1,
            "found": False,
            "kb_injected": False,
            "target_element": "Footer link",
            "pathway_summary": "",
            "error_message": "All tabs exhausted",
        }

        accumulated = operator.add([episode_1], [episode_2])

        assert len(accumulated) == 2, "operator.add should concatenate, not overwrite"
        assert accumulated[0]["ac_step_index"] == 0
        assert accumulated[1]["ac_step_index"] == 3


# ===========================================================================
# Config constants tests
# ===========================================================================


class TestExplorationConfig:
    """Verify the new Exploration Mode config constants exist and have correct defaults."""

    def test_enable_exploration_mode_default_true(self):
        """ENABLE_EXPLORATION_MODE defaults to True."""
        from backend.config import settings

        assert settings.enable_exploration_mode is True

    def test_exploration_max_steps_default(self):
        """EXPLORATION_MAX_STEPS defaults to 8."""
        from backend.config import settings

        assert settings.exploration_max_steps == 8

    def test_exploration_min_dom_failures_default(self):
        """EXPLORATION_MIN_DOM_FAILURES defaults to 5."""
        from backend.config import settings

        assert settings.exploration_min_dom_failures == 5


# ===========================================================================
# Phase 1 stub: run() always returns found=False
# ===========================================================================


class TestPhase1Stub:
    """
    Verify the Phase 1 stub behaviour of ExplorationRunner.run().

    Phase 2 will replace run() with real strategy logic; for now it must
    return a well-formed result dict with found=False.
    """

    @pytest.mark.anyio
    async def test_run_returns_found_false_in_phase1(self):
        """
        ExplorationRunner.run() is a stub in Phase 1 — always returns found=False.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="TIMEOUT",
            ac_step_action_fail_count=5,
        )
        runner = _make_runner(state)

        mock_page = MagicMock()  # live page not needed in Phase 1 stub
        result = await runner.run(page=mock_page)

        assert result["found"] is False, "Phase 1 stub must return found=False"

    @pytest.mark.anyio
    async def test_run_returns_well_formed_outcome(self):
        """
        The outcome dict from run() must contain all ExplorationOutcome required fields.
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="DOM_ABSENT",
            ac_step_action_fail_count=7,
        )
        runner = _make_runner(state)

        mock_page = MagicMock()
        result = await runner.run(page=mock_page)

        outcome = result["outcome"]
        required_fields = {
            "ac_step_index",
            "strategy_used",
            "steps_taken",
            "found",
            "kb_injected",
            "target_element",
            "error_message",
        }
        missing = required_fields - set(outcome.keys())
        assert not missing, f"run() outcome is missing required fields: {missing}"

    @pytest.mark.anyio
    async def test_run_does_not_set_kb_injected_on_failure(self):
        """
        Phase 1 stub: kb_injected must be False (no KB writes in Phase 1).
        """
        state = _make_state(
            debugger_attempted=True,
            exploration_attempted=False,
            failure_type="TIMEOUT",
            ac_step_action_fail_count=5,
        )
        runner = _make_runner(state)

        mock_page = MagicMock()
        result = await runner.run(page=mock_page)

        assert result["outcome"]["kb_injected"] is False, (
            "Phase 1 stub must NOT set kb_injected=True (KB injection is Phase 3)"
        )
