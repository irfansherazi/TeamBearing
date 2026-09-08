"""
TASK-048 — Unit tests for COVERAGE_GAP reporter fix.

Tests:
  1. _render_header with COVERAGE_GAP → badge shows "FAILED ✗", "3/4 passed"
  2. _render_header with no COVERAGE_GAP → badge shows "PASSED ✓", "4/4 passed"
  3. _render_ac_table with COVERAGE_GAP at index 3 → 4th row has class="fail" and ✗
  4. _render_ac_table with no gaps → all rows pass (regression guard)
  5. Edge case: COVERAGE_GAP at index 0 → header and table both fail at first step
"""

# We import the two private helpers directly; they accept plain dicts that
# satisfy the VQAState TypedDict signature so no mocking is required.
from backend.engine.reporter import _render_ac_table, _render_header

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    ac_steps: list[str],
    completed: list[int],
    bug_log: list[dict] | None = None,
    skipped: list[int] | None = None,
    **kwargs,
) -> dict:
    """Build a minimal VQAState-compatible dict for reporter tests."""
    state = {
        "jira_ticket": {
            "ticket_id": "QA-298",
            "summary": "Test summary",
            "acceptance_criteria_steps": ac_steps,
        },
        "role_context": {"role_name": "Account Executive"},
        "ac_steps_completed": completed,
        "ac_steps_skipped": skipped or [],
        "detailed_execution_log": [],
        "bug_log": bug_log or [],
        "run_id": "run-1b6e49c7",
    }
    state.update(kwargs)
    return state


def _coverage_gap_bug(ac_step_index: int) -> dict:
    return {
        "type": "COVERAGE_GAP",
        "description": f"AC step {ac_step_index + 1}/4 was never executed",
        "severity": "HIGH",
        "ac_step_index": ac_step_index,
    }


# ---------------------------------------------------------------------------
# _render_header tests
# ---------------------------------------------------------------------------


