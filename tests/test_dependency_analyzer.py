"""
tests/test_dependency_analyzer.py
===================================
Unit tests for backend/engine/dependency_analyzer.py (TASK-080-P3A).

Tests cover:
- READ-only action types build parallel groups
- WRITE actions serialize (one group per step)
- Mixed sequences: WRITE flushes pending read group
- Edge cases: empty list, all-WRITE, all-READ, trailing reads
- Feature flag: PARALLEL_STEPS_ENABLED=false → all sequential groups
- Invariant: every step index appears exactly once across all groups
- Unknown/None action_type falls through to WRITE (conservative default)
- Logging: parallel block count is logged at INFO level

AC Coverage:
- AC-EDGE-2: Steps with shared write state → serialized (sequential groups)
- AC-ENTRY-1: PARALLEL_STEPS_ENABLED=false → sequential fallback, zero regression
- AC-NFR-1: Conservative approach ensures ≥ 90% AC step pass rate
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Stub TestStep (mirrors StructuredACStep.step_type field)
# ---------------------------------------------------------------------------


@dataclass
class StubStep:
    """Minimal stand-in for StructuredACStep with step_type field."""

    step_type: Optional[str] = None


def _make_steps(*step_types: Optional[str]) -> list[StubStep]:
    """Convenience factory — returns a list of StubStep objects."""
    return [StubStep(step_type=t) for t in step_types]


# ---------------------------------------------------------------------------
# Helper: verify the invariant directly
# ---------------------------------------------------------------------------


def _assert_invariant(steps: list, groups: list[list[int]]) -> None:
    """All step indices appear exactly once across all groups."""
    flat = [i for g in groups for i in g]
    assert sorted(flat) == list(range(len(steps))), (
        f"Invariant violated: expected {list(range(len(steps)))}, got {sorted(flat)}"
    )


# ---------------------------------------------------------------------------
# Tests: READ-only classification
# ---------------------------------------------------------------------------


class TestReadOnlyActions:
    """VERIFY_ONLY steps should be grouped into parallel blocks."""

    def test_single_verify_step_forms_single_group(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0]]
        _assert_invariant(steps, groups)

    @pytest.mark.parametrize(
        "read_type",
        ["VERIFY_ONLY", "verify_only", "VERIFY_TABLE_SORT"],
    )
    def test_read_type_variants_are_recognized(self, read_type):
        """Step types are case-normalized before classification."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(read_type, read_type)
        groups = build_parallel_groups(steps, enabled=True)
        # Both should be in one parallel group
        assert len(groups) == 1
        assert set(groups[0]) == {0, 1}
        _assert_invariant(steps, groups)

    def test_three_consecutive_verify_steps_form_one_parallel_group(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0, 1, 2]]
        _assert_invariant(steps, groups)

    def test_all_verify_steps_form_single_parallel_group(self):
        """All-READ list → one group containing all step indices."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "VERIFY_ONLY", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert len(groups) == 1
        assert sorted(groups[0]) == [0, 1, 2, 3]
        _assert_invariant(steps, groups)


# ---------------------------------------------------------------------------
# Tests: WRITE action serialization
# ---------------------------------------------------------------------------


class TestWriteActions:
    """WRITE steps must always be serialized — one group per step."""

    @pytest.mark.parametrize(
        "write_type",
        ["CLICK", "FILL", "NAVIGATE", "SELECT_DROPDOWN", "TOGGLE_CHECKBOX",
         "DATE_SELECT", "SORT_COLUMN", "ACCOUNT_SWITCH", "PERSONA_SWITCH"],
    )
    def test_write_step_always_sequential(self, write_type):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(write_type)
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0]]
        _assert_invariant(steps, groups)

    def test_three_write_steps_each_get_own_group(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("CLICK", "FILL", "NAVIGATE")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0], [1], [2]]
        _assert_invariant(steps, groups)

    def test_all_write_steps_all_sequential(self):
        """No read steps → fully sequential plan."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("CLICK", "FILL", "CLICK", "NAVIGATE", "FILL")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0], [1], [2], [3], [4]]
        _assert_invariant(steps, groups)


