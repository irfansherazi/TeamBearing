"""
test_cv_fallback_cost_gate.py
Phase 1 Unit Tests — CV Fallback Cost Gate

Tests for:
  AC-ENTRY-2: Cost gate prevents premature vision calls (fail_count < threshold → no CV)
  AC-ENTRY-2: CV call fires at threshold (fail_count >= threshold → CV)
  AC-HAPPY-2: cv_fallback_eligible=True lowers threshold from 3 to 1
  State schema: VQAState serializes cv_fallback_invocations and cv_fallback_results
  Config: CV_FALLBACK_ENABLED and CV_FALLBACK_MIN_DOM_FAILURES fields present and correct

All tests are pure unit tests — no Playwright, no LLM, no network.
"""

import operator

import pytest

# ---------------------------------------------------------------------------
# CvFallbackResolver
# ---------------------------------------------------------------------------
from backend.browser.cv_resolver import CvFallbackResolver


class TestShouldActivate:
    """Tests for CvFallbackResolver.should_activate()."""

    def _make_state(
        self,
        *,
        ac_step_action_fail_count: int = 0,
        cv_fallback_results: list | None = None,
        ac_step_index: int = 0,
    ) -> dict:
        """Build a minimal VQAState-compatible dict for cost gate testing."""
        return {
            "ac_step_action_fail_count": ac_step_action_fail_count,
            "cv_fallback_results": cv_fallback_results or [],
            "cv_fallback_invocations": 0,
            "ac_step_index": ac_step_index,
        }

    def _make_action(self, action_type: str = "click", *, cv_fallback_eligible: bool = False) -> dict:
        return {
            "action": action_type,
            "name": "Some Button",
            "cv_fallback_eligible": cv_fallback_eligible,
        }

    # ── AC-ENTRY-2: Cost gate — below threshold ──────────────────────────

    def test_fail_count_0_no_activation(self):
        """Fail count 0 → should_activate returns False regardless of config."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=0)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    def test_fail_count_1_no_activation_at_threshold_3(self):
        """Fail count 1 < threshold 3 → CV does not activate."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=1)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    def test_fail_count_2_no_activation_at_threshold_3(self):
        """Fail count 2 < threshold 3 → CV does not activate."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=2)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    # ── AC-ENTRY-2: Cost gate — at threshold ────────────────────────────

    def test_fail_count_3_activates_at_threshold_3(self):
        """Fail count 3 >= threshold 3 → CV activates."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=3)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is True

    def test_fail_count_5_activates_above_threshold(self):
        """Fail count 5 >> threshold 3 → CV still activates."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=5)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is True

    # ── Feature flag gate ────────────────────────────────────────────────

    def test_disabled_flag_prevents_activation(self):
        """enabled=False → never activates even at threshold."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=10)
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=False, min_dom_failures=3) is False

    # ── Action type gate ─────────────────────────────────────────────────

    def test_only_click_action_eligible(self):
        """Only 'click' and 'coordinate_action' action types are eligible."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=5)

        for action_type in ("click", "coordinate_action"):
            action = self._make_action(action_type)
            assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is True, (
                f"Expected {action_type} to be eligible"
            )

    def test_non_click_action_not_eligible(self):
        """Non-click action types do not activate CV fallback."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=10)

        for action_type in ("fill", "press_key", "scroll", "navigate", "wait"):
            action = self._make_action(action_type)
            assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False, (
                f"Expected {action_type} to NOT be eligible"
            )

    # ── AC-HAPPY-2: cv_fallback_eligible lowers threshold to 1 ──────────

    def test_cv_fallback_eligible_lowers_threshold_to_1(self):
        """cv_fallback_eligible=True on action → threshold lowers to 1."""
        resolver = CvFallbackResolver()
        # Only 1 failure — normally below threshold of 3
        state = self._make_state(ac_step_action_fail_count=1)
        action = self._make_action("click", cv_fallback_eligible=True)
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is True

    def test_cv_fallback_eligible_fail_count_0_still_no_activation(self):
        """cv_fallback_eligible=True but fail_count=0 → still no activation (≥1 required)."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=0)
        action = self._make_action("click", cv_fallback_eligible=True)
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    def test_cv_fallback_eligible_false_uses_normal_threshold(self):
        """cv_fallback_eligible=False → normal threshold applies (fail_count=1 < 3 → no)."""
        resolver = CvFallbackResolver()
        state = self._make_state(ac_step_action_fail_count=1)
        action = self._make_action("click", cv_fallback_eligible=False)
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    # ── Per-step double-vision guard ─────────────────────────────────────

    def test_already_attempted_on_this_step_prevents_second_call(self):
        """If cv_fallback_results already contains an entry for the current step, don't re-activate."""
        resolver = CvFallbackResolver()
        state = self._make_state(
            ac_step_action_fail_count=5,
            cv_fallback_results=[{"step_idx": 0, "mark_id": 3, "x": 100, "y": 200, "success": False}],
            ac_step_index=0,
        )
        action = self._make_action("click")
        # Step 0 already has a CV result → guard prevents second call
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is False

    def test_previous_step_result_does_not_block_new_step(self):
        """CV result for step 0 does NOT block activation on step 1."""
        resolver = CvFallbackResolver()
        state = self._make_state(
            ac_step_action_fail_count=3,
            cv_fallback_results=[{"step_idx": 0, "mark_id": 3, "x": 100, "y": 200, "success": True}],
            ac_step_index=1,  # Now on step 1
        )
        action = self._make_action("click")
        assert resolver.should_activate(state, action, enabled=True, min_dom_failures=3) is True


