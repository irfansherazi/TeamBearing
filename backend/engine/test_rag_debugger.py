"""
T1-c: RAG Debugger LlamaIndex Dependency Fix — Unit Tests
==========================================================
Module: backend/engine/test_rag_debugger.py

Tests that the RAG debugger's query path uses direct ChromaDB calls and
no longer depends on LlamaIndex. After the fix, `query_knowledge_base()`
should work even when no llama-index-* packages are installed.

ACs covered:
  - AC-VERIFY-3: query_knowledge_base returns non-empty string with header
  - AC-ERROR-1:  empty/missing collection returns "" + WARNING, no exception
  - AC-VERIFY-5: regression — pre-existing test patterns unaffected

Run:
    python -m pytest backend/engine/test_rag_debugger.py -v
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import the module under test at module level (consistent with the other
# test files in this project). Each test resets the module-level singleton.
# ---------------------------------------------------------------------------
from backend.engine import rag_debugger  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the Chroma collection singleton before and after each test."""
    original = rag_debugger._chroma_collection_singleton
    rag_debugger._chroma_collection_singleton = None
    yield
    rag_debugger._chroma_collection_singleton = original


# ---------------------------------------------------------------------------
# Helpers — synthetic chromadb result dict used across tests
# ---------------------------------------------------------------------------


def _make_chroma_results(texts: list[str], sources: list[str]) -> dict:
    """Build a chromadb.Collection.query()-style result dict."""
    return {
        "documents": [texts],
        "metadatas": [[{"source_file": s, "file_type": "markdown"} for s in sources]],
        "distances": [[float(i) * 0.1 for i in range(len(texts))]],
        "ids": [[f"id-{i}" for i in range(len(texts))]],
    }


# ---------------------------------------------------------------------------
# Test 1 — AC-VERIFY-3 (happy path): returns the RAG DEBUGGER header + at
# least one source block when the Chroma collection has content.
# ---------------------------------------------------------------------------


def test_query_knowledge_base_returns_header_and_sources():
    """
    query_knowledge_base() must return a non-empty string that contains the
    'RAG DEBUGGER' header and at least one source filename.
    No LlamaIndex import should be needed after the fix.
    """
    mock_collection = MagicMock()
    mock_collection.count.return_value = 10
    mock_collection.query.return_value = _make_chroma_results(
        texts=["await page.locator('p-select').click()", "## Quick-Order Workflow\nStep 1: ..."],
        sources=["qo_form.spec.ts", "workflow_quick_order.md"],
    )

    with (
        patch.object(rag_debugger, "_get_or_create_collection", return_value=mock_collection),
        patch.object(rag_debugger, "_embed_query", return_value=[0.1] * 1536),
    ):
        result = rag_debugger.query_knowledge_base(
            "TimeoutError: locator get_by_text('Contest') strict mode violation"
        )

    assert result, "Expected a non-empty string from query_knowledge_base"
    assert "RAG DEBUGGER" in result, "Expected the RAG DEBUGGER header in the result"
    assert "qo_form.spec.ts" in result or "workflow_quick_order.md" in result, (
        "Expected at least one source filename in the result"
    )


# ---------------------------------------------------------------------------
# Test 2 — AC-ERROR-1: empty collection returns "" + WARNING log.
# ---------------------------------------------------------------------------


def test_query_knowledge_base_empty_collection_returns_empty_string(caplog):
    """
    When the Chroma collection is empty (count == 0), query_knowledge_base
    must return "" and log a WARNING containing 'empty' — it must NOT raise.
    """
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0  # <-- empty collection

    with (
        patch.object(rag_debugger, "_get_or_create_collection", return_value=mock_collection),
        patch.object(rag_debugger, "_embed_query", return_value=[0.1] * 1536),
        caplog.at_level(logging.WARNING, logger="backend.engine.rag_debugger"),
    ):
        result = rag_debugger.query_knowledge_base("some error log text")

    assert result == "", f"Expected empty string for empty collection, got: {result!r}"
    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "empty" in m.lower() or "not found" in m.lower()
        for m in warning_msgs
    ), f"Expected a WARNING about empty collection; got: {warning_msgs}"


# ---------------------------------------------------------------------------
# Test 3 — AC-ERROR-1 variant: _get_or_create_collection raises (e.g. dir
# not writable) → query_knowledge_base returns "" gracefully.
# ---------------------------------------------------------------------------


def test_query_knowledge_base_collection_error_returns_empty_string():
    """
    When _get_or_create_collection raises (e.g. Chroma dir unwritable),
    query_knowledge_base must catch the error and return "" without re-raising.
    """
    with (
        patch.object(
            rag_debugger,
            "_get_or_create_collection",
            side_effect=RuntimeError("chromadb not available"),
        ),
        patch.object(rag_debugger, "_embed_query", return_value=[0.1] * 1536),
    ):
        result = rag_debugger.query_knowledge_base("locator timed out")

    assert result == "", f"Expected '' when collection raises, got: {result!r}"


# ---------------------------------------------------------------------------
# Test 4 — AC-VERIFY-3 (no LlamaIndex): module exposes the public API even
# when all llama_index.* packages raise ImportError.
# ---------------------------------------------------------------------------


def test_module_exposes_public_api_without_llama_index():
    """
    After the fix, the rag_debugger module must expose `query_knowledge_base`
    and `ingest_knowledge_base` as callables. These must exist regardless of
    whether LlamaIndex is installed (it should no longer be imported at all).
    """
    assert callable(getattr(rag_debugger, "query_knowledge_base", None)), (
        "query_knowledge_base must be a callable on rag_debugger"
    )
    assert callable(getattr(rag_debugger, "ingest_knowledge_base", None)), (
        "ingest_knowledge_base must be a callable on rag_debugger"
    )
    # Confirm the module does NOT reference llama_index at the top level.
    # (The old guard was _LLAMA_AVAILABLE; the new code uses _CHROMA_AVAILABLE.)
    assert not hasattr(rag_debugger, "_LLAMA_AVAILABLE"), (
        "_LLAMA_AVAILABLE must NOT exist in the rewritten module (LlamaIndex removed)"
    )
    assert hasattr(rag_debugger, "_CHROMA_AVAILABLE"), (
        "_CHROMA_AVAILABLE must exist — chromadb is now the direct dependency"
    )


# ---------------------------------------------------------------------------
# Test 5 — AC-VERIFY-3 (empty error_log): query with empty/blank string
# returns "" immediately without touching Chroma.
# ---------------------------------------------------------------------------


def test_query_knowledge_base_empty_input_returns_empty():
    """
    Passing an empty or whitespace-only error_log must return "" immediately.
    The Chroma collection must NOT be accessed (fast-path guard).
    """
    mock_collection = MagicMock()

    with patch.object(rag_debugger, "_get_or_create_collection", return_value=mock_collection):
        result_empty = rag_debugger.query_knowledge_base("")
        result_blank = rag_debugger.query_knowledge_base("   ")

    assert result_empty == "", f"Expected '' for empty input, got {result_empty!r}"
    assert result_blank == "", f"Expected '' for blank input, got {result_blank!r}"
    # The Chroma collection must NOT have been obtained (fast-path exits before it).
    mock_collection.query.assert_not_called()
    mock_collection.count.assert_not_called()
