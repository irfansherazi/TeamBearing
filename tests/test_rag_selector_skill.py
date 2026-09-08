"""
vQA — RAG Selector Skill Test Suite (AC-INDEX-1 + AC-LIFECYCLE-1)
==================================================================
Tests: tests/test_rag_selector_skill.py

Phase 1 scope:
  AC-INDEX-1  — Index Build Offline Pipeline
  AC-LIFECYCLE-1 — Auto-Rebuild on KB Update (staleness detection)

Mocking approach:
  - selector_registry.json paths mocked via tmp_path fixture
  - memory/selector_rag/ paths redirected to tmp_path for isolation
  - No real file system dependencies for the registry data
"""

import json
import pickle
import time
from pathlib import Path

import pytest

# ── Test fixtures ─────────────────────────────────────────────────────────────


def _make_minimal_registry(n: int = 5) -> dict:
    """Return a minimal selector_registry JSON structure with n entries."""
    selectors = {}
    for i in range(n):
        selectors[f"entry_{i}"] = {
            "description": f"Description for element {i} — sort table client column",
            "context": f"Visible on production orders page context {i}",
            "strategies": [
                {"method": "get_by_role", "role": "button", "name": f"Button {i}"},
                {"method": "css", "selector": f".element-{i}"},
            ],
            "timing_note": None,
        }
    return {"version": "1.0", "last_updated": "2026-01-01", "selectors": selectors}


def _make_blueprint_yaml(name: str) -> str:
    """Return a minimal blueprint YAML string."""
    return f"""name: {name}
description: Open Quick Order form and select ad type
steps:
  - description: Click New Request button to open Quick Order
  - description: Select Radio Commercial from ad type dropdown
  - description: Fill in required fields and submit order
"""


@pytest.fixture
def tmp_registry(tmp_path: Path):
    """Create a temporary selector_registry.json."""
    registry_file = tmp_path / "selector_registry.json"
    registry_file.write_text(
        json.dumps(_make_minimal_registry(n=10)),
        encoding="utf-8",
    )
    return registry_file


@pytest.fixture
def tmp_blueprints_dir(tmp_path: Path):
    """Create a temporary blueprints/ directory with sample YAMLs."""
    bp_dir = tmp_path / "blueprints"
    bp_dir.mkdir()
    for name in ["quick_order_form", "compact_view_navigate", "batch_checkbox"]:
        (bp_dir / f"{name}.yaml").write_text(_make_blueprint_yaml(name), encoding="utf-8")
    return bp_dir


@pytest.fixture
def tmp_index_dir(tmp_path: Path):
    """Create a temporary memory/selector_rag/ directory."""
    index_dir = tmp_path / "selector_rag"
    index_dir.mkdir()
    return index_dir


@pytest.fixture
def selector_rag_instance(tmp_registry, tmp_blueprints_dir, tmp_index_dir):
    """Return a SelectorRAG instance pointed at tmp paths."""
    from backend.kb.selector_rag import SelectorRAG

    return SelectorRAG(
        registry_path=tmp_registry,
        blueprints_dir=tmp_blueprints_dir,
        index_dir=tmp_index_dir,
    )


# ── AC-INDEX-1: Index Build Offline Pipeline ──────────────────────────────────


