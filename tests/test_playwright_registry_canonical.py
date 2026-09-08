"""
tests/test_playwright_registry_canonical.py
============================================
Unit tests for PlaywrightRegistry with the canonical playwright_index.json.

Tests:
  - Registry loads from JSON index file (not filesystem scan)
  - list_tests() returns all entries
  - get_test() performs allow-list lookup by id
  - get_valid_ids() returns set of all ids
  - refresh() reloads from file
  - Missing/corrupt file gracefully returns empty list
"""

import json
from pathlib import Path

import pytest

from backend.storage.playwright_registry import PlaywrightRegistry

# ---------------------------------------------------------------------------
# Sample index data matching the real playwright_index.json structure
# ---------------------------------------------------------------------------

SAMPLE_INDEX = [
    {
        "id": "qa-321-sorting-list-and-compact.test",
        "file": "tests/qa-321-sorting-list-and-compact.test.ts",
        "jira_keys": ["QA-321"],
        "description": "QA-321: List and Compact View Sorting",
        "steps_count": 1,
        "step_names": ["Execute Sorting End-to-End Workflows"],
    },
    {
        "id": "qa-100-script-library.test",
        "file": "tests/qa-100-script-library.test.ts",
        "jira_keys": ["QA-100"],
        "description": "QA-100: Script Library",
        "steps_count": 4,
        "step_names": [
            "Phase 1 & 2: Send script to library",
            "Phase 3: Manage library",
            "Phase 4: Permission Testing",
            "Phase 5: Script Timer Integration",
        ],
    },
    {
        "id": "vc2-8821-memory-leak.test",
        "file": "tests/vc2-8821-memory-leak.test.ts",
        "jira_keys": ["VC2-8821"],
        "description": "VC2-8821: Memory Leak Detection",
        "steps_count": 0,
        "step_names": [],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_index_file(tmp_path: Path):
    """Create a temporary JSON index file with sample data."""
    index_file = tmp_path / "playwright_index.json"
    index_file.write_text(json.dumps(SAMPLE_INDEX))
    return index_file


@pytest.fixture
def registry(tmp_path: Path, temp_index_file: Path) -> PlaywrightRegistry:
    """Instantiate a registry pointing at the temp index."""
    return PlaywrightRegistry(
        tests_dir=str(tmp_path / "tests"),
        registry_file=str(temp_index_file),
    )


# ---------------------------------------------------------------------------
# Tests: AC-BACK-1 / AC-BACK-2 — Registry loads canonical index
# ---------------------------------------------------------------------------


def test_registry_loads_json_index(registry: PlaywrightRegistry):
    """AC-BACK-1: Registry reads from JSON index, not filesystem scan."""
    tests = registry.list_tests()
    assert len(tests) == len(SAMPLE_INDEX), f"Expected {len(SAMPLE_INDEX)} tests, got {len(tests)}"


def test_registry_returns_full_metadata(registry: PlaywrightRegistry):
    """AC-BACK-2: Each entry includes id, file, jira_keys, description, steps_count, step_names."""
    tests = registry.list_tests()
    for entry in tests:
        assert "id" in entry, "Missing 'id' field"
        assert "file" in entry, "Missing 'file' field"
        assert "jira_keys" in entry, "Missing 'jira_keys' field"
        assert isinstance(entry["jira_keys"], list), "'jira_keys' must be a list"
        assert "description" in entry, "Missing 'description' field"
        assert "steps_count" in entry, "Missing 'steps_count' field"
        assert "step_names" in entry, "Missing 'step_names' field"
        assert isinstance(entry["step_names"], list), "'step_names' must be a list"


# ---------------------------------------------------------------------------
# Tests: Allow-list lookup
# ---------------------------------------------------------------------------


def test_get_test_returns_matching_entry(registry: PlaywrightRegistry):
    """get_test() returns the matching dict for a known ID."""
    result = registry.get_test("qa-321-sorting-list-and-compact.test")
    assert result is not None
    assert result["id"] == "qa-321-sorting-list-and-compact.test"
    assert result["jira_keys"] == ["QA-321"]


def test_get_test_returns_none_for_unknown_id(registry: PlaywrightRegistry):
    """get_test() returns None for an ID not in the index (AC-BACK-3)."""
    result = registry.get_test("nonexistent-test-id")
    assert result is None


def test_get_test_returns_none_for_injection_attempt(registry: PlaywrightRegistry):
    """get_test() returns None for a shell injection attempt."""
    result = registry.get_test("; rm -rf /")
    assert result is None


def test_get_valid_ids_returns_all_ids(registry: PlaywrightRegistry):
    """get_valid_ids() returns a set of all IDs in the index."""
    valid_ids = registry.get_valid_ids()
    assert isinstance(valid_ids, set)
    assert "qa-321-sorting-list-and-compact.test" in valid_ids
    assert "qa-100-script-library.test" in valid_ids
    assert "vc2-8821-memory-leak.test" in valid_ids
    assert len(valid_ids) == len(SAMPLE_INDEX)


# ---------------------------------------------------------------------------
# Tests: Refresh and file handling
# ---------------------------------------------------------------------------


def test_refresh_reloads_from_file(tmp_path: Path, temp_index_file: Path):
    """refresh() reloads tests after the index file changes."""
    registry = PlaywrightRegistry(
        tests_dir=str(tmp_path / "tests"),
        registry_file=str(temp_index_file),
    )
    assert len(registry.list_tests()) == len(SAMPLE_INDEX)

    # Overwrite with a longer index
    new_index = SAMPLE_INDEX + [
        {
            "id": "new-test.test",
            "file": "tests/new-test.test.ts",
            "jira_keys": [],
            "description": "New test",
            "steps_count": 1,
            "step_names": ["Step 1"],
        }
    ]
    temp_index_file.write_text(json.dumps(new_index))

    registry.refresh()
    assert len(registry.list_tests()) == len(SAMPLE_INDEX) + 1


def test_missing_index_file_returns_empty_list(tmp_path: Path):
    """Missing index file returns empty list (no crash)."""
    registry = PlaywrightRegistry(
        tests_dir=str(tmp_path / "tests"),
        registry_file=str(tmp_path / "nonexistent.json"),
    )
    assert registry.list_tests() == []
    assert registry.get_test("anything") is None
    assert registry.get_valid_ids() == set()


def test_corrupt_index_file_returns_empty_list(tmp_path: Path):
    """Corrupt JSON index file returns empty list (no crash)."""
    index_file = tmp_path / "corrupt.json"
    index_file.write_text("NOT VALID JSON {{{")
    registry = PlaywrightRegistry(
        tests_dir=str(tmp_path / "tests"),
        registry_file=str(index_file),
    )
    assert registry.list_tests() == []


# ---------------------------------------------------------------------------
# Tests: Real index file (integration smoke)
# ---------------------------------------------------------------------------


def test_real_playwright_index_has_minimum_entries():
    """
    Integration smoke: the real playwright_index.json has >= 35 entries (AC-ENTRY-3).

    This test is skipped if the file doesn't exist (e.g. in CI without the repo).
    """
    real_index = Path("playwright/playwright_index.json")
    if not real_index.exists():
        pytest.skip("playwright/playwright_index.json not found (not in CI scope)")

    registry = PlaywrightRegistry(
        tests_dir="playwright/tests",
        registry_file=str(real_index),
    )
    tests = registry.list_tests()
    assert len(tests) >= 35, f"Expected >= 35 tests, got {len(tests)}"


def test_real_playwright_index_entries_have_required_fields():
    """
    Integration smoke: all entries in playwright_index.json have required fields.
    """
    real_index = Path("playwright/playwright_index.json")
    if not real_index.exists():
        pytest.skip("playwright/playwright_index.json not found (not in CI scope)")

    registry = PlaywrightRegistry(
        tests_dir="playwright/tests",
        registry_file=str(real_index),
    )
    tests = registry.list_tests()
    for entry in tests:
        assert "id" in entry
        assert "file" in entry
        assert "jira_keys" in entry
        assert "description" in entry
        assert "steps_count" in entry
        assert "step_names" in entry
