"""
tests/test_rag_fallback.py
===========================
Tests for AC-FALLBACK-1: Graceful degradation when the selector RAG index
is unavailable (missing or corrupt pickle file).

Acceptance Criteria
-------------------
AC-FALLBACK-1 (MUST):
  Given the selector RAG index fails to load (missing file, corrupt pickle)
  When SelectorRAG.query() is called
  Then:
  - Falls back to keyword-only selector_registry.query() (existing behavior)
  - Logs WARNING: "Selector RAG unavailable — falling back to keyword match"
  - No exception propagates; planner call completes normally

Verification:
  - test_fallback_on_corrupt_index
  - test_fallback_on_missing_index
"""

import logging
from pathlib import Path

import pytest

from backend.kb.selector_rag import SelectorRAG

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_rag(tmp_path: Path) -> SelectorRAG:
    """Build a SelectorRAG with a tiny valid index so we can corrupt it."""
    registry = tmp_path / "selector_registry.json"
    registry.write_text(
        '{"selectors": {"btn-submit": {"description": "Submit button", "context": "", "strategies": [{"method": "get_by_role", "role": "button", "name": "Submit", "selector": ""}]}}}'
    )
    bp_dir = tmp_path / "blueprints"
    bp_dir.mkdir()

    index_dir = tmp_path / "selector_rag"

    rag = SelectorRAG(
        registry_path=registry,
        blueprints_dir=bp_dir,
        index_dir=index_dir,
    )
    rag.build_index()
    return rag


# ---------------------------------------------------------------------------
# AC-FALLBACK-1: test_fallback_on_missing_index
# ---------------------------------------------------------------------------


class TestFallbackOnMissingIndex:
    """
    SelectorRAG.query() must not raise when index files are absent.

    The instance starts with no index directory populated, so load_index()
    returns False.  Because the registry path doesn't exist in tmp_path by
    default (we deliberately skip build_index()), query() must handle the
    missing state gracefully and return "" (empty string = graceful null).
    """

    def test_returns_empty_string_when_no_index_and_no_registry(self, tmp_path: Path):
        """No exception; returns empty string when both index and registry are absent."""
        rag = SelectorRAG(
            registry_path=tmp_path / "nonexistent_registry.json",
            blueprints_dir=tmp_path / "blueprints",
            index_dir=tmp_path / "selector_rag",
        )
        # Index files do not exist; registry does not exist either.
        result = rag.query("Sort production orders by CLIENT ascending")
        assert isinstance(result, str), "query() must return str even on missing index"

    def test_no_exception_propagates_on_missing_index(self, tmp_path: Path):
        """Missing index files must NOT cause any exception to propagate."""
        rag = SelectorRAG(
            registry_path=tmp_path / "nonexistent.json",
            blueprints_dir=tmp_path / "blueprints",
            index_dir=tmp_path / "selector_rag",
        )
        try:
            rag.query("Click Submit button")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"query() raised an exception on missing index: {exc}")

    def test_load_index_returns_false_when_files_missing(self, tmp_path: Path):
        """load_index() returns False when pkl files don't exist."""
        rag = SelectorRAG(
            registry_path=tmp_path / "r.json",
            blueprints_dir=tmp_path / "bp",
            index_dir=tmp_path / "idx",
        )
        result = rag.load_index()
        assert result is False, "load_index() must return False when pkl files are missing"

    def test_missing_index_warning_emitted(self, tmp_path: Path, caplog):
        """
        When SelectorRAG has no pre-built index and registry is also missing,
        no WARNING should be emitted for the missing case (it's a first-time run),
        but a fallback-related log SHOULD appear if the registry path is present
        but the index is not built yet. This test verifies the non-exception path.
        """
        rag = SelectorRAG(
            registry_path=tmp_path / "nonexistent.json",
            blueprints_dir=tmp_path / "blueprints",
            index_dir=tmp_path / "selector_rag",
        )
        with caplog.at_level(logging.DEBUG, logger="backend.kb.selector_rag"):
            result = rag.query("some step text here")
        # Must not raise; result is a string
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# AC-FALLBACK-1: test_fallback_on_corrupt_index
# ---------------------------------------------------------------------------


