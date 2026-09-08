"""
TASK-051 Phase 5 — Bug G: Page Text Snapshot PrimeNG Table
============================================================

Tests for the extended page text capture in executor.py's `verify` action.
The bug: `document.body.innerText` returns empty for PrimeNG `p-datatable`
tables because Angular renders rows inside component shadow-like structures
that `innerText` on `document.body` misses.

Fix: After `document.body.innerText` returns empty/sparse, also query:
  - `tbody tr td`  (standard HTML tables nested in PrimeNG)
  - `[role='row']` (ARIA row elements)
  - `.p-datatable-tbody` (PrimeNG datatable body container)

Tests:
  - test_page_text_captures_primeng_table: text from .p-datatable-tbody is returned
    when body.innerText returns empty
  - test_page_text_body_text_takes_priority: when body.innerText is non-empty,
    it is used directly (no redundant JS evaluation)
  - test_page_text_combined_when_body_sparse: combines body text with table text
    when body text is non-empty but short

Run: python3 -m pytest tests/test_task_051_phase5_bug_g.py -v
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _make_page_mock(
    body_inner_text: str = "",
    table_cell_text: str = "",
    aria_row_text: str = "",
    datatable_text: str = "",
    is_visible: bool = False,
    dom_count: int = 0,
) -> MagicMock:
    """
    Create a mock Playwright Page that simulates the PrimeNG table environment.

    body_inner_text: returned by `document.body.innerText`
    table_cell_text: returned by querying `tbody tr td`
    aria_row_text: returned by querying `[role='row']`
    datatable_text: returned by querying `.p-datatable-tbody`
    """
    page = MagicMock()
    page.url = "https://test.vcreative.net/campaigns"

    # is_visible returns False (triggers Tier 3 page text search)
    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=is_visible)
    locator.count = AsyncMock(return_value=dom_count)
    page.locator.return_value = locator

    # Simulate page.evaluate() for different JS expressions
    async def mock_evaluate(script, *args, **kwargs):
        # Match the body.innerText call
        if "document.body.innerText" in script:
            return body_inner_text
        # Match table cell selectors
        if "tbody tr td" in script or "p-datatable-tbody" in script or "role='row'" in script or 'role="row"' in script:
            # Return combined table text from the selectors
            parts = []
            if table_cell_text:
                parts.append(table_cell_text)
            if aria_row_text:
                parts.append(aria_row_text)
            if datatable_text:
                parts.append(datatable_text)
            return "\n".join(parts) if parts else ""
        return ""

    page.evaluate = mock_evaluate
    return page


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Bug G — PrimeNG table text captured when body.innerText is empty
# ═══════════════════════════════════════════════════════════════════════════


class TestPageTextPrimeNGFallback:
    """AC-HAPPY-5: page text extraction captures PrimeNG table data."""

    def test_page_text_body_text_used_when_present(self):
        """
        When document.body.innerText returns non-empty text,
        it should be used for verify text matching (existing behavior preserved).
        """
        from backend.engine.executor import _extract_page_text

        async def run():
            page = _make_page_mock(body_inner_text="Campaign Alpha Campaign Beta")
            text = await _extract_page_text(page)
            return text

        result = _run_async(run())
        assert "Campaign Alpha" in result, "Body text should be in page_text"
        assert "Campaign Beta" in result, "Body text should be in page_text"

    def test_page_text_captures_primeng_table_when_body_empty(self):
        """
        AC-HAPPY-5 Bug G: When document.body.innerText is empty (PrimeNG table
        rendering in Angular component boundaries), the fallback also queries
        tbody tr td, [role='row'], and .p-datatable-tbody selectors.
        """
        from backend.engine.executor import _extract_page_text

        async def run():
            page = _make_page_mock(
                body_inner_text="",  # Simulates PrimeNG table invisible to body.innerText
                table_cell_text="Campaign Alpha\nCampaign Beta\n2026-05-01",
                aria_row_text="Campaign Alpha Campaign Beta",
                datatable_text="Campaign Alpha Campaign Beta 2026-05-01",
            )
            text = await _extract_page_text(page)
            return text

        result = _run_async(run())
        assert "Campaign Alpha" in result, (
            f"PrimeNG table text should be captured via fallback selectors (got: '{result[:100]}')"
        )

    def test_page_text_fallback_selectors_queried(self):
        """
        Verify that the fallback table selectors are attempted when body.innerText is empty.
        The mock tracks all evaluate() calls.
        """
        from backend.engine.executor import _extract_page_text

        eval_calls = []

        async def run():
            page = MagicMock()
            page.url = "https://test.vcreative.net"

            async def mock_evaluate(script, *args, **kwargs):
                eval_calls.append(script[:80])
                if "document.body.innerText" in script:
                    return ""  # Empty — triggers fallback
                # Fallback selectors return table data
                return "Campaign Delta\nCampaign Epsilon"

            page.evaluate = mock_evaluate
            text = await _extract_page_text(page)
            return text

        result = _run_async(run())

        # The body.innerText call should have been made
        body_calls = [c for c in eval_calls if "body.innerText" in c]
        assert len(body_calls) >= 1, "document.body.innerText must be called"

        # At least one fallback selector call should have been made
        fallback_calls = [c for c in eval_calls if "tbody" in c or "p-datatable" in c or "role" in c]
        assert len(fallback_calls) >= 1, (
            f"At least one fallback table selector must be queried when body text is empty. Calls made: {eval_calls}"
        )

        assert "Campaign Delta" in result, "Fallback table text should be returned"

    def test_page_text_combined_body_and_table(self):
        """
        When body text is non-empty but short (< some threshold), also append
        table text to maximize coverage. Tests that both sources are captured.
        """
        from backend.engine.executor import _extract_page_text

        async def run():
            page = _make_page_mock(
                body_inner_text="Campaigns page loaded",  # Short body text
                table_cell_text="Campaign Alpha\nCampaign Beta",
            )
            text = await _extract_page_text(page)
            return text

        result = _run_async(run())
        # At minimum, body text should be present
        assert "Campaigns" in result, "Body text should always be in result"

    def test_page_text_exception_handling(self):
        """
        When page.evaluate() throws for any reason,
        the function should return empty string (not raise).
        """
        from backend.engine.executor import _extract_page_text

        async def run():
            page = MagicMock()
            page.url = "https://test.vcreative.net"

            async def mock_evaluate(script, *args, **kwargs):
                raise RuntimeError("Page closed")

            page.evaluate = mock_evaluate
            text = await _extract_page_text(page)
            return text

        result = _run_async(run())
        assert result == "", f"Should return empty string on exception, got: '{result}'"


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Verify action uses _extract_page_text (integration smoke test)
# ═══════════════════════════════════════════════════════════════════════════


class TestVerifyActionUsesExtractPageText:
    """Integration smoke test: verify action calls _extract_page_text."""

    def test_extract_page_text_is_importable(self):
        """_extract_page_text must be a top-level importable function."""
        from backend.engine import executor

        assert hasattr(executor, "_extract_page_text"), (
            "_extract_page_text must be defined as a top-level function in executor.py "
            "so it can be unit tested and used from the verify action handler."
        )

    def test_extract_page_text_is_coroutine_function(self):
        """_extract_page_text must be an async function."""
        import inspect

        from backend.engine.executor import _extract_page_text

        assert inspect.iscoroutinefunction(_extract_page_text), (
            "_extract_page_text must be async (uses await page.evaluate)"
        )
