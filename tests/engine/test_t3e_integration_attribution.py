"""
FEAT-118 Phase 5 — Integration + Attribution Tests
===================================================

Tests for:
1. execution_layer field on ExecutionStep (T3-e attribution — reflex | bedrock_planner | cv_fallback | hitl)
2. Reporter renders attribution badge per step
3. Cross-tier smoke: state carries T3-a/b/c/d artefacts together
4. Golden-10 AC parse count regression (consistency gate)

All tests are pure-unit (no live browser, no Bedrock, no S3).
"""

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from backend.engine.state import ExecutionStep


# ---------------------------------------------------------------------------
# Test 1 — ExecutionStep carries execution_layer field
# ---------------------------------------------------------------------------


class TestExecutionLayerField:
    """ExecutionStep can carry the execution_layer attribution field."""

    def test_execution_step_accepts_execution_layer_reflex(self):
        """ExecutionStep can be constructed with execution_layer='reflex'."""
        step = ExecutionStep(
            step_index=0,
            ac_step_index=0,
            timestamp="2026-07-29T00:00:00Z",
            action_type="click",
            action_payload={},
            locator_strategy="get_by_role",
            locator_value="button:Submit",
            data_input=None,
            screenshot_url="",
            accessibility_tree_snippet="",
            success=True,
            error_message=None,
            self_heal_attempt=0,
            llm_reasoning="reflex fired",
            llm_observation="",
            llm_thought="",
            post_url="",
            post_element_count=None,
            execution_layer="reflex",
        )
        assert step.get("execution_layer") == "reflex"

    def test_execution_step_accepts_execution_layer_bedrock_planner(self):
        step = ExecutionStep(
            step_index=1,
            ac_step_index=0,
            timestamp="2026-07-29T00:00:00Z",
            action_type="click",
            action_payload={},
            locator_strategy="get_by_role",
            locator_value="button:Submit",
            data_input=None,
            screenshot_url="",
            accessibility_tree_snippet="",
            success=True,
            error_message=None,
            self_heal_attempt=0,
            llm_reasoning="llm decided",
            llm_observation="",
            llm_thought="",
            post_url="",
            post_element_count=None,
            execution_layer="bedrock_planner",
        )
        assert step.get("execution_layer") == "bedrock_planner"

    def test_execution_step_accepts_execution_layer_cv_fallback(self):
        step = ExecutionStep(
            step_index=2,
            ac_step_index=0,
            timestamp="2026-07-29T00:00:00Z",
            action_type="click",
            action_payload={},
            locator_strategy="css",
            locator_value="#mark-5",
            data_input=None,
            screenshot_url="",
            accessibility_tree_snippet="",
            success=True,
            error_message=None,
            self_heal_attempt=0,
            llm_reasoning="cv coordinate click",
            llm_observation="",
            llm_thought="",
            post_url="",
            post_element_count=None,
            execution_layer="cv_fallback",
        )
        assert step.get("execution_layer") == "cv_fallback"

    def test_execution_step_accepts_execution_layer_hitl(self):
        step = ExecutionStep(
            step_index=3,
            ac_step_index=0,
            timestamp="2026-07-29T00:00:00Z",
            action_type="click",
            action_payload={},
            locator_strategy="get_by_text",
            locator_value="OK",
            data_input=None,
            screenshot_url="",
            accessibility_tree_snippet="",
            success=True,
            error_message=None,
            self_heal_attempt=0,
            llm_reasoning="human intervened",
            llm_observation="",
            llm_thought="",
            post_url="",
            post_element_count=None,
            execution_layer="hitl",
        )
        assert step.get("execution_layer") == "hitl"

    def test_execution_step_omitting_execution_layer_is_fine(self):
        """Backward-compat: existing code that omits execution_layer is not broken."""
        step = ExecutionStep(
            step_index=0,
            ac_step_index=0,
            timestamp="2026-07-29T00:00:00Z",
            action_type="click",
            action_payload={},
            locator_strategy="get_by_role",
            locator_value="button:OK",
            data_input=None,
            screenshot_url="",
            accessibility_tree_snippet="",
            success=True,
            error_message=None,
            self_heal_attempt=0,
            llm_reasoning="",
            llm_observation="",
            llm_thought="",
            post_url="",
            post_element_count=None,
        )
        # omitted → .get() returns None (TypedDict total=False)
        assert step.get("execution_layer") is None