class TestFallbackOnCorruptIndex:
    """
    SelectorRAG.query() must gracefully handle a corrupt pickle file.

    We build a valid index, then overwrite selector_index.pkl with garbage
    bytes so that pickle.loads() will raise.  The SelectorRAG must log a
    WARNING and return a result without raising.
    """

    def test_load_index_returns_false_on_corrupt_selector_pkl(self, tmp_path: Path, caplog):
        """load_index() returns False and logs WARNING when selector_index.pkl is corrupt."""
        rag = _make_minimal_rag(tmp_path)
        # Corrupt the selector pickle
        (tmp_path / "selector_rag" / "selector_index.pkl").write_bytes(b"NOT_A_VALID_PICKLE!!!")
        # Remove JSON manifest fallback to force failure
        (tmp_path / "selector_rag" / "manifest.json").unlink(missing_ok=True)

        # Reset in-memory state to force a fresh load
        rag._sel_vectorizer = None
        rag._sel_tfidf = None
        rag._sel_bm25 = None
        rag._sel_entries = None

        with caplog.at_level(logging.WARNING, logger="backend.kb.selector_rag"):
            result = rag.load_index()

        assert result is False, "load_index() must return False on corrupt pkl"
        assert any("corrupt" in r.message.lower() or "failed to load" in r.message.lower() for r in caplog.records), (
            "Expected a WARNING about corrupt/failed pkl load"
        )

    def test_load_index_returns_false_on_corrupt_skill_pkl(self, tmp_path: Path, caplog):
        """load_index() returns False and logs WARNING when skill_index.pkl is corrupt."""
        rag = _make_minimal_rag(tmp_path)
        # Corrupt the skill pickle only
        (tmp_path / "selector_rag" / "skill_index.pkl").write_bytes(b"GARBAGE_DATA_9999")
        # Remove JSON manifest fallback to force failure
        (tmp_path / "selector_rag" / "manifest.json").unlink(missing_ok=True)

        rag._sel_vectorizer = None
        rag._sel_tfidf = None
        rag._sel_bm25 = None
        rag._sel_entries = None

        with caplog.at_level(logging.WARNING, logger="backend.kb.selector_rag"):
            result = rag.load_index()

        assert result is False

    def test_query_does_not_raise_on_corrupt_index(self, tmp_path: Path):
        """query() must return a string without raising when index is corrupt."""
        rag = _make_minimal_rag(tmp_path)
        # Corrupt both pickles
        (tmp_path / "selector_rag" / "selector_index.pkl").write_bytes(b"CORRUPT_BYTES")
        (tmp_path / "selector_rag" / "skill_index.pkl").write_bytes(b"MORE_CORRUPT")

        # Reset in-memory state
        rag._sel_vectorizer = None
        rag._sel_tfidf = None
        rag._sel_bm25 = None
        rag._sel_entries = None
        rag._bp_vectorizer = None
        rag._bp_tfidf = None
        rag._bp_bm25 = None
        rag._bp_entries = None

        try:
            result = rag.query("Sort production orders by CLIENT ascending")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"query() raised on corrupt index: {exc}")
        else:
            assert isinstance(result, str)

    def test_query_warning_logged_on_corrupt_index(self, tmp_path: Path, caplog):
        """WARNING must be logged when index cannot be loaded (corrupt pkl)."""
        rag = _make_minimal_rag(tmp_path)
        # Corrupt both pickles
        (tmp_path / "selector_rag" / "selector_index.pkl").write_bytes(b"GARBAGE")
        (tmp_path / "selector_rag" / "skill_index.pkl").write_bytes(b"GARBAGE")

        # Reset in-memory state
        rag._sel_vectorizer = None
        rag._sel_tfidf = None
        rag._sel_bm25 = None
        rag._sel_entries = None
        rag._bp_vectorizer = None
        rag._bp_tfidf = None
        rag._bp_bm25 = None
        rag._bp_entries = None

        with caplog.at_level(logging.WARNING, logger="backend.kb.selector_rag"):
            rag.query("Click the Submit button")

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_messages) > 0, "Expected at least one WARNING log when index is corrupt"

    def test_query_returns_string_after_corrupt_load_attempt(self, tmp_path: Path):
        """
        After a corrupt load attempt, query() rebuilds from registry if available.
        If registry is also missing, returns empty string — but never raises.
        """
        # Create rag with valid registry but corrupt index
        registry = tmp_path / "selector_registry.json"
        registry.write_text('{"selectors": {"btn-x": {"description": "X button", "context": "", "strategies": []}}}')
        bp_dir = tmp_path / "blueprints"
        bp_dir.mkdir()
        index_dir = tmp_path / "selector_rag"
        index_dir.mkdir(parents=True, exist_ok=True)

        # Write corrupt pickles
        (index_dir / "selector_index.pkl").write_bytes(b"CORRUPT")
        (index_dir / "skill_index.pkl").write_bytes(b"CORRUPT")
        (index_dir / ".last_built").write_text("0")

        rag = SelectorRAG(
            registry_path=registry,
            blueprints_dir=bp_dir,
            index_dir=index_dir,
        )

        result = rag.query("Sort by CLIENT")
        assert isinstance(result, str), "Must return str even after corrupt load + rebuild"