class TestRenderHeaderCoverageGap:
    """AC-HAPPY-1 and AC-HAPPY-2: header badge and AC step count."""

    def test_coverage_gap_shows_failed_badge(self):
        """AC-HAPPY-1: COVERAGE_GAP entry → header badge reads 'FAILED ✗'."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        # All 4 indices appear in completed (as the evaluator does) but step 3 has a gap.
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            ac_steps_coverage_gap=[3],  # TASK-054
            bug_log=[_coverage_gap_bug(3)],
        )
        html = _render_header(state, duration_ms=5000)
        assert "FAILED ✗" in html, "Expected 'FAILED ✗' badge when COVERAGE_GAP present"
        assert "PASSED ✓" not in html, "Must NOT show 'PASSED ✓' when COVERAGE_GAP present"

    def test_coverage_gap_shows_correct_passed_count(self):
        """AC-HAPPY-2: COVERAGE_GAP at step 3 → '3/4 passed', not '4/4 passed'."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            ac_steps_coverage_gap=[3],  # TASK-054
            bug_log=[_coverage_gap_bug(3)],
        )
        html = _render_header(state, duration_ms=5000)
        assert "3/4 passed" in html, "Expected '3/4 passed' when one step has COVERAGE_GAP"
        assert "4/4 passed" not in html, "Must NOT show '4/4 passed' with a COVERAGE_GAP"

    def test_no_coverage_gap_shows_passed_badge(self):
        """AC-HAPPY-4: No COVERAGE_GAP → 'PASSED ✓', '4/4 passed' (no regression)."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            bug_log=[],
        )
        html = _render_header(state, duration_ms=5000)
        assert "PASSED ✓" in html, "Expected 'PASSED ✓' when no COVERAGE_GAP"
        assert "4/4 passed" in html, "Expected '4/4 passed' when all steps completed"

    def test_coverage_gap_at_index_0_shows_failed(self):
        """Edge case: COVERAGE_GAP at first step → header FAILED and '0/4 passed'."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        # evaluator appended 0 to completed but it's a gap
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            ac_steps_coverage_gap=[0],  # TASK-054
            bug_log=[_coverage_gap_bug(0)],
        )
        html = _render_header(state, duration_ms=5000)
        assert "FAILED ✗" in html
        assert "3/4 passed" in html, "3 remaining steps counted (indices 1,2,3)"

    def test_non_coverage_gap_bugs_do_not_affect_all_passed(self):
        """Other bug types (UI, LOGIC, API, QA, MEM) must NOT affect all_passed."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            bug_log=[
                {"type": "UI", "description": "Button misaligned", "severity": "LOW"},
                {"type": "LOGIC", "description": "Wrong value", "severity": "HIGH"},
            ],
        )
        html = _render_header(state, duration_ms=5000)
        # Non-COVERAGE_GAP bugs must not flip the badge to FAILED
        assert "PASSED ✓" in html, "Non-COVERAGE_GAP bugs must not make all_passed=False"
        assert "4/4 passed" in html


# ---------------------------------------------------------------------------
# _render_ac_table tests
# ---------------------------------------------------------------------------


class TestRenderAcTableCoverageGap:
    """AC-HAPPY-3 and AC-REGRESS-2: AC table row rendering."""

    def test_coverage_gap_step_renders_as_fail(self):
        """AC-HAPPY-3: COVERAGE_GAP at index 3 → row class='fail' and ✗ icon."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            ac_steps_coverage_gap=[3],  # TASK-054
            bug_log=[_coverage_gap_bug(3)],
        )
        html = _render_ac_table(state)
        # The failing row must contain class="fail"
        assert 'class="fail"' in html, "Expected class='fail' for COVERAGE_GAP row"
        # Ensure ✗ appears (for the gap row)
        assert "✗" in html

    def test_no_coverage_gap_all_rows_pass(self):
        """AC-HAPPY-4 / AC-REGRESS-1: No gap → all rows have class='pass' and ✓."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            bug_log=[],
        )
        html = _render_ac_table(state)
        # No fail rows
        assert 'class="fail"' not in html, "No rows should be 'fail' without COVERAGE_GAP"
        # ✗ should not appear
        assert "✗" not in html

    def test_coverage_gap_at_index_0_first_row_fails(self):
        """Edge case: COVERAGE_GAP at index 0 → first row class='fail'."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2, 3],
            ac_steps_coverage_gap=[0],  # TASK-054
            bug_log=[_coverage_gap_bug(0)],
        )
        html = _render_ac_table(state)
        assert 'class="fail"' in html
        assert "✗" in html

    def test_skipped_steps_still_render_as_skip(self):
        """AC-REGRESS-2: Skipped steps still render with 'skip' class and ⊘ icon."""
        ac_steps = ["Step A", "Step B", "Step C", "Step D"]
        # Step 3 is skipped (budget exceeded), no COVERAGE_GAP
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1, 2],
            skipped=[3],
            bug_log=[],
        )
        html = _render_ac_table(state)
        assert 'class="skip"' in html, "Skipped steps must still render as 'skip'"
        assert "⊘" in html, "Skipped steps must show ⊘ icon"
        # Skipped step must not be treated as fail or pass
        assert 'class="fail"' not in html

    def test_coverage_gap_overrides_completed_membership(self):
        """
        A step that is both in ac_steps_completed AND has a COVERAGE_GAP bug
        must render as fail (gap takes priority over completed membership).
        """
        ac_steps = ["Step A", "Step B"]
        # index 1 is in completed AND has a COVERAGE_GAP
        state = _make_state(
            ac_steps=ac_steps,
            completed=[0, 1],
            ac_steps_coverage_gap=[1],  # TASK-054
            bug_log=[_coverage_gap_bug(1)],
        )
        html = _render_ac_table(state)
        assert 'class="fail"' in html, "COVERAGE_GAP must override completed membership"
