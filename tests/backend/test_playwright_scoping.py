"""
tests/backend/test_playwright_scoping.py
==========================================
TDD tests for TASK-124, Phase 5: Per-Product Playwright Test Organization.

Covers:
- PlaywrightRegistry.list_tests_for_product() unit tests:
    - Returns only vpromedia tests when playwright_tests_dir="playwright/tests/vpromedia"
    - Returns empty list for a product with no tests (vtrade)
    - Filters correctly from a mixed-product registry
- GET /playwright/tests (no product) returns all tests — backwards compat
- GET /playwright/tests?product=vpromedia returns only vpromedia tests
- GET /playwright/tests?product=vtrade returns empty list
- GET /playwright/tests?product=unknown_slug returns 422
- GET /playwright/match/QA-100?product=vpromedia returns matched=True
- GET /playwright/match/QA-100?product=vtrade returns matched=False
- GET /playwright/match/QA-100 (no product) returns all matches — backwards compat

ALL TESTS SHOULD FAIL until Phase 5 implementation is complete (TDD RED phase).
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.main import app
from backend.storage.playwright_registry import PlaywrightRegistry


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Simulated post-Phase-5 index: all entries have paths under tests/vpromedia/
# (After Phase 5 the real index will have paths like tests/vpromedia/qa-100-*.test.ts)
VPROMEDIA_INDEX_ENTRIES = [
    {
        "id": "qa-100-script-library.test",
        "file": "tests/vpromedia/qa-100-script-library.test.ts",
        "jira_keys": ["QA-100"],
        "description": "QA-100: Script Library",
        "steps_count": 4,
        "step_names": ["Phase 1 & 2: Send script to library"],
    },
    {
        "id": "qa-101-client-merging.test",
        "file": "tests/vpromedia/qa-101-client-merging.test.ts",
        "jira_keys": ["QA-101"],
        "description": "QA-101: Client Merging",
        "steps_count": 6,
        "step_names": ["Ensure"],
    },
    {
        "id": "qa-125-new-user-experience.test",
        "file": "tests/vpromedia/qa-125-new-user-experience.test.ts",
        "jira_keys": ["QA-125"],
        "description": "QA-125: New User Experience",
        "steps_count": 3,
        "step_names": ["Step 1"],
    },
]

# A hypothetical vtrade test entry (no such tests exist in Phase 5 yet)
VTRADE_INDEX_ENTRIES = [
    {
        "id": "vt-001-trade-order.test",
        "file": "tests/vtrade/vt-001-trade-order.test.ts",
        "jira_keys": ["VT-1"],
        "description": "VT-001: Trade Order",
        "steps_count": 2,
        "step_names": ["Login", "Create Order"],
    }
]

# Mixed index — vpromedia + vtrade entries combined
MIXED_INDEX_ENTRIES = VPROMEDIA_INDEX_ENTRIES + VTRADE_INDEX_ENTRIES


@pytest.fixture()
def vpromedia_registry_file(tmp_path: Path) -> Path:
    """Write a temp playwright_index.json containing only vpromedia tests."""
    index_file = tmp_path / "playwright_index.json"
    index_file.write_text(json.dumps(VPROMEDIA_INDEX_ENTRIES))
    return index_file


@pytest.fixture()
def mixed_registry_file(tmp_path: Path) -> Path:
    """Write a temp playwright_index.json containing vpromedia + vtrade tests."""
    index_file = tmp_path / "playwright_index.json"
    index_file.write_text(json.dumps(MIXED_INDEX_ENTRIES))
    return index_file


@pytest.fixture()
def empty_registry_file(tmp_path: Path) -> Path:
    """Write an empty playwright_index.json."""
    index_file = tmp_path / "playwright_index.json"
    index_file.write_text("[]")
    return index_file


@pytest.fixture()
def test_client():
    """Synchronous TestClient for fast route tests."""
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# 1. PlaywrightRegistry.list_tests_for_product() — unit tests
# ---------------------------------------------------------------------------


class TestPlaywrightRegistryListTestsForProduct:
    """PlaywrightRegistry.list_tests_for_product() filters tests by product directory prefix."""

    def test_returns_only_vpromedia_tests_when_vpromedia_dir_given(
        self, vpromedia_registry_file: Path, tmp_path: Path
    ):
        """list_tests_for_product('playwright/tests/vpromedia') returns all 3 vpromedia tests."""
        registry = PlaywrightRegistry(
            tests_dir=str(tmp_path),
            registry_file=str(vpromedia_registry_file),
        )
        results = registry.list_tests_for_product("playwright/tests/vpromedia")
        assert len(results) == 3
        for test in results:
            assert test["file"].startswith("tests/vpromedia/"), (
                f"Expected vpromedia path prefix, got: {test['file']}"
            )

    def test_returns_empty_list_when_vtrade_dir_given_and_no_vtrade_tests(
        self, vpromedia_registry_file: Path, tmp_path: Path
    ):
        """list_tests_for_product('playwright/tests/vtrade') returns [] when no vtrade tests exist."""
        registry = PlaywrightRegistry(
            tests_dir=str(tmp_path),
            registry_file=str(vpromedia_registry_file),
        )
        results = registry.list_tests_for_product("playwright/tests/vtrade")
        assert results == [], (
            f"Expected empty list for vtrade, got: {results}"
        )

    def test_filters_correctly_from_mixed_index(
        self, mixed_registry_file: Path, tmp_path: Path
    ):
        """list_tests_for_product() returns only the matching product's tests from a mixed index."""
        registry = PlaywrightRegistry(
            tests_dir=str(tmp_path),
            registry_file=str(mixed_registry_file),
        )
        vpromedia_results = registry.list_tests_for_product("playwright/tests/vpromedia")
        vtrade_results = registry.list_tests_for_product("playwright/tests/vtrade")

        # vpromedia: 3 tests; vtrade: 1 test
        assert len(vpromedia_results) == 3
        assert len(vtrade_results) == 1

        # No cross-contamination
        assert all(t["file"].startswith("tests/vpromedia/") for t in vpromedia_results)
        assert all(t["file"].startswith("tests/vtrade/") for t in vtrade_results)

    def test_list_tests_for_product_does_not_modify_list_tests_output(
        self, vpromedia_registry_file: Path, tmp_path: Path
    ):
        """list_tests() (no filter) still returns all tests after calling list_tests_for_product()."""
        registry = PlaywrightRegistry(
            tests_dir=str(tmp_path),
            registry_file=str(vpromedia_registry_file),
        )
        # Call filtered version first
        registry.list_tests_for_product("playwright/tests/vtrade")
        # Then confirm all tests still returned
        all_tests = registry.list_tests()
        assert len(all_tests) == 3

    def test_list_tests_for_product_returns_correct_ids(
        self, mixed_registry_file: Path, tmp_path: Path
    ):
        """Returned test dicts preserve all fields including id and jira_keys."""
        registry = PlaywrightRegistry(
            tests_dir=str(tmp_path),
            registry_file=str(mixed_registry_file),
        )
        results = registry.list_tests_for_product("playwright/tests/vtrade")
        assert len(results) == 1
        assert results[0]["id"] == "vt-001-trade-order.test"
        assert "VT-1" in results[0]["jira_keys"]


