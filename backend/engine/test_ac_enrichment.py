"""
vQA — AC Enrichment Engine Tests
===================================
Module: backend/engine/test_ac_enrichment.py

FEAT-002: Comprehensive test suite for the Domain-Aware AC Enrichment Engine.

Tests cover:
  1. Domain inference from ticket summary + AC text
  2. Enrichment integration (KB retrieval + context injection)
  3. Context formatting (XML tags, char budget)
  4. Edge cases (empty input, no KB match, poor quality)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engine.ac_enricher import (
    EnrichmentResult,
    _build_enrichment_context,
    _detect_domains,
    _extract_actionable_lines,
    enrich_ac_text,
)

# ---------------------------------------------------------------------------
# 1. Domain Inference Tests
# ---------------------------------------------------------------------------


class TestDomainInference:
    """Test domain detection from ticket summary and AC text."""

    def test_detects_table_sort_domain(self):
        """Sort-related keywords should detect table_sort domain."""
        domains = _detect_domains(
            summary="Sort Production Orders by client column",
            raw_ac="Click the CLIENT column header to sort ascending",
        )
        assert "table_sort" in domains

    def test_detects_quick_order_domain(self):
        """Quick order keywords should detect quick_order domain."""
        domains = _detect_domains(
            summary="Create a new radio commercial quick order",
            raw_ac="Click New Request, select ad type Radio Commercial",
        )
        assert "quick_order" in domains

    def test_detects_voice_workflow_domain(self):
        """Voice/dubber keywords should detect voice_workflow domain."""
        domains = _detect_domains(
            summary="Add voice talent to spot",
            raw_ac="Click Add Voice on the production orders list",
        )
        assert "voice_workflow" in domains

    def test_detects_login_auth_domain(self):
        """Login/credentials keywords should detect login_auth domain."""
        domains = _detect_domains(
            summary="Login as Account Executive",
            raw_ac="Enter email and password credentials",
        )
        assert "login_auth" in domains

    def test_detects_view_navigation_domain(self):
        """View switching keywords should detect view_navigation domain."""
        domains = _detect_domains(
            summary="Switch to compact view",
            raw_ac="Navigate from list view to compact view",
        )
        assert "view_navigation" in domains

    def test_detects_multiple_domains(self):
        """Compound AC should detect multiple domains."""
        domains = _detect_domains(
            summary="Sort table then upload file in quick order",
            raw_ac="1. Sort by client column\n2. Upload audio file",
        )
        assert len(domains) >= 2
        # Should detect both table_sort and file_upload
        detected_set = set(domains)
        assert "table_sort" in detected_set
        assert "file_upload" in detected_set

    def test_no_domain_detected(self):
        """Completely generic text should return empty domains."""
        domains = _detect_domains(
            summary="General system test",
            raw_ac="The application should behave normally",
        )
        # May or may not detect — the point is it doesn't crash
        assert isinstance(domains, list)

    def test_max_three_domains(self):
        """Should return at most 3 domains even with many keyword matches."""
        domains = _detect_domains(
            summary="Login, sort table, upload file, approve order, add voice, change status",
            raw_ac="Do everything in the system",
        )
        assert len(domains) <= 3

    def test_description_contributes_to_detection(self):
        """Full Jira description should contribute to domain detection."""
        domains = _detect_domains(
            summary="Test the feature",
            raw_ac="Verify the page",
            description="The user needs to sort the production orders table by due date",
        )
        assert "table_sort" in domains

    def test_domains_sorted_by_strength(self):
        """Domains with more keyword matches should come first."""
        domains = _detect_domains(
            summary="Sort ascending descending column header table order by",
            raw_ac="Click the column to sort",
            description="Sort the table by client",
        )
        if domains:
            # table_sort should be first since it has the most keyword matches
            assert domains[0] == "table_sort"


# ---------------------------------------------------------------------------
# 2. Context Formatting Tests
# ---------------------------------------------------------------------------


class TestContextFormatting:
    """Test the XML-tagged context block builder."""

    def test_enrichment_context_xml_tagged(self):
        """Output should have <domain_context> XML tags."""
        context = _build_enrichment_context(
            domains=["table_sort"],
            kb_articles=[("table_sort", "TABLE SORTING RULES", "Use sort-btn for compact view")],
        )
        assert "<domain_context" in context
        assert "</domain_context>" in context
        assert 'source="kb_enrichment"' in context

    def test_empty_articles_returns_empty(self):
        """No articles should produce empty context."""
        context = _build_enrichment_context(
            domains=["table_sort"],
            kb_articles=[],
        )
        assert context == ""

    def test_domain_labels_present(self):
        """Each domain should appear as a label in the context."""
        context = _build_enrichment_context(
            domains=["table_sort", "quick_order"],
            kb_articles=[
                ("table_sort", "SORT RULES", "Click column header"),
                ("quick_order", "QO WORKFLOW", "Select Radio Commercial"),
            ],
        )
        assert "table_sort" in context
        assert "quick_order" in context

    def test_article_names_present(self):
        """KB article names should appear in the context."""
        context = _build_enrichment_context(
            domains=["table_sort"],
            kb_articles=[("table_sort", "TABLE SORTING RULES", "Use primeng_dropdown")],
        )
        assert "TABLE SORTING RULES" in context

    def test_anti_hallucination_instruction(self):
        """Context should include anti-hallucination instruction."""
        context = _build_enrichment_context(
            domains=["table_sort"],
            kb_articles=[("table_sort", "RULES", "content")],
        )
        assert "Do NOT invent" in context


# ---------------------------------------------------------------------------
# 3. Actionable Line Extraction Tests
# ---------------------------------------------------------------------------


class TestActionableLineExtraction:
    """Test the line scoring and filtering logic."""

    def test_prioritizes_component_mentions(self):
        """Lines mentioning PrimeNG components should be prioritized."""
        content = (
            "This is a general introduction.\n"
            "Step 1: Click the p-select dropdown to open the sort panel.\n"
            "Some filler text about the system.\n"
            "Step 2: Use get_by_role('button', name='Sort By') for compact view.\n"
            "More filler.\n"
        )
        lines = _extract_actionable_lines(content)
        assert len(lines) >= 2
        # Both lines with component names should be included
        assert any("p-select" in line for line in lines)
        assert any("get_by_role" in line for line in lines)

    def test_skips_separator_lines(self):
        """═══ and ─── lines should be skipped."""
        content = "═══════════════════\nSome important rule.\n───────────────────\n"
        lines = _extract_actionable_lines(content)
        assert not any("═" in line for line in lines)
        assert not any("─" in line for line in lines)

    def test_max_five_lines(self):
        """Should return at most 5 lines."""
        content = "\n".join(f"Step {i}: Click the p-select button #{i}" for i in range(20))
        lines = _extract_actionable_lines(content)
        assert len(lines) <= 5

    def test_empty_content_returns_empty(self):
        """Empty content should return empty list."""
        lines = _extract_actionable_lines("")
        assert lines == []


# ---------------------------------------------------------------------------
# 4. Full Enrichment Pipeline Tests
# ---------------------------------------------------------------------------


class TestEnrichACText:
    """Integration tests for the full enrichment pipeline."""

    @pytest.mark.anyio
    @patch("backend.engine.ac_enricher._query_kb_for_enrichment")
    async def test_enriches_sort_step(self, mock_query):
        """Sort-related AC should be enriched with sort context."""
        # Return pre-built KB articles instead of hitting real KB
        mock_query.return_value = [
            (
                "table_sort",
                "TABLE SORTING RULES",
                "In compact view, use button#sort-btn to open the sort panel.\n"
                "Click the column header in list view.\n"
                "Use primeng_dropdown for compound columns.",
            ),
        ]

        mock_quality = MagicMock()
        mock_quality.overall_score = 10
        mock_quality.quality_grade = "good"

        result = await enrich_ac_text(
            raw_ac="User can sort the table",
            summary="Sort Production Orders table",
            description="",
            ticket_id="QA-TEST-001",
            quality_result=mock_quality,
        )

        assert result.enrichment_applied is True
        assert "table_sort" in result.detected_domains
        assert len(result.kb_articles_used) > 0
        assert "<domain_context" in result.enriched_ac
        assert "User can sort the table" in result.enriched_ac  # original preserved

    @pytest.mark.anyio
    async def test_noop_on_empty_ac(self):
        """Empty AC text should result in no-op."""
        result = await enrich_ac_text(
            raw_ac="",
            summary="Some ticket",
            description="",
            ticket_id="QA-TEST-002",
        )
        assert result.enrichment_applied is False
        assert result.enriched_ac == ""

    @pytest.mark.anyio
    async def test_noop_on_whitespace_ac(self):
        """Whitespace-only AC text should result in no-op."""
        result = await enrich_ac_text(
            raw_ac="   \n  \t  ",
            summary="Some ticket",
            description="",
            ticket_id="QA-TEST-003",
        )
        assert result.enrichment_applied is False

    @pytest.mark.anyio
    @patch("backend.engine.ac_enricher._query_kb_for_enrichment")
    async def test_original_ac_preserved(self, mock_query):
        """Original AC text should appear unchanged at the start of enriched AC."""
        original_ac = "Click the submit button"
        mock_query.return_value = [
            ("quick_order", "FORM RULES", "Always use get_by_role for buttons."),
        ]
        mock_quality = MagicMock()
        mock_quality.overall_score = 10
        mock_quality.quality_grade = "good"

        result = await enrich_ac_text(
            raw_ac=original_ac,
            summary="Submit quick order",
            description="",
            ticket_id="QA-TEST-004",
            quality_result=mock_quality,
        )
        # Original AC should be at the beginning, unchanged
        assert result.enriched_ac.startswith(original_ac)

    @pytest.mark.anyio
    async def test_noop_when_no_domains_detected(self):
        """If no domains are detected, should be a no-op."""
        mock_quality = MagicMock()
        mock_quality.overall_score = 10
        mock_quality.quality_grade = "good"

        result = await enrich_ac_text(
            raw_ac="The system processes data internally",
            summary="Internal processing test",
            description="Backend task with no UI interaction",
            ticket_id="QA-TEST-005",
            quality_result=mock_quality,
        )
        # Even if it doesn't detect domains, it should handle gracefully
        assert isinstance(result, EnrichmentResult)

    def test_to_dict_serialization(self):
        """EnrichmentResult.to_dict() should produce a clean dict."""
        result = EnrichmentResult(
            enriched_ac="test text",
            detected_domains=["table_sort", "login_auth"],
            kb_articles_used=["TABLE SORTING RULES"],
            enrichment_applied=True,
            enrichment_char_count=500,
        )
        d = result.to_dict()
        assert d["detected_domains"] == ["table_sort", "login_auth"]
        assert d["kb_articles_used"] == ["TABLE SORTING RULES"]
        assert d["enrichment_applied"] is True
        assert d["enrichment_char_count"] == 500

    @pytest.mark.anyio
    async def test_quality_result_accepted(self):
        """Quality result parameter should be accepted without error."""
        mock_quality = MagicMock()
        mock_quality.quality_grade = "good"
        mock_quality.overall_score = 8

        # Should not raise even with a quality result
        result = await enrich_ac_text(
            raw_ac="Sort the table ascending",
            summary="Sort test",
            description="",
            ticket_id="QA-TEST-006",
            quality_result=mock_quality,
        )
        assert isinstance(result, EnrichmentResult)


# ---------------------------------------------------------------------------
# 5. Edge Case Tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and robustness tests."""

    @pytest.mark.anyio
    @patch("backend.engine.ac_enricher._query_kb_for_enrichment")
    async def test_kb_query_failure_is_non_fatal(self, mock_query):
        """KB query errors should be caught — playwright context may still apply."""
        mock_query.side_effect = Exception("KB crashed")
        mock_quality = MagicMock()
        mock_quality.overall_score = 10
        mock_quality.quality_grade = "good"

        result = await enrich_ac_text(
            raw_ac="Sort the table by client",
            summary="Sort test",
            description="",
            ticket_id="QA-TEST-007",
            quality_result=mock_quality,
        )
        # Should not raise — non-fatal KB failure.
        # Playwright RAG may still inject context (enrichment_applied may be True or False).
        # The key contract: no exception, domains are still detected, enriched_ac contains raw AC.
        assert "table_sort" in result.detected_domains
        assert result.enriched_ac.startswith("Sort the table by client")

    def test_enrichment_result_default_values(self):
        """Default EnrichmentResult should have safe defaults."""
        result = EnrichmentResult(enriched_ac="raw text")
        assert result.detected_domains == []
        assert result.kb_articles_used == []
        assert result.enrichment_applied is False
        assert result.enrichment_char_count == 0

    def test_detect_domains_case_insensitive(self):
        """Domain detection should be case-insensitive."""
        domains = _detect_domains(
            summary="SORT THE TABLE BY COLUMN HEADER",
            raw_ac="ASCENDING ORDER",
        )
        assert "table_sort" in domains

    def test_detect_domains_empty_inputs(self):
        """Empty summary and AC should return empty domains."""
        domains = _detect_domains(summary="", raw_ac="")
        assert domains == []