class TestEstimateCost:
    """Tests for CvFallbackResolver.estimate_cost()."""

    def test_estimate_cost_returns_expected_value(self):
        """estimate_cost() returns ~$0.003 per invocation (Claude Sonnet vision at 1024px)."""
        resolver = CvFallbackResolver()
        cost = resolver.estimate_cost()
        assert isinstance(cost, float)
        assert cost == pytest.approx(0.003, rel=0.01)

    def test_estimate_cost_positive(self):
        """Cost estimate must always be positive."""
        assert CvFallbackResolver().estimate_cost() > 0


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------


class TestConfigFields:
    """Verify CV_FALLBACK config fields exist and have correct defaults."""

    def test_cv_fallback_enabled_exists_and_defaults_true(self):
        """Settings must have cv_fallback_enabled field defaulting to True."""
        from backend.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert hasattr(s, "cv_fallback_enabled"), "Settings missing cv_fallback_enabled"
        assert s.cv_fallback_enabled is True

    def test_cv_fallback_min_dom_failures_exists_and_defaults_3(self):
        """Settings must have cv_fallback_min_dom_failures field defaulting to 3."""
        from backend.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert hasattr(s, "cv_fallback_min_dom_failures"), "Settings missing cv_fallback_min_dom_failures"
        assert s.cv_fallback_min_dom_failures == 3

    def test_cv_fallback_min_dom_failures_is_int(self):
        """cv_fallback_min_dom_failures must be an integer."""
        from backend.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s.cv_fallback_min_dom_failures, int)

    def test_cv_fallback_enabled_is_bool(self):
        """cv_fallback_enabled must be a boolean."""
        from backend.config import get_settings

        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s.cv_fallback_enabled, bool)


# ---------------------------------------------------------------------------
# VQAState schema tests
# ---------------------------------------------------------------------------


class TestVQAStateSchema:
    """Verify VQAState includes cv_fallback fields and make_initial_state initializes them."""

    def test_vqa_state_has_cv_fallback_invocations(self):
        """VQAState TypedDict must declare cv_fallback_invocations."""
        from backend.engine.state import VQAState

        hints = VQAState.__annotations__
        assert "cv_fallback_invocations" in hints, "VQAState missing cv_fallback_invocations"

    def test_vqa_state_has_cv_fallback_results(self):
        """VQAState TypedDict must declare cv_fallback_results."""
        from backend.engine.state import VQAState

        hints = VQAState.__annotations__
        assert "cv_fallback_results" in hints, "VQAState missing cv_fallback_results"

    def test_cv_fallback_results_uses_operator_add_reducer(self):
        """cv_fallback_results must be annotated with operator.add reducer for LangGraph append semantics."""
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState, include_extras=True)
        cv_results_annotation = hints.get("cv_fallback_results")
        assert cv_results_annotation is not None, "cv_fallback_results not found in type hints"
        # Annotated[list, operator.add] — check metadata contains operator.add
        metadata = getattr(cv_results_annotation, "__metadata__", ())
        assert operator.add in metadata, (
            f"cv_fallback_results must use Annotated[list, operator.add] reducer. Got metadata: {metadata}"
        )

    def test_make_initial_state_sets_cv_fallback_invocations_to_0(self):
        """make_initial_state() must initialize cv_fallback_invocations=0."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-test-001",
            jira_ticket_id="VC2-9999",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert state["cv_fallback_invocations"] == 0

    def test_make_initial_state_sets_cv_fallback_results_to_empty_list(self):
        """make_initial_state() must initialize cv_fallback_results=[]."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-test-002",
            jira_ticket_id="VC2-9999",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert state["cv_fallback_results"] == []

    def test_cv_fallback_invocations_is_int_in_initial_state(self):
        """cv_fallback_invocations must be int (not None) in initial state."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-test-003",
            jira_ticket_id="VC2-9999",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        assert isinstance(state["cv_fallback_invocations"], int)