# ---------------------------------------------------------------------------
# 2. GET /playwright/tests?product=<slug> — route tests
# ---------------------------------------------------------------------------


class TestListPlaywrightTestsWithProductFilter:
    """GET /playwright/tests with and without ?product= query param."""

    def test_no_product_param_returns_all_tests(self, test_client: TestClient):
        """
        GET /playwright/tests with no product param must return all tests
        (backwards compatibility — no regression from Phase 5).
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/tests")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 3

    def test_product_vpromedia_returns_only_vpromedia_tests(self, test_client: TestClient):
        """
        GET /playwright/tests?product=vpromedia must call list_tests_for_product()
        with the vpromedia playwright_tests_dir and return only matching tests.
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/tests?product=vpromedia")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            # All returned tests should be for vpromedia
            for test in data:
                assert "vpromedia" in test.get("file", ""), (
                    f"Expected vpromedia in file path, got: {test.get('file')}"
                )

    def test_product_vtrade_returns_empty_list(self, test_client: TestClient):
        """
        GET /playwright/tests?product=vtrade returns [] when no vtrade tests exist.
        vtrade stub dirs are created but contain no tests in Phase 5.
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/tests?product=vtrade")
            assert response.status_code == 200
            data = response.json()
            assert data == [], (
                f"Expected empty list for vtrade, got: {data}"
            )

    def test_unknown_product_slug_returns_422(self, test_client: TestClient):
        """
        GET /playwright/tests?product=unknown_slug must return 422 (Unprocessable Entity)
        because the product slug is not in the product registry.
        """
        response = test_client.get("/api/playwright/tests?product=unknown_slug_xyz")
        assert response.status_code == 422, (
            f"Expected 422 for unknown product slug, got: {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 3. GET /playwright/match/{ticket_id}?product=<slug> — route tests
# ---------------------------------------------------------------------------


class TestMatchPlaywrightTestWithProductFilter:
    """GET /playwright/match/{ticket_id} with and without ?product= query param."""

    def test_match_qa100_with_product_vpromedia_returns_matched_true(
        self, test_client: TestClient
    ):
        """
        GET /playwright/match/QA-100?product=vpromedia must return matched=True
        because QA-100 maps to tests/vpromedia/qa-100-script-library.test.ts
        after the Phase 5 index update.
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/match/QA-100?product=vpromedia")
            assert response.status_code == 200
            data = response.json()
            assert data["matched"] is True, (
                "QA-100 is a vpromedia test — should match when product=vpromedia"
            )
            assert len(data["tests"]) > 0

    def test_match_qa100_with_product_vtrade_returns_matched_false(
        self, test_client: TestClient
    ):
        """
        GET /playwright/match/QA-100?product=vtrade must return matched=False
        because QA-100 is in tests/vpromedia/, not tests/vtrade/.
        Even if the test is in the global index, it should not appear for vtrade.
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/match/QA-100?product=vtrade")
            assert response.status_code == 200
            data = response.json()
            assert data["matched"] is False, (
                "QA-100 is NOT a vtrade test — should not match when product=vtrade"
            )
            assert data["tests"] == []

    def test_match_qa100_without_product_returns_all_matches(
        self, test_client: TestClient
    ):
        """
        GET /playwright/match/QA-100 (no product param) must return matched=True
        using the global index search — backwards compatibility preserved.
        """
        with patch(
            "backend.api.playwright_routes._get_registry",
        ) as mock_get_registry:
            mock_registry = _make_mock_registry(VPROMEDIA_INDEX_ENTRIES)
            mock_get_registry.return_value = mock_registry

            response = test_client.get("/api/playwright/match/QA-100")
            assert response.status_code == 200
            data = response.json()
            assert data["matched"] is True, (
                "QA-100 must still match without a product filter (backwards compat)"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockRegistry:
    """Minimal mock registry for route tests — avoids filesystem hits."""

    def __init__(self, entries: list):
        self._entries = entries

    def list_tests(self) -> list:
        return self._entries

    def list_tests_for_product(self, playwright_tests_dir: str) -> list:
        # Derive relative prefix: "playwright/tests/vpromedia" → "tests/vpromedia/"
        parts = playwright_tests_dir.split("playwright/", 1)
        if len(parts) == 2:
            prefix = parts[1].rstrip("/") + "/"
        else:
            prefix = playwright_tests_dir.rstrip("/") + "/"
        return [t for t in self._entries if t.get("file", "").startswith(prefix)]

    def get_tests_by_jira_key(self, key: str) -> list:
        normalized = key.strip().upper()
        return [
            t for t in self._entries
            if any(normalized == k.strip().upper() for k in t.get("jira_keys", []))
        ]

    def get_tests_by_jira_key_for_product(self, key: str, playwright_tests_dir: str) -> list:
        product_tests = self.list_tests_for_product(playwright_tests_dir)
        normalized = key.strip().upper()
        return [
            t for t in product_tests
            if any(normalized == k.strip().upper() for k in t.get("jira_keys", []))
        ]

    def get_valid_ids(self) -> set:
        return {t.get("id") for t in self._entries if t.get("id")}

    def refresh(self) -> None:
        pass


def _make_mock_registry(entries: list) -> _MockRegistry:
    return _MockRegistry(entries)