# ---------------------------------------------------------------------------
# Tests: Mixed sequences (AC-EDGE-2)
# ---------------------------------------------------------------------------


class TestMixedSequences:
    """AC-EDGE-2: Dependent steps must be serialized; independent parallelized."""

    def test_write_then_read_then_read(self):
        """[FILL, VERIFY, VERIFY] → [[0], [1, 2]]"""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("FILL", "VERIFY_ONLY", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0], [1, 2]]
        _assert_invariant(steps, groups)

    def test_read_then_write_flushes_read_group(self):
        """[VERIFY, VERIFY, CLICK] → [[0, 1], [2]]"""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "CLICK")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0, 1], [2]]
        _assert_invariant(steps, groups)

    def test_write_between_two_read_blocks(self):
        """[VERIFY, VERIFY, CLICK, VERIFY, VERIFY] → [[0,1], [2], [3,4]]"""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "CLICK", "VERIFY_ONLY", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0, 1], [2], [3, 4]]
        _assert_invariant(steps, groups)

    def test_alternating_read_write(self):
        """[VERIFY, CLICK, VERIFY, CLICK] → [[0], [1], [2], [3]]"""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "CLICK", "VERIFY_ONLY", "CLICK")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0], [1], [2], [3]]
        _assert_invariant(steps, groups)

    def test_ac_edge2_scenario_six_steps(self):
        """
        AC-EDGE-2: 6 steps where steps 3+4 depend on step 2.
        Steps 3 and 4 are CLICK (WRITE) — should each get own sequential group.
        No cross-contamination from parallel execution.

        [FILL, FILL, CLICK, CLICK, VERIFY, VERIFY]
        → [[0], [1], [2], [3], [4, 5]]
        """
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("FILL", "FILL", "CLICK", "CLICK", "VERIFY_ONLY", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0], [1], [2], [3], [4, 5]]
        _assert_invariant(steps, groups)

    def test_long_sequence_with_multiple_read_blocks(self):
        """Complex mix: verify that invariant holds for longer sequences."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        # [V, V, W, V, W, W, V, V, V, W]
        # → [[0,1], [2], [3], [4], [5], [6,7,8], [9]]
        steps = _make_steps(
            "VERIFY_ONLY", "VERIFY_ONLY",   # group 0: [0,1]
            "CLICK",                          # group 1: [2]
            "VERIFY_ONLY",                    # group 2: [3]
            "FILL",                           # group 3: [4]
            "NAVIGATE",                       # group 4: [5]
            "VERIFY_ONLY", "VERIFY_ONLY", "VERIFY_ONLY",  # group 5: [6,7,8]
            "CLICK",                          # group 6: [9]
        )
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0, 1], [2], [3], [4], [5], [6, 7, 8], [9]]
        _assert_invariant(steps, groups)


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions the algorithm must handle correctly."""

    def test_empty_step_list_returns_empty_groups(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        groups = build_parallel_groups([], enabled=True)
        assert groups == []

    def test_single_write_step(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("CLICK")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0]]
        _assert_invariant(steps, groups)

    def test_single_read_step(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        assert groups == [[0]]
        _assert_invariant(steps, groups)

    def test_none_step_type_treated_as_write(self):
        """None action_type → conservative WRITE (unknown = sequential)."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(None, "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        # None treated as WRITE → [[0], [1]]
        assert groups == [[0], [1]]
        _assert_invariant(steps, groups)

    def test_unknown_step_type_treated_as_write(self):
        """Unknown step_type → conservative WRITE (default to sequential)."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("SOME_UNKNOWN_TYPE", "VERIFY_ONLY")
        groups = build_parallel_groups(steps, enabled=True)
        # Unknown → WRITE → [[0], [1]]
        assert groups == [[0], [1]]
        _assert_invariant(steps, groups)

    def test_dict_based_step_without_step_type_treated_as_write(self):
        """Dict steps without step_type key → conservative WRITE."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps_dicts = [{"goal": "do thing"}, {"step_type": "VERIFY_ONLY"}]
        groups = build_parallel_groups(steps_dicts, enabled=True)  # type: ignore[arg-type]
        assert groups == [[0], [1]]
        _assert_invariant(steps_dicts, groups)

    def test_dict_with_verify_step_type_is_read(self):
        """Dict steps with step_type=VERIFY_ONLY → READ (parallel)."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps_dicts = [{"step_type": "VERIFY_ONLY"}, {"step_type": "VERIFY_ONLY"}]
        groups = build_parallel_groups(steps_dicts, enabled=True)  # type: ignore[arg-type]
        assert groups == [[0, 1]]
        _assert_invariant(steps_dicts, groups)


# ---------------------------------------------------------------------------
# Tests: Feature Flag (AC-ENTRY-1)
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """AC-ENTRY-1: PARALLEL_STEPS_ENABLED=false → all sequential, zero regression."""

    def test_disabled_returns_sequential_for_all_verify_steps(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "VERIFY_ONLY")
        # Feature flag OFF
        groups = build_parallel_groups(steps, enabled=False)
        assert groups == [[0], [1], [2]]
        _assert_invariant(steps, groups)

    def test_disabled_returns_sequential_for_mixed_steps(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("FILL", "VERIFY_ONLY", "VERIFY_ONLY", "CLICK")
        groups = build_parallel_groups(steps, enabled=False)
        assert groups == [[0], [1], [2], [3]]
        _assert_invariant(steps, groups)

    def test_disabled_returns_sequential_for_empty_list(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        groups = build_parallel_groups([], enabled=False)
        assert groups == []

    def test_disabled_does_not_call_classifier(self):
        """When disabled, step_type is irrelevant — all steps are sequential."""
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(None, None, None)  # All None — but flag is off
        groups = build_parallel_groups(steps, enabled=False)
        assert groups == [[0], [1], [2]]
        _assert_invariant(steps, groups)


# ---------------------------------------------------------------------------
# Tests: Invariant
# ---------------------------------------------------------------------------


class TestInvariant:
    """Every step index must appear exactly once across all groups."""

    @pytest.mark.parametrize("n", [1, 2, 5, 10, 20])
    def test_all_write_steps_invariant(self, n):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(*["CLICK"] * n)
        groups = build_parallel_groups(steps, enabled=True)
        _assert_invariant(steps, groups)

    @pytest.mark.parametrize("n", [1, 2, 5, 10, 20])
    def test_all_read_steps_invariant(self, n):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(*["VERIFY_ONLY"] * n)
        groups = build_parallel_groups(steps, enabled=True)
        _assert_invariant(steps, groups)

    def test_complex_mixed_sequence_invariant(self):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps(
            "FILL", "CLICK", "VERIFY_ONLY", "VERIFY_ONLY",
            "FILL", "NAVIGATE", "VERIFY_ONLY", "CLICK",
        )
        groups = build_parallel_groups(steps, enabled=True)
        _assert_invariant(steps, groups)


# ---------------------------------------------------------------------------
# Tests: Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """DependencyAnalyzer logs parallel block info at INFO level."""

    def test_logs_parallel_info_when_enabled(self, caplog):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY", "CLICK")
        with caplog.at_level(logging.INFO, logger="backend.engine.dependency_analyzer"):
            build_parallel_groups(steps, enabled=True)
        assert any("parallel" in r.message.lower() or "group" in r.message.lower()
                   for r in caplog.records)

    def test_logs_debug_when_disabled(self, caplog):
        from backend.engine.dependency_analyzer import build_parallel_groups

        steps = _make_steps("VERIFY_ONLY", "VERIFY_ONLY")
        with caplog.at_level(logging.DEBUG, logger="backend.engine.dependency_analyzer"):
            build_parallel_groups(steps, enabled=False)
        assert any("sequential" in r.message.lower() or "disabled" in r.message.lower()
                   for r in caplog.records)