class TestIndexBuild:
    """AC-INDEX-1: Build creates correct pickle files and .last_built timestamp."""

    def test_index_build_creates_pkl_files(self, selector_rag_instance, tmp_index_dir):
        """
        AC-INDEX-1: After build_index(), selector_index.pkl and skill_index.pkl
        must exist on disk.
        """
        rag = selector_rag_instance
        rag.build_index()

        assert (tmp_index_dir / "selector_index.pkl").exists(), "selector_index.pkl must be created by build_index()"
        assert (tmp_index_dir / "skill_index.pkl").exists(), "skill_index.pkl must be created by build_index()"
        assert (tmp_index_dir / ".last_built").exists(), ".last_built timestamp file must be created by build_index()"

    def test_index_build_under_30_seconds(self, selector_rag_instance):
        """
        AC-INDEX-1: Index build must complete in ≤30s (10-entry registry, 3 blueprints).
        For full 373-entry registry the same algorithm is O(n), so this
        micro-benchmark serves as a functional gate.
        """
        rag = selector_rag_instance
        start = time.monotonic()
        rag.build_index()
        elapsed = time.monotonic() - start
        assert elapsed < 30.0, f"Index build took {elapsed:.2f}s — must complete in ≤30s"

    def test_index_build_logs_info(self, selector_rag_instance, caplog):
        """
        AC-INDEX-1: build_index() must emit an INFO log with entry counts.
        Pattern: "Selector RAG: index built — N selectors, M blueprints"
        """
        import logging

        rag = selector_rag_instance
        with caplog.at_level(logging.INFO, logger="backend.kb.selector_rag"):
            rag.build_index()

        log_text = " ".join(caplog.messages)
        assert "Selector RAG" in log_text and "index built" in log_text, (
            f"Expected 'Selector RAG: index built' in logs, got: {log_text!r}"
        )

    def test_index_pickle_is_loadable(self, selector_rag_instance, tmp_index_dir):
        """
        AC-INDEX-1: Pickled index files must be deserializable with pickle.load().
        Tests AC-INDEX-1 serialization requirement.
        """
        rag = selector_rag_instance
        rag.build_index()

        sel_idx_path = tmp_index_dir / "selector_index.pkl"
        with open(sel_idx_path, "rb") as fh:
            sel_data = pickle.load(fh)
        assert "tfidf_vectorizer" in sel_data, "selector_index.pkl missing tfidf_vectorizer key"
        assert "bm25" in sel_data, "selector_index.pkl missing bm25 key"
        assert "entries" in sel_data, "selector_index.pkl missing entries key"

    def test_index_build_from_registry_with_373_entries(self, tmp_path):
        """
        AC-INDEX-1: Build must handle the full 373-entry registry without error.
        Uses a synthetic 373-entry registry to verify scalability.
        """
        from backend.kb.selector_rag import SelectorRAG

        registry_file = tmp_path / "selector_registry.json"
        registry_file.write_text(
            json.dumps(_make_minimal_registry(n=373)),
            encoding="utf-8",
        )
        bp_dir = tmp_path / "blueprints"
        bp_dir.mkdir()
        for i in range(10):
            (bp_dir / f"blueprint_{i}.yaml").write_text(_make_blueprint_yaml(f"blueprint_{i}"), encoding="utf-8")
        index_dir = tmp_path / "selector_rag"
        index_dir.mkdir()

        rag = SelectorRAG(
            registry_path=registry_file,
            blueprints_dir=bp_dir,
            index_dir=index_dir,
        )
        start = time.monotonic()
        rag.build_index()
        elapsed = time.monotonic() - start

        assert (index_dir / "selector_index.pkl").exists()
        assert elapsed < 30.0, f"373-entry build took {elapsed:.2f}s — must be ≤30s"


# ── AC-INDEX-1: Staleness Detection ──────────────────────────────────────────


class TestIndexStalenessDetection:
    """AC-INDEX-1 + AC-LIFECYCLE-1: _is_stale() comparisons and rebuild triggers."""

    def test_index_staleness_detection_fresh_index(self, selector_rag_instance):
        """
        AC-INDEX-1: Immediately after build_index(), _is_stale() must return False.
        """
        rag = selector_rag_instance
        rag.build_index()
        assert rag._is_stale() is False, "_is_stale() must return False immediately after build_index()"

    def test_index_staleness_detection_missing_last_built(self, selector_rag_instance, tmp_index_dir):
        """
        AC-INDEX-1: _is_stale() returns True when .last_built is absent.
        Simulates a fresh install where no index has been built yet.
        """
        rag = selector_rag_instance
        # No build_index() call — .last_built does not exist
        assert rag._is_stale() is True, "_is_stale() must return True when .last_built is absent"

    def test_index_staleness_detection_registry_newer(self, selector_rag_instance, tmp_registry, tmp_index_dir):
        """
        AC-INDEX-1: _is_stale() returns True when registry mtime > .last_built mtime.
        Simulates a 'make kb-refresh' that updated the registry after index was built.
        """
        rag = selector_rag_instance
        rag.build_index()

        # Simulate registry update: touch the file to advance its mtime
        time.sleep(0.01)  # ensure mtime difference is detectable
        tmp_registry.write_text(
            json.dumps(_make_minimal_registry(n=15)),  # updated registry
            encoding="utf-8",
        )

        assert rag._is_stale() is True, "_is_stale() must return True when registry mtime > .last_built mtime"

    def test_index_staleness_detection_logs_stale_info(
        self, selector_rag_instance, tmp_registry, tmp_index_dir, caplog
    ):
        """
        AC-LIFECYCLE-1: When stale index detected, INFO log must include mtime info.
        Pattern: "Selector RAG: stale — rebuilding"
        """
        import logging

        rag = selector_rag_instance
        rag.build_index()
        time.sleep(0.01)
        tmp_registry.write_text(
            json.dumps(_make_minimal_registry(n=5)),
            encoding="utf-8",
        )

        with caplog.at_level(logging.INFO, logger="backend.kb.selector_rag"):
            is_stale = rag._is_stale()

        assert is_stale is True
        log_text = " ".join(caplog.messages)
        assert "stale" in log_text.lower(), f"Expected 'stale' in logs when index is stale, got: {log_text!r}"