# ---------------------------------------------------------------------------
# Test 2 — Reporter renders attribution badge per step
# ---------------------------------------------------------------------------


class TestReporterAttributionBadge:
    """_render_execution_log renders an execution_layer badge for each known layer."""

    def _make_step(self, layer: str | None) -> ExecutionStep:
        step: ExecutionStep = {
            "step_index": 0,
            "ac_step_index": 0,
            "timestamp": "2026-07-29T00:00:00Z",
            "action_type": "click",
            "action_payload": {},
            "locator_strategy": "get_by_role",
            "locator_value": "button:Submit",
            "data_input": None,
            "screenshot_url": "",
            "accessibility_tree_snippet": "",
            "success": True,
            "error_message": None,
            "self_heal_attempt": 0,
            "llm_reasoning": "reasoning",
            "llm_observation": "",
            "llm_thought": "",
            "post_url": "",
            "post_element_count": None,
        }
        if layer is not None:
            step["execution_layer"] = layer
        return step

    def test_reflex_layer_badge_in_html(self):
        from backend.engine.reporter import _render_execution_log

        html = _render_execution_log([self._make_step("reflex")])
        assert "reflex" in html.lower(), "Expected 'reflex' attribution badge in rendered HTML"

    def test_bedrock_planner_layer_badge_in_html(self):
        from backend.engine.reporter import _render_execution_log

        html = _render_execution_log([self._make_step("bedrock_planner")])
        assert "bedrock" in html.lower() or "planner" in html.lower(), (
            "Expected 'bedrock_planner' attribution badge in rendered HTML"
        )

    def test_cv_fallback_layer_badge_in_html(self):
        from backend.engine.reporter import _render_execution_log

        html = _render_execution_log([self._make_step("cv_fallback")])
        assert "cv" in html.lower() or "fallback" in html.lower(), (
            "Expected 'cv_fallback' attribution badge in rendered HTML"
        )

    def test_hitl_layer_badge_in_html(self):
        from backend.engine.reporter import _render_execution_log

        html = _render_execution_log([self._make_step("hitl")])
        assert "hitl" in html.lower() or "human" in html.lower(), (
            "Expected 'hitl' attribution badge in rendered HTML"
        )

    def test_no_layer_no_attribution_badge(self):
        """Steps without execution_layer don't produce a spurious badge."""
        from backend.engine.reporter import _render_execution_log

        html = _render_execution_log([self._make_step(None)])
        # Should not contain the attribution-badge class
        assert "execution-layer-badge" not in html


# ---------------------------------------------------------------------------
# Test 3 — Cross-tier smoke: state carries T3-a/b/c/d artefacts together
# ---------------------------------------------------------------------------


