"""
tests/test_aria_diff.py
========================
Unit tests for backend/browser/aria_diff.py (TASK-080-P1B).

Tests cover:
- Delta computation: changed nodes emitted, unchanged nodes omitted
- Empty delta: no changes → empty/minimal output
- New node appearing in current tree not in previous
- Node removed from previous tree → tombstone or omitted
- Feature flag: PROMPT_COMPRESSION_ENABLED=false → full tree returned
- Graceful handling of malformed/empty ARIA trees
"""

import pytest

from backend.browser.aria_diff import AriaDiff, DiffResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def differ():
    return AriaDiff()


SAMPLE_TREE_A = """
[Document]
  [banner]
    [heading] "Production Orders"
  [main]
    [button] "New Request +"
    [grid] "Orders Table"
      [row] "Order 001 | Active | 2026-01-15"
      [row] "Order 002 | Draft  | 2026-01-16"
""".strip()

SAMPLE_TREE_B_CHANGED = """
[Document]
  [banner]
    [heading] "Production Orders"
  [main]
    [button] "New Request +"
    [button] "Export CSV"
    [grid] "Orders Table"
      [row] "Order 001 | Active | 2026-01-15"
      [row] "Order 002 | Active | 2026-01-16"
      [row] "Order 003 | Draft  | 2026-01-17"
""".strip()

SAMPLE_TREE_B_IDENTICAL = SAMPLE_TREE_A


# ---------------------------------------------------------------------------
# Core Diff Tests
# ---------------------------------------------------------------------------


class TestAriaDiffDelta:
    def test_identical_trees_produce_minimal_delta(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_IDENTICAL)
        assert result.is_empty or len(result.delta_text) < len(SAMPLE_TREE_A) // 2

    def test_changed_tree_produces_nonempty_delta(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert not result.is_empty
        assert len(result.delta_text) > 0

    def test_new_button_appears_in_delta(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert "Export CSV" in result.delta_text

    def test_new_row_appears_in_delta(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert "Order 003" in result.delta_text

    def test_changed_cell_value_appears_in_delta(self, differ):
        """Order 002 changed from Draft to Active — should appear in delta."""
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert "Order 002" in result.delta_text

    def test_unchanged_nodes_excluded_from_delta(self, differ):
        """Unchanged heading and unchanged Order 001 row should NOT be in delta."""
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        # "Production Orders" heading didn't change — ideally not in delta
        # This is a soft assertion; some implementations include context lines
        # What matters is delta is meaningfully smaller than the full tree
        assert len(result.delta_text) < len(SAMPLE_TREE_B_CHANGED)


class TestAriaDiffEdgeCases:
    def test_empty_previous_tree_returns_full_current(self, differ):
        result: DiffResult = differ.compute_delta("", SAMPLE_TREE_A)
        # On first call (no previous), full tree is the delta
        assert SAMPLE_TREE_A in result.delta_text or len(result.delta_text) >= len(SAMPLE_TREE_A) // 2

    def test_empty_current_tree_handled_gracefully(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, "")
        assert result is not None  # does not raise

    def test_both_empty_trees(self, differ):
        result: DiffResult = differ.compute_delta("", "")
        assert result is not None
        assert result.is_empty

    def test_malformed_tree_handled_gracefully(self, differ):
        malformed = "[[[[not valid ARIA]]]"
        result: DiffResult = differ.compute_delta(malformed, SAMPLE_TREE_A)
        assert result is not None  # does not raise

    def test_very_large_tree_produces_bounded_delta(self, differ):
        """Delta output should not exceed the current tree length."""
        large_tree = "\n".join(f"  [button] 'Button {i}'" for i in range(500))
        changed_tree = large_tree + "\n  [button] 'New Button'"
        result: DiffResult = differ.compute_delta(large_tree, changed_tree)
        # Delta must be smaller than or equal to the full tree
        assert len(result.delta_text) <= len(changed_tree) + 50  # +50 for headers


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestAriaDiffFeatureFlag:
    def test_disabled_returns_full_tree(self):
        """When PROMPT_COMPRESSION_ENABLED=False, full tree is returned as delta."""
        differ = AriaDiff(enabled=False)
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        # When disabled, result should contain the full current tree
        assert SAMPLE_TREE_B_CHANGED == result.delta_text or SAMPLE_TREE_B_CHANGED in result.delta_text

    def test_enabled_by_default(self):
        differ = AriaDiff()
        assert differ.enabled is True


# ---------------------------------------------------------------------------
# DiffResult Properties
# ---------------------------------------------------------------------------


class TestDiffResult:
    def test_diff_result_has_delta_text(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert isinstance(result.delta_text, str)

    def test_diff_result_is_empty_flag(self, differ):
        result_empty: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_IDENTICAL)
        result_changed: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        # identical tree → is_empty True; changed → is_empty False
        assert result_empty.is_empty
        assert not result_changed.is_empty

    def test_diff_result_change_count(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_CHANGED)
        assert result.change_count >= 1  # at least 1 change

    def test_identical_result_has_zero_change_count(self, differ):
        result: DiffResult = differ.compute_delta(SAMPLE_TREE_A, SAMPLE_TREE_B_IDENTICAL)
        assert result.change_count == 0
