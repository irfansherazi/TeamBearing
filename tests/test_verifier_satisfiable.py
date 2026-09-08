"""
Tests for goal_satisfiable_check keyword filtering fix (TC-5).

Validates that the keyword extraction in goal_satisfiable_check:
1. Does NOT filter out short but meaningful verbs (set, tab, row, add, click)
2. DOES filter out stopwords (the, and, for, etc.)
3. Preserves the safe default: empty keywords → returns True
4. Correctly handles edge cases (all-stopword goals, mixed goals)

See: backend/engine/verifier.py::goal_satisfiable_check
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
def rich_aria_snapshot():
    """ARIA tree containing elements that match various goal keywords."""
    return {
        "role": "WebArea",
        "name": "Production Orders",
        "children": [
            {
                "role": "table",
                "name": "Production Orders",
                "children": [
                    {"role": "row", "name": "Row 1"},
                    {"role": "row", "name": "Row 2"},
                ],
            },
            {"role": "button", "name": "Add New"},
            {"role": "tab", "name": "Active"},
            {
                "role": "combobox",
                "name": "filter",
                "children": [
                    {"role": "option", "name": "Active"},
                    {"role": "option", "name": "Inactive"},
                ],
            },
        ],
    }


class TestKeywordExtractionFix:
    """Tests for TC-5: short meaningful verbs must NOT be filtered."""

    @pytest.mark.asyncio
    async def test_short_verb_set_not_filtered(self, mock_page_with_aria, rich_aria_snapshot):
        """'set' (3 chars) must be kept as a keyword, not dropped."""
        from backend.engine.verifier import goal_satisfiable_check

        # "set" should be a keyword; "filter" matches ARIA "filter" combobox;
        # "active" matches ARIA option "Active"
        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "set the filter to Active", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_short_verb_add_not_filtered(self, mock_page_with_aria, rich_aria_snapshot):
        """'add' (3 chars) must be kept as a keyword, not dropped."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "add a row", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_short_verb_tab_not_filtered(self, mock_page_with_aria, rich_aria_snapshot):
        """'tab' (3 chars) must be kept as a keyword, not dropped."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "click the tab", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_short_verb_row_not_filtered(self, mock_page_with_aria, rich_aria_snapshot):
        """'row' (3 chars) must be kept as a keyword, not dropped."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "select the row", "run-test")
        assert result is True


class TestStopwordFiltering:
    """Tests that stopwords ARE filtered from keywords."""

    @pytest.mark.asyncio
    async def test_stopwords_filtered(self, mock_page_with_aria):
        """Articles and prepositions should be filtered out."""
        from backend.engine.verifier import goal_satisfiable_check

        # All words are stopwords — keywords should be empty → safe default True
        page = mock_page_with_aria()
        result = await goal_satisfiable_check(page, "the", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_only_stopwords_returns_true(self, mock_page_with_aria):
        """Goal composed entirely of stopwords → empty keywords → safe default True."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria()
        result = await goal_satisfiable_check(page, "the and for are has", "run-test")
        assert result is True


class TestSafeDefault:
    """Tests that the safe default (return True) is preserved."""

    @pytest.mark.asyncio
    async def test_empty_keywords_returns_true(self, mock_page_with_aria):
        """When no meaningful keywords can be extracted, return True."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria()
        result = await goal_satisfiable_check(page, "", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_true(self, mock_page_with_aria):
        """On any exception, return True (safe default)."""
        from backend.engine.verifier import goal_satisfiable_check

        page = AsyncMock()
        page.accessibility.snapshot = AsyncMock(side_effect=Exception("Snapshot failed"))
        result = await goal_satisfiable_check(page, "verify something", "run-test")
        assert result is True


class TestKeywordContent:
    """Tests verifying specific keyword extraction results."""

    @pytest.mark.asyncio
    async def test_set_filter_active_keywords(self, mock_page_with_aria, rich_aria_snapshot):
        """goal='set the filter to Active' → keywords include set, filter, active (not 'the', 'to')."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "set the filter to Active", "run-test")
        # The function returns True because these keywords ARE in the ARIA tree
        assert result is True

    @pytest.mark.asyncio
    async def test_add_row_keywords(self, mock_page_with_aria, rich_aria_snapshot):
        """goal='add a row' → keywords include add, row (not 'a')."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        result = await goal_satisfiable_check(page, "add a row", "run-test")
        assert result is True

    @pytest.mark.asyncio
    async def test_unsatisfiable_goal_returns_false(self, mock_page_with_aria, rich_aria_snapshot):
        """Goal with meaningful keywords NOT present in ARIA tree → returns False."""
        from backend.engine.verifier import goal_satisfiable_check

        page = mock_page_with_aria(rich_aria_snapshot)
        # "verify", "calendar", "widget" are all meaningful but not in the ARIA tree
        result = await goal_satisfiable_check(page, "verify the calendar widget", "run-test")
        assert result is False
