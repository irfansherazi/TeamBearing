"""
vQA — AC Quality Gate Tests
==============================
Module: backend/engine/test_ac_quality_gate.py

FEAT-001: Comprehensive test suite for the AC quality scorer.
Tests cover:
  - Score calibration (high/medium/low quality ACs)
  - Per-dimension scoring accuracy
  - Step splitting edge cases
  - Integration with the validator pipeline
"""

from backend.engine.ac_quality_gate import (
    _score_actionability,
    _score_observable_outcome,
    _score_precondition_clarity,
    _score_scope_atomicity,
    _score_specificity,
    split_ac_into_steps,
    score_ac_quality,
)
from backend.engine.validators import validate_ac_steps

# ---------------------------------------------------------------------------
# Score calibration tests
# ---------------------------------------------------------------------------


class TestScoreCalibration:
    """Verify that the overall scorer produces correct grades for different AC quality levels."""

    def test_high_quality_ac_scores_7_plus(self):
        """AC with named components, specific outcomes, clear preconditions → ≥7."""
        ac = """
1. On the Production Orders page in compact view, click the 'Client Name' column header
2. Verify the table rows are sorted ascending (A-Z) by client name
3. Click the 'Client Name' column header again
4. Verify the table rows are sorted descending (Z-A) by client name
5. Verify the p-table sort icon shows a downward arrow
        """
        result = score_ac_quality(ac)
        assert result.overall_score >= 7, (
            f"High-quality AC scored {result.overall_score}/10, expected ≥7. Dims: {result.dimension_scores}"
        )
        assert result.quality_grade == "good"

    def test_medium_quality_ac_scores_4_to_6(self):
        """AC with generic components, vague outcomes → 4-6."""
        ac = """
1. The user can sort the table by clicking a column header
2. Verify the page updates after sorting
3. Click the dropdown and select an option
        """
        result = score_ac_quality(ac)
        assert 4 <= result.overall_score <= 6, (
            f"Medium-quality AC scored {result.overall_score}/10, expected 4-6. Dims: {result.dimension_scores}"
        )
        assert result.quality_grade == "fair"

    def test_low_quality_ac_scores_below_4(self):
        """AC with no components, no outcomes, passive voice → <4."""
        ac = "Everything should be working and functioning as expected"
        result = score_ac_quality(ac)
        assert result.overall_score < 4, (
            f"Low-quality AC scored {result.overall_score}/10, expected <4. Dims: {result.dimension_scores}"
        )
        assert result.quality_grade == "poor"

    def test_empty_ac_scores_zero(self):
        """Empty string → 0."""
        result = score_ac_quality("")
        assert result.overall_score == 0
        assert result.quality_grade == "poor"
        assert len(result.warnings) > 0

    def test_whitespace_only_ac_scores_zero(self):
        """Whitespace-only string → 0."""
        result = score_ac_quality("   \n\t  ")
        assert result.overall_score == 0
        assert result.quality_grade == "poor"

    def test_multi_step_ac_returns_per_step_scores(self):
        """AC with 3 numbered steps → 3 individual scores."""
        ac = """
1. Click the Submit All button on the Quick Order form
2. Verify success toast appears
3. Navigate to the dashboard
        """
        result = score_ac_quality(ac)
        assert len(result.step_scores) == 3
        for step_result in result.step_scores:
            assert "score" in step_result
            assert "dimension_scores" in step_result
            assert "warnings" in step_result


# ---------------------------------------------------------------------------
# Dimension-specific tests
# ---------------------------------------------------------------------------


class TestSpecificity:
    """Test the specificity dimension scorer."""

    def test_detects_primeng_component(self):
        """'Click the p-select dropdown' → specificity=2."""
        score, warnings = _score_specificity("Click the p-select Sort By dropdown")
        assert score == 2
        assert len(warnings) == 0

    def test_detects_named_button(self):
        """'Click the Submit All button' → specificity=2."""
        score, warnings = _score_specificity("Click the Submit All button")
        assert score == 2

    def test_detects_generic_reference(self):
        """'Click the button' → specificity=1."""
        score, warnings = _score_specificity("Click the button")
        assert score == 1
        assert len(warnings) > 0

    def test_no_component_reference(self):
        """'Sort the data' → specificity=0."""
        score, warnings = _score_specificity("Sort the data")
        assert score == 0
        assert len(warnings) > 0


class TestObservableOutcome:
    """Test the observable outcome dimension scorer."""

    def test_detects_toast(self):
        """'Verify success toast appears' → outcome=2."""
        score, _ = _score_observable_outcome("Verify the success toast appears")
        assert score == 2

    def test_detects_url_change(self):
        """'Verify URL changes to /orders' → outcome=2."""
        score, _ = _score_observable_outcome("Verify URL changes to /orders")
        assert score == 2

    def test_detects_element_visibility(self):
        """'Verify the modal is visible' → outcome=2."""
        score, _ = _score_observable_outcome("Verify the modal is visible")
        assert score == 2

    def test_flags_vague_outcome(self):
        """'Verify it works correctly' → outcome=0."""
        score, warnings = _score_observable_outcome("Verify it works correctly")
        assert score == 0
        assert len(warnings) > 0

    def test_action_step_without_outcome_gets_1(self):
        """'Click the Submit button' → outcome=1 (action, not verify)."""
        score, _ = _score_observable_outcome("Click the Submit button")
        assert score == 1