# ── AC-INDEX-1: get_all_entries() on SelectorRegistry ────────────────────────


class TestSelectorRegistryGetAllEntries:
    """
    AC-INDEX-1: SelectorRegistry must expose get_all_entries() for index build.
    """

    def test_get_all_entries_returns_dict(self, tmp_path):
        """
        get_all_entries() must return a dict of all registry entries.
        """
        from backend.kb.selector_registry import SelectorRegistry

        reg_file = tmp_path / "selector_registry.json"
        reg_file.write_text(
            json.dumps(_make_minimal_registry(n=5)),
            encoding="utf-8",
        )

        # Patch path and instantiate
        import backend.kb.selector_registry as sr_mod

        original_path = sr_mod._REGISTRY_PATH
        sr_mod._REGISTRY_PATH = reg_file
        try:
            registry = SelectorRegistry()
            entries = registry.get_all_entries()
        finally:
            sr_mod._REGISTRY_PATH = original_path

        assert isinstance(entries, dict), "get_all_entries() must return a dict"
        assert len(entries) == 5, f"Expected 5 entries, got {len(entries)}"

    def test_get_all_entries_returns_empty_on_missing_registry(self, tmp_path):
        """
        get_all_entries() must return empty dict when registry is missing.
        """
        import backend.kb.selector_registry as sr_mod
        from backend.kb.selector_registry import SelectorRegistry

        original_path = sr_mod._REGISTRY_PATH
        sr_mod._REGISTRY_PATH = tmp_path / "nonexistent.json"
        try:
            registry = SelectorRegistry()
            entries = registry.get_all_entries()
        finally:
            sr_mod._REGISTRY_PATH = original_path

        assert entries == {}, "get_all_entries() must return empty dict if file missing"


# ── AC-INDEX-1: SelectorRAG.load_index() ─────────────────────────────────────


class TestLoadIndex:
    """
    AC-INDEX-1: load_index() must restore state from pickled files.
    """

    def test_load_index_restores_state(self, selector_rag_instance, tmp_index_dir):
        """
        After build_index() + load_index(), the rag instance must have
        _sel_vectorizer, _sel_bm25, and _sel_entries populated.
        """
        rag = selector_rag_instance
        rag.build_index()

        # Create fresh instance, load without building
        from backend.kb.selector_rag import SelectorRAG

        rag2 = SelectorRAG(
            registry_path=rag._registry_path,
            blueprints_dir=rag._blueprints_dir,
            index_dir=tmp_index_dir,
        )
        loaded = rag2.load_index()

        assert loaded is True, "load_index() must return True on success"
        assert rag2._sel_vectorizer is not None, "_sel_vectorizer must be populated"
        assert rag2._sel_bm25 is not None, "_sel_bm25 must be populated"
        assert rag2._sel_entries is not None and len(rag2._sel_entries) > 0, (
            "_sel_entries must be non-empty after load_index()"
        )

    def test_load_index_returns_false_on_missing_pkl(self, selector_rag_instance, tmp_index_dir):
        """
        load_index() must return False gracefully when pkl files are absent.
        """
        rag = selector_rag_instance
        # Don't call build_index() — no pkl files exist
        loaded = rag.load_index()
        assert loaded is False, "load_index() must return False when pkl files absent"

    def test_load_index_returns_false_on_corrupt_pkl(self, selector_rag_instance, tmp_index_dir):
        """
        load_index() must return False gracefully when pkl is corrupt.
        """
        rag = selector_rag_instance
        # Write garbage data as the selector_index.pkl
        (tmp_index_dir / "selector_index.pkl").write_bytes(b"corrupted data here!")
        (tmp_index_dir / "skill_index.pkl").write_bytes(b"also corrupted!")

        loaded = rag.load_index()
        assert loaded is False, "load_index() must return False on corrupt pkl"
