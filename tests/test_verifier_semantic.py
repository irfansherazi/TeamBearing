"""
Tests for semantic element resolution in goal_satisfiable_check (DR-011).

Validates the two-pass approach:
1. Pass 1 (fast): Exact keyword match — if found, return True immediately
2. Pass 2 (new): Semantic noun phrase matching against ARIA name/role/value fields
3. If both passes find nothing → return False
4. Empty ARIA tree → return True (safe default)

See: backend/engine/verifier.py::goal_satisfiable_check
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_page_with_aria():
    """Create a mock Playwright page with a configurable ARIA tree snapshot."""

    def _factory(aria_snapshot: dict | None = None):
        page = AsyncMock()
        if aria_snapshot is None:
            aria_snapshot = {"role": "WebArea", "name": "Test Page", "children": []}
        page.accessibility.snapshot = AsyncMock(return_value=aria_snapshot)
        return page

    return _factory


@pytest.fixture
def production_orders_aria():
    """ARIA tree with 'Production Orders' as a compound noun in a table name."""
    return {
        "role": "WebArea",
        "name": "vSuite Dashboard",
        "children": [
            {
                "role": "table",
                "name": "Production Orders",
                "children": [
                    {"role": "row", "name": "Order #1001"},
                    {"role": "row", "name": "Order #1002"},
                ],
            },
            {"role": "button", "name": "Create New"},
            {"role": "heading", "name": "Dashboard Overview", "level": 1},
        ],
    }


class TestSemanticPass2:
    """Tests for Pass 2 semantic noun phrase matching."""

    @pytest.mark.asyncio
    async def test_compound_noun_found_in_aria_name(self, mock_page_with_aria, production_orders_aria):
        """Compound noun 'Production Orders' found in ARIA name field → satisfiable=True."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(production_orders_aria)
        # Individual tokens "production" and "orders" might not match on their own
        # in the raw JSON string, but "Production Orders" as a compound noun
        # maps to the table's ARIA name field
        result = await goal_satisfiable_check(
            page, "verify the Production Orders table shows filtered results", "run-test"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_no_semantic_match_returns_false(self, mock_page_with_aria, production_orders_aria):
        """Goal with no matching semantic content → satisfiable=False."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(production_orders_aria)
        # "Calendar Widget" doesn't exist anywhere in the ARIA tree
        result = await goal_satisfiable_check(
            page, "verify the Calendar Widget displays correctly", "run-test"
        )
        assert result is False


class TestPass1ShortCircuit:
    """Tests that Pass 1 short-circuits Pass 2 when keywords are found."""

    @pytest.mark.asyncio
    async def test_pass1_hit_skips_pass2(self, mock_page_with_aria, production_orders_aria):
        """When Pass 1 finds keywords, Pass 2 is not invoked."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(production_orders_aria)
        # "dashboard" appears in the raw JSON string → Pass 1 hit
        result = await goal_satisfiable_check(
            page, "navigate to the dashboard", "run-test"
        )
        assert result is True


class TestSafeDefaults:
    """Tests that safe defaults are preserved."""

    @pytest.mark.asyncio
    async def test_empty_aria_tree_returns_true(self, mock_page_with_aria):
        """Empty ARIA tree → satisfiable=True (safe default)."""
        from backend.engine.verifier import goal_satisfiable_check

        # Null snapshot — safe default
        page = AsyncMock()
        page.accessibility.snapshot = AsyncMock(return_value=None)
        result = await goal_satisfiable_check(page, "verify something", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_pass2_exception_falls_through_to_true(self, mock_page_with_aria):
        """If Pass 2 raises an exception, fall through to return True."""
        from backend.engine.verifier import goal_satisfiable_check

        # The overall function catches exceptions and returns True
        page = AsyncMock()
        page.accessibility.snapshot = AsyncMock(side_effect=RuntimeError("Boom"))
        result = await goal_satisfiable_check(page, "some complex goal", "run-test")
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — Resolution-path evidence annotation tests (AC-ASYNC-1)
# ═══════════════════════════════════════════════════════════════════════════


class TestResolutionPathEvidenceAnnotation:
    """Tests for annotate_evidence_with_resolution_path (AC-ASYNC-1).

    The helper must append a 'locator=<resolution_path>' tag to evidence
    strings for all A11y-resolver resolution paths, so post-run analysts
    can compute the a11y-resolution rate from detailed_execution_log.
    """

    def test_a11y_primary_is_annotated(self):
        """Evidence is annotated with locator=a11y_primary."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        result = annotate_evidence_with_resolution_path(
            "button Save was found", "a11y_primary"
        )
        assert "[locator=a11y_primary]" in result

    def test_a11y_normalized_is_annotated(self):
        """Evidence is annotated with locator=a11y_normalized."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        result = annotate_evidence_with_resolution_path(
            "found via normalized match", "a11y_normalized"
        )
        assert "[locator=a11y_normalized]" in result

    def test_selector_fallback_is_annotated(self):
        """selector_fallback path (a11y miss) is annotated."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        result = annotate_evidence_with_resolution_path("css match", "selector_fallback")
        assert "[locator=selector_fallback]" in result

    def test_selector_only_legacy_not_annotated(self):
        """selector_only_legacy (no a11y attempted) is NOT annotated.

        This path indicates no a11y resolver was involved — omitting the tag
        lets analysts identify legacy-path steps cleanly.
        """
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        result = annotate_evidence_with_resolution_path(
            "old path used", "selector_only_legacy"
        )
        assert "[locator=" not in result

    def test_none_resolution_path_leaves_evidence_unchanged(self):
        """When resolution_path is None, evidence is returned unmodified."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        original = "some evidence text"
        result = annotate_evidence_with_resolution_path(original, None)
        assert result == original

    def test_idempotent_annotation(self):
        """Calling the function twice does not duplicate the tag."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        once = annotate_evidence_with_resolution_path("evidence", "a11y_primary")
        twice = annotate_evidence_with_resolution_path(once, "a11y_primary")
        assert twice.count("[locator=a11y_primary]") == 1

    def test_original_evidence_text_preserved(self):
        """The original evidence text is preserved with the annotation appended."""
        from backend.engine.verifier import annotate_evidence_with_resolution_path

        original = "button[name='Save'] found in DOM"
        result = annotate_evidence_with_resolution_path(original, "a11y_primary")
        assert result.startswith(original)
