"""
Phase 3 (accessibility-tree-grounding) — AC-parser ARIA Enrichment Tests
=========================================================================

Tests for ``backend/engine/ac_aria_enricher.py`` — the post-compilation
deterministic Python pass that populates ``aria_role`` and ``aria_name`` on
each ``TestPlanStep`` dict from the live ARIA snapshot.

Architecture Decision 2: Enrichment runs as a post-compile Python pass
invoked from ``planner_node`` on first entry (post-login), NOT inside
``ac_parser_node`` (which has no live ARIA tree).

Coverage mapped to AC-VERIFY-2:
  "When a target_component string from the parsed test plan matches an element
  visible in the current ARIA tree, the resulting TestPlanStep carries
  non-empty aria_role and aria_name values derived from the ARIA snapshot."

Run: python -m pytest tests/test_ac_parser_a11y_enrichment.py -v
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_aria_snapshot():
    """A realistic PrimeNG ARIA tree with a mix of roles and names."""
    return {
        "role": "WebArea",
        "name": "vSuite Production Orders",
        "children": [
            {
                "role": "navigation",
                "name": "Main Navigation",
                "children": [
                    {"role": "link", "name": "Production Orders", "children": []},
                ],
            },
            {
                "role": "toolbar",
                "name": "Actions",
                "children": [
                    {"role": "button", "name": "Save", "children": []},
                    {"role": "button", "name": "Cancel", "children": []},
                    {"role": "button", "name": "Sort ▾", "children": []},  # trailing icon
                ],
            },
            {
                "role": "main",
                "name": "Content",
                "children": [
                    {
                        "role": "textbox",
                        "name": "Search",
                        "children": [],
                    },
                    {
                        "role": "combobox",
                        "name": "Status Filter",
                        "children": [],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def mock_page_with_aria(sample_aria_snapshot):
    """A Playwright Page mock that returns the sample ARIA snapshot."""
    page = AsyncMock()
    page.accessibility = AsyncMock()
    page.accessibility.snapshot = AsyncMock(return_value=sample_aria_snapshot)
    return page


@pytest.fixture
def mock_page_empty_aria():
    """A Playwright Page mock that returns an empty ARIA tree."""
    page = AsyncMock()
    page.accessibility = AsyncMock()
    page.accessibility.snapshot = AsyncMock(return_value=None)
    return page


@pytest.fixture
def mock_page_snapshot_raises():
    """A Playwright Page mock where accessibility.snapshot raises."""
    page = AsyncMock()
    page.accessibility = AsyncMock()
    page.accessibility.snapshot = AsyncMock(
        side_effect=RuntimeError("CDP error: page closed")
    )
    return page


def _make_test_plan(*target_components: str) -> dict:
    """Build a minimal test plan dict with the given target_component values."""
    return {
        "steps": [
            {
                "step_index": i,
                "target_component": tc,
                "action_type": "click",
            }
            for i, tc in enumerate(target_components)
        ]
    }


# ---------------------------------------------------------------------------
# Tests: _flatten_aria_tree
# ---------------------------------------------------------------------------


class TestFlattenAriaTree:
    """Unit tests for the internal ARIA tree flattener."""

    def test_flattens_nested_tree(self, sample_aria_snapshot):
        """All role/name nodes in the tree are flattened into a list."""
        from backend.engine.ac_aria_enricher import _flatten_aria_tree

        result = []
        _flatten_aria_tree(sample_aria_snapshot, result)

        roles = [n["role"] for n in result]
        names = [n["name"] for n in result]

        assert "button" in roles
        assert "Save" in names
        assert "textbox" in roles
        assert "Search" in names

    def test_empty_children_node_included(self):
        """Leaf nodes with empty children list are included."""
        from backend.engine.ac_aria_enricher import _flatten_aria_tree

        node = {"role": "button", "name": "Submit", "children": []}
        result = []
        _flatten_aria_tree(node, result)
        assert result == [{"role": "button", "name": "Submit"}]

    def test_node_without_name_has_empty_string(self):
        """Nodes with missing 'name' key produce empty-string name entry."""
        from backend.engine.ac_aria_enricher import _flatten_aria_tree

        node = {"role": "img", "children": []}
        result = []
        _flatten_aria_tree(node, result)
        assert result[0]["name"] == ""


# ---------------------------------------------------------------------------
# Tests: _find_aria_node
# ---------------------------------------------------------------------------


class TestFindAriaNode:
    """Unit tests for the ARIA node lookup helper."""

    def test_exact_match_with_role_filter(self, sample_aria_snapshot):
        """Matches button 'Save' when candidate_roles=['button']."""
        from backend.engine.ac_aria_enricher import _find_aria_node, _flatten_aria_tree

        nodes: list[dict] = []
        _flatten_aria_tree(sample_aria_snapshot, nodes)

        result = _find_aria_node(nodes, "Save", candidate_roles=["button"])
        assert result is not None
        assert result["role"] == "button"
        assert "Save" in result["name"]

    def test_case_insensitive_match(self, sample_aria_snapshot):
        """Target component lookup is case-insensitive."""
        from backend.engine.ac_aria_enricher import _find_aria_node, _flatten_aria_tree

        nodes: list[dict] = []
        _flatten_aria_tree(sample_aria_snapshot, nodes)

        result = _find_aria_node(nodes, "search", candidate_roles=None)
        assert result is not None
        assert result["role"] == "textbox"

    def test_no_match_returns_none(self, sample_aria_snapshot):
        """Returns None when no ARIA node matches the target_component."""
        from backend.engine.ac_aria_enricher import _find_aria_node, _flatten_aria_tree

        nodes: list[dict] = []
        _flatten_aria_tree(sample_aria_snapshot, nodes)

        result = _find_aria_node(nodes, "NonExistentWidget", candidate_roles=None)
        assert result is None

    def test_role_filter_falls_back_to_all_nodes_on_empty_match(self, sample_aria_snapshot):
        """When candidate_roles filter returns no candidates, falls back to all nodes."""
        from backend.engine.ac_aria_enricher import _find_aria_node, _flatten_aria_tree

        nodes: list[dict] = []
        _flatten_aria_tree(sample_aria_snapshot, nodes)

        # "textbox" role isn't in candidate_roles, but fallback to all nodes finds it
        result = _find_aria_node(nodes, "Search", candidate_roles=["dialog"])
        # With fallback, "Search" textbox is found
        assert result is not None
        assert "Search" in result["name"]


# ---------------------------------------------------------------------------
# Tests: enrich_test_plan_with_aria (main public API)
# ---------------------------------------------------------------------------


class TestEnrichTestPlanWithAria:
    """Tests for the main enrichment function."""

    @pytest.mark.asyncio
    async def test_no_op_when_flag_disabled(self, mock_page_with_aria):
        """Returns test plan unchanged when a11y_enrichment_enabled=False."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("Save", "Cancel")

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = False
            result = await enrich_test_plan_with_aria(mock_page_with_aria, test_plan, "run-1")

        # ARIA snapshot should NOT have been called
        mock_page_with_aria.accessibility.snapshot.assert_not_called()
        # Steps remain unenriched
        for step in result["steps"]:
            assert step.get("aria_role") is None
            assert step.get("aria_name") is None

    @pytest.mark.asyncio
    async def test_enriches_matching_steps(self, mock_page_with_aria):
        """Steps with a target_component that matches an ARIA node get aria_role and aria_name set.

        This directly covers AC-VERIFY-2: TestPlanStep produced from an AC-parser run
        over a page with a live ARIA tree carries non-None aria_role/aria_name.
        """
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("Save", "Search")

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            result = await enrich_test_plan_with_aria(mock_page_with_aria, test_plan, "run-1")

        steps = result["steps"]

        # "Save" → button
        save_step = steps[0]
        assert save_step.get("aria_role") is not None, "Save step must be enriched"
        assert save_step.get("aria_name") is not None
        assert "Save" in save_step["aria_name"]

        # "Search" → textbox
        search_step = steps[1]
        assert search_step.get("aria_role") is not None, "Search step must be enriched"
        assert "Search" in search_step["aria_name"]

    @pytest.mark.asyncio
    async def test_unmatched_steps_left_unchanged(self, mock_page_with_aria):
        """Steps with no ARIA match are not modified (aria_role stays None)."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("NonExistentWidget99")

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            result = await enrich_test_plan_with_aria(mock_page_with_aria, test_plan, "run-1")

        step = result["steps"][0]
        assert step.get("aria_role") is None
        assert step.get("aria_name") is None

    @pytest.mark.asyncio
    async def test_empty_snapshot_returns_plan_unchanged(self, mock_page_empty_aria):
        """When ARIA snapshot is None, test plan is returned unchanged without error."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("Save")

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            result = await enrich_test_plan_with_aria(mock_page_empty_aria, test_plan, "run-1")

        # Plan intact, no crash
        assert result["steps"][0].get("aria_role") is None

    @pytest.mark.asyncio
    async def test_snapshot_exception_returns_plan_unchanged(self, mock_page_snapshot_raises):
        """When page.accessibility.snapshot() raises, plan is returned unchanged (AC-ERROR-1 analogue)."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("Save")

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            # Must not propagate the exception to the caller
            result = await enrich_test_plan_with_aria(
                mock_page_snapshot_raises, test_plan, "run-1"
            )

        assert result["steps"][0].get("aria_role") is None

    @pytest.mark.asyncio
    async def test_already_enriched_steps_not_overwritten(self, mock_page_with_aria):
        """Steps that already carry aria_role/aria_name are not overwritten."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = _make_test_plan("Save")
        test_plan["steps"][0]["aria_role"] = "link"
        test_plan["steps"][0]["aria_name"] = "Existing"

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            result = await enrich_test_plan_with_aria(mock_page_with_aria, test_plan, "run-1")

        step = result["steps"][0]
        # Pre-existing values must NOT be overwritten
        assert step["aria_role"] == "link"
        assert step["aria_name"] == "Existing"

    @pytest.mark.asyncio
    async def test_empty_steps_list_returns_plan(self, mock_page_with_aria):
        """test_plan with no steps returns immediately without calling snapshot."""
        from backend.engine.ac_aria_enricher import enrich_test_plan_with_aria

        test_plan = {"steps": []}

        with patch("backend.engine.ac_aria_enricher.settings") as mock_settings:
            mock_settings.a11y_enrichment_enabled = True
            result = await enrich_test_plan_with_aria(mock_page_with_aria, test_plan, "run-1")

        mock_page_with_aria.accessibility.snapshot.assert_not_called()
        assert result["steps"] == []
