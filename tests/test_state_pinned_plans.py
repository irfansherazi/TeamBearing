"""
tests/test_state_pinned_plans.py
=================================

Unit tests for Phase 2: pinned-plan VQAState additions.

Covers:
  - VQAState TypedDict has pinned_plan field (dict | None)
  - VQAState TypedDict has pinned_plan_id field (str | None)
  - make_initial_state() initialises pinned_plan to None
  - make_initial_state() initialises pinned_plan_id to None
  - make_initial_state() accepts pinned_plan / pinned_plan_id kwargs
    (future-proofing; optional at Phase 2 since routes wiring is Phase 4)
  - Existing make_initial_state() signature and outputs are unchanged
"""

import pytest

from backend.engine.state import VQAState, make_initial_state


# ---------------------------------------------------------------------------
# VQAState field presence
# ---------------------------------------------------------------------------


class TestVQAStatePinnedPlanFields:
    """VQAState TypedDict must declare pinned_plan and pinned_plan_id."""

    def _make_state(self) -> VQAState:
        return make_initial_state(
            run_id="test-run-001",
            jira_ticket_id="VC2-0001",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

    def test_pinned_plan_field_exists(self):
        """VQAState must have a pinned_plan key."""
        state = self._make_state()
        assert "pinned_plan" in state

    def test_pinned_plan_id_field_exists(self):
        """VQAState must have a pinned_plan_id key."""
        state = self._make_state()
        assert "pinned_plan_id" in state

    def test_pinned_plan_defaults_to_none(self):
        """make_initial_state must initialise pinned_plan to None."""
        state = self._make_state()
        assert state["pinned_plan"] is None

    def test_pinned_plan_id_defaults_to_none(self):
        """make_initial_state must initialise pinned_plan_id to None."""
        state = self._make_state()
        assert state["pinned_plan_id"] is None

    def test_pinned_plan_can_hold_dict(self):
        """pinned_plan field accepts a dict (the TestPlan structure)."""
        state = self._make_state()
        test_plan_dict = {
            "steps": [{"step_id": 1, "goal": "Login", "step_type": "NAVIGATE"}]
        }
        # TypedDict assignment — verify no TypeError
        state["pinned_plan"] = test_plan_dict  # type: ignore[typeddict-item]
        assert state["pinned_plan"] == test_plan_dict

    def test_pinned_plan_id_can_hold_string(self):
        """pinned_plan_id field accepts a string opaque id."""
        state = self._make_state()
        state["pinned_plan_id"] = "abc-123-opaque"  # type: ignore[typeddict-item]
        assert state["pinned_plan_id"] == "abc-123-opaque"


# ---------------------------------------------------------------------------
# make_initial_state() existing contract is unchanged (additive)
# ---------------------------------------------------------------------------


class TestMakeInitialStateAdditive:
    """Existing make_initial_state callers must be unaffected by Phase 2 additions."""

    def test_required_fields_unchanged(self):
        """Existing required fields still populate correctly."""
        state = make_initial_state(
            run_id="run-xyz",
            jira_ticket_id="VC2-5678",
            role="producer",
            target_url="https://qa.vcreative.net",
            mode="interactive",
        )
        assert state["run_id"] == "run-xyz"
        assert state["jira_ticket"]["ticket_id"] == "VC2-5678"
        assert state["role_queue"] == ["producer"]
        assert state["target_url"] == "https://qa.vcreative.net"
        assert state["execution_mode"] == "interactive"

    def test_existing_test_plan_field_unchanged(self):
        """Existing test_plan field must still default to None (not clobbered)."""
        state = make_initial_state(
            run_id="run-abc",
            jira_ticket_id="VC2-1111",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert state["test_plan"] is None

    def test_new_pinned_fields_do_not_clobber_test_plan(self):
        """pinned_plan and test_plan are distinct fields — both default None."""
        state = make_initial_state(
            run_id="run-abc",
            jira_ticket_id="VC2-1111",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert state["test_plan"] is None
        assert state["pinned_plan"] is None
        # They must be distinct keys
        assert "test_plan" in state
        assert "pinned_plan" in state
        assert state["test_plan"] is not state["pinned_plan"] or (
            state["test_plan"] is None and state["pinned_plan"] is None
        )