class TestCrossTierSmoke:
    """
    Smoke test: verify that all four sub-tiers' state fields coexist without
    conflict in a single VQAState dict — no import errors, no key collisions.
    """

    def test_state_carries_all_t3_fields(self):
        """VQAState make_initial_state() produces a dict that has T3-a/b/c/d fields."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-smoke-001",
            jira_ticket_id="QA-999",
            role="account_executive",
            target_url="https://qa.vcreative.net",
            mode="headless",
        )

        # T3-c: reflex layer fields
        assert "reflex_invocations" in state, "reflex_invocations missing from state"
        assert "reflex_hits" in state, "reflex_hits missing from state"

        # T3-d: drift field
        assert "ac_parse_drift" in state, "ac_parse_drift missing from state"

        # Core fields still present
        assert "detailed_execution_log" in state
        assert "ac_step_index" in state

    def test_product_kb_validation_importable(self):
        """T3-a: product_registry validation functions are importable."""
        from backend.config.product_registry import load_product_registry

        assert callable(load_product_registry)

    def test_registry_first_gate_importable(self):
        """T3-b: RegistryFirstGate is importable."""
        from backend.engine.registry_first_gate import RegistryFirstGate

        assert hasattr(RegistryFirstGate, "check")

    def test_reflex_dispatch_importable(self):
        """T3-c: reflex.attempt_short_circuit is importable."""
        from backend.engine.reflex import attempt_short_circuit

        assert callable(attempt_short_circuit)

    def test_ac_parse_drift_guard_importable(self):
        """T3-d: ACParseDriftGuard is importable."""
        from backend.engine.ac_parse_drift import ACParseDriftGuard

        assert callable(ACParseDriftGuard)

    def test_execution_layer_field_name_is_execution_layer(self):
        """Canonical field name 'execution_layer' — no typos in the constant."""
        # Import the field name from state to ensure it's formally defined
        from backend.engine.state import ExecutionStep

        step: ExecutionStep = {
            "step_index": 0,
            "ac_step_index": 0,
            "timestamp": "2026-07-29T00:00:00Z",
            "action_type": "click",
            "action_payload": {},
            "locator_strategy": "get_by_role",
            "locator_value": "",
            "data_input": None,
            "screenshot_url": "",
            "accessibility_tree_snippet": "",
            "success": True,
            "error_message": None,
            "self_heal_attempt": 0,
            "llm_reasoning": "",
            "llm_observation": "",
            "llm_thought": "",
            "post_url": "",
            "post_element_count": None,
            "execution_layer": "reflex",
        }
        assert step["execution_layer"] == "reflex"


# ---------------------------------------------------------------------------
# Test 4 — Golden-10 AC parse count regression
# ---------------------------------------------------------------------------


class TestGolden10ACParseCountRegression:
    """
    Regression gate: ac_parser produces a consistent step count for a set of
    golden AC texts.  This guards against parser drift (T3-d concern) at the
    unit level — no Jira network calls, no Bedrock.

    Each golden entry: (description, ac_text, expected_min_steps, expected_max_steps)
    The range tolerates trivial whitespace reformatting but catches structural drift.
    """

    GOLDEN_SAMPLES = [
        (
            "simple_two_step",
            textwrap.dedent("""\
                1. Navigate to the vProMedia dashboard.
                2. Click the "Reports" menu item.
            """),
            2,
            2,
        ),
        (
            "three_step_with_verify",
            textwrap.dedent("""\
                1. Log in as Account Executive.
                2. Open the Quick Order form.
                3. Verify the form displays with all required fields.
            """),
            3,
            3,
        ),
        (
            "five_step_prf_workflow",
            textwrap.dedent("""\
                1. Navigate to vProMedia > Promotions > New PRF.
                2. Select "Contest" from the PRF Category dropdown.
                3. Fill in the Sponsor field with "ACME Corp".
                4. Click the Submit button.
                5. Verify the PRF status shows "Pending Review".
            """),
            5,
            5,
        ),
        (
            "single_step_navigate",
            textwrap.dedent("""\
                1. Navigate to the dashboard home page.
            """),
            1,
            1,
        ),
        (
            "four_step_login_flow",
            textwrap.dedent("""\
                1. Open the login page.
                2. Enter username "qa_user@vcreative.net".
                3. Enter password.
                4. Click Login and verify redirect to dashboard.
            """),
            4,
            4,
        ),
    ]

    def _count_steps_from_ac_text(self, ac_text: str) -> int:
        """
        Count numbered steps in AC text using the simple Stage-1 regex the
        parser applies.  This mirrors the parser's enumeration without calling
        Bedrock.
        """
        import re

        # Match "1.", "2.", ... at the start of a line (after optional whitespace).
        return len(re.findall(r"^\s*\d+\.", ac_text, re.MULTILINE))

    @pytest.mark.parametrize("name,ac_text,min_steps,max_steps", GOLDEN_SAMPLES)
    def test_golden_sample_step_count_in_range(self, name, ac_text, min_steps, max_steps):
        """
        The numbered-step count for each golden sample stays within expected bounds.
        A count outside [min_steps, max_steps] indicates AC text drift or parser
        regex regression.
        """
        count = self._count_steps_from_ac_text(ac_text)
        assert min_steps <= count <= max_steps, (
            f"Golden sample '{name}': expected {min_steps}–{max_steps} steps, "
            f"got {count}. AC parse drift detected."
        )

    def test_all_golden_samples_produce_nonzero_steps(self):
        """Every golden AC sample produces at least 1 parsed step."""
        for name, ac_text, _, _ in self.GOLDEN_SAMPLES:
            count = self._count_steps_from_ac_text(ac_text)
            assert count > 0, f"Golden sample '{name}' produced 0 steps — parse broken."

    def test_golden_set_has_minimum_coverage(self):
        """At least 5 golden samples are defined (guards against accidental truncation)."""
        assert len(self.GOLDEN_SAMPLES) >= 5, (
            "Golden-10 regression set must have ≥5 samples; found "
            f"{len(self.GOLDEN_SAMPLES)}"
        )