class TestActionability:
    """Test the actionability dimension scorer."""

    def test_specific_verb_click(self):
        """'Click the button' → actionability=2."""
        score, _ = _score_actionability("Click the Submit All button")
        assert score == 2

    def test_specific_verb_navigate(self):
        """'Navigate to /dashboard' → actionability=2."""
        score, _ = _score_actionability("Navigate to the dashboard page")
        assert score == 2

    def test_generic_verb_verify(self):
        """'Verify the page' → actionability=1."""
        score, warnings = _score_actionability("Verify the page loads")
        assert score == 1
        assert len(warnings) > 0

    def test_passive_voice(self):
        """'The data should be sorted' → actionability=0."""
        score, warnings = _score_actionability("The data should be sorted")
        assert score == 0
        assert len(warnings) > 0


class TestPreconditionClarity:
    """Test the precondition clarity dimension scorer."""

    def test_explicit_precondition(self):
        """'On the Production Orders page...' → precondition=2."""
        score, _ = _score_precondition_clarity("On the Production Orders page, click the Client column")
        assert score == 2

    def test_logged_in_precondition(self):
        """'Logged in as Account Executive' → precondition=2."""
        score, _ = _score_precondition_clarity("Logged in as Account Executive, navigate to orders")
        assert score == 2

    def test_implied_precondition(self):
        """'The user can sort...' → precondition=1."""
        score, warnings = _score_precondition_clarity("The user can sort the table")
        assert score == 1
        assert len(warnings) > 0

    def test_no_precondition(self):
        """'Sort ascending' → precondition=0."""
        score, warnings = _score_precondition_clarity("Sort ascending")
        assert score == 0
        assert len(warnings) > 0


class TestScopeAtomicity:
    """Test the scope atomicity dimension scorer."""

    def test_single_action(self):
        """'Click the Submit button' → atomicity=2."""
        score, _ = _score_scope_atomicity("Click the Submit button")
        assert score == 2

    def test_two_actions_joined_by_and(self):
        """'Click submit and verify toast' → atomicity=1."""
        score, warnings = _score_scope_atomicity("Click submit and verify the success toast")
        assert score == 1
        assert len(warnings) > 0

    def test_three_actions_joined_by_and(self):
        """'Click submit and verify toast and check URL' → atomicity=0."""
        score, warnings = _score_scope_atomicity("Click submit and verify the toast and navigate to dashboard")
        assert score == 0
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# Step splitting tests
# ---------------------------------------------------------------------------


class TestStepSplitting:
    """Test the split_ac_into_steps helper."""

    def test_numbered_list(self):
        steps = split_ac_into_steps("1. Step one\n2. Step two\n3. Step three")
        assert len(steps) == 3

    def test_bulleted_list(self):
        steps = split_ac_into_steps("- Step one\n- Step two\n- Step three")
        assert len(steps) == 3

    def test_newline_separated(self):
        steps = split_ac_into_steps("Step one\nStep two\nStep three")
        assert len(steps) == 3

    def test_single_block(self):
        steps = split_ac_into_steps("Just one single step here")
        assert len(steps) == 1

    def test_empty_string(self):
        steps = split_ac_into_steps("")
        assert len(steps) == 0

    def test_checkbox_format(self):
        steps = split_ac_into_steps("[] Step one\n[] Step two\n[x] Step three")
        assert len(steps) == 3


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests ensuring quality gate works with the validator pipeline."""

    def test_quality_gate_does_not_reject_good_ac(self):
        """Good AC → grade='good', no warnings preventing execution."""
        ac = """
1. On Production Orders compact view, click the 'Client Name' column header
2. Verify the p-table rows are sorted ascending (A-Z) by client name
3. Click the 'Client Name' column header again
4. Verify the p-table rows are sorted descending (Z-A) by client name
        """
        result = score_ac_quality(ac)
        assert result.quality_grade in ("good", "fair")
        assert result.overall_score >= 4

    def test_quality_gate_warns_on_poor_ac(self):
        """Poor AC → grade='poor', warnings non-empty."""
        ac = "The table should sort correctly and function as expected"
        result = score_ac_quality(ac)
        assert result.quality_grade == "poor"
        assert len(result.warnings) > 0

    def test_to_dict_serialization(self):
        """ACQualityResult.to_dict() produces a valid dict for state storage."""
        result = score_ac_quality("Click the Submit All button on the Quick Order form")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "overall_score" in d
        assert "dimension_scores" in d
        assert "quality_grade" in d
        assert "warnings" in d
        assert "step_scores" in d

    def test_validators_component_specificity_check(self):
        """Semantic validator flags 'Click the button' → warning."""
        steps = [
            "Click the button",
            "Click the Submit All button",
        ]
        valid, errors, warnings = validate_ac_steps(steps)
        # "Click the button" should trigger a specificity warning
        assert any("specificity" in w.lower() for w in warnings), f"Expected specificity warning, got: {warnings}"

    def test_validators_observable_outcome_check(self):
        """Semantic validator flags 'Verify the page loads' → warning."""
        steps = [
            "Verify the page loads",
            "Verify the success toast appears",
        ]
        valid, errors, warnings = validate_ac_steps(steps)
        # "Verify the page loads" should trigger an observable outcome warning
        assert any("observable" in w.lower() for w in warnings), f"Expected observable outcome warning, got: {warnings}"

    def test_validators_backward_compat_valid_steps(self):
        """Existing valid steps still pass without errors."""
        steps = [
            "Click the Submit All button",
            "Verify the success toast appears with text 'Order saved'",
            "Navigate to the Production Orders page",
        ]
        valid, errors, warnings = validate_ac_steps(steps)
        assert len(valid) == 3
        assert len(errors) == 0
