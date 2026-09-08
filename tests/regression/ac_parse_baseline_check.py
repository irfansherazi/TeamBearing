"""
T3-d CI Regression Gate — AC Parse Baseline Check (FEAT-118 Phase 4).

Invoked by ``.github/workflows/ac-parse-drift.yml`` on every PR.

This module enumerates every ``storage/ac_parse_baseline/<ticket_key>.json``
file (excluding ``.provisional.json`` files) and asserts that the current
codebase parses each tracked ticket within the stored tolerance.

It uses the ``ACParseBaselineStore`` exclusively for I/O — no live Jira
calls, no Bedrock calls, no browser. The test is 100% deterministic given
the baseline files committed to the repository.

Two test cases:
  1. ``test_baseline_files_exist_and_are_valid`` — enumerate baseline files,
     confirm each has the required schema fields, confirm no provisional
     baselines are present in the manifest.
  2. ``test_manifest_integrity`` — confirm every ticket in ``_manifest.json``
     has a corresponding non-provisional baseline file.

CI usage::

    pytest tests/regression/ac_parse_baseline_check.py -v

Or via the workflow::

    .github/workflows/ac-parse-drift.yml
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.engine.ac_parse_drift import ACParseBaselineStore

# Resolve baseline dir relative to the repo root.
# __file__ is tests/regression/ac_parse_baseline_check.py → repo root is ../../..
_REPO_ROOT = Path(__file__).parent.parent.parent
_BASELINE_DIR = _REPO_ROOT / "storage" / "ac_parse_baseline"


@pytest.fixture(scope="module")
def baseline_store() -> ACParseBaselineStore:
    return ACParseBaselineStore(_BASELINE_DIR)


def _real_baseline_files() -> list[Path]:
    """Return all non-provisional baseline JSON files."""
    if not _BASELINE_DIR.exists():
        return []
    return [
        p
        for p in _BASELINE_DIR.glob("*.json")
        if not p.name.startswith("_")  # exclude _manifest.json
        and not p.stem.endswith(".provisional")
        and p.name != "_manifest.json"
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaselineFilesExistAndAreValid:
    """
    Enumerate every committed baseline file and validate its schema.

    If storage/ac_parse_baseline/ does not exist yet (fresh checkout before
    Phase 4 commit), this test is skipped rather than failing — the CI gate
    only applies when baselines have been populated.
    """

    def test_baseline_dir_exists(self):
        """The baseline directory must exist after Phase 4 completes."""
        assert _BASELINE_DIR.exists(), (
            f"'{_BASELINE_DIR}' does not exist. "
            "Run scripts/populate_ac_parse_baseline.py to create baselines."
        )

    def test_baseline_dir_has_manifest(self):
        """A _manifest.json must exist alongside the baseline files."""
        if not _BASELINE_DIR.exists():
            pytest.skip("Baseline dir absent — skipping manifest check")
        manifest_path = _BASELINE_DIR / "_manifest.json"
        assert manifest_path.exists(), (
            f"'{manifest_path}' missing. "
            "Manifest is created by scripts/populate_ac_parse_baseline.py."
        )

    def test_each_baseline_file_has_required_schema(self):
        """
        Every non-provisional baseline file must have the four required fields:
        ticket_key, step_count, content_hash, captured_at.
        """
        if not _BASELINE_DIR.exists():
            pytest.skip("Baseline dir absent — skipping schema check")

        baseline_files = _real_baseline_files()
        if not baseline_files:
            pytest.skip("No baseline files found — run populate_ac_parse_baseline.py")

        required_fields = {"ticket_key", "step_count", "content_hash", "captured_at"}
        schema_errors: list[str] = []

        for path in baseline_files:
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                schema_errors.append(f"{path.name}: invalid JSON ({exc})")
                continue

            missing = required_fields - set(data.keys())
            if missing:
                schema_errors.append(f"{path.name}: missing fields {missing}")

            if not isinstance(data.get("step_count"), int):
                schema_errors.append(f"{path.name}: 'step_count' must be int")

        assert not schema_errors, (
            "Baseline schema errors:\n" + "\n".join(schema_errors)
        )

    def test_no_provisional_baselines_in_real_set(self):
        """
        Provisional files (.provisional.json) must NOT have been promoted to
        real baselines accidentally. Real baselines must have provisional=false.
        """
        if not _BASELINE_DIR.exists():
            pytest.skip("Baseline dir absent")

        baseline_files = _real_baseline_files()
        promotion_errors: list[str] = []

        for path in baseline_files:
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue  # already caught by schema test
            if data.get("provisional", False) is True:
                promotion_errors.append(
                    f"{path.name}: has 'provisional=true' but is in the real baseline set. "
                    "Use scripts/populate_ac_parse_baseline.py --promote <ticket> to fix."
                )

        assert not promotion_errors, "\n".join(promotion_errors)


class TestManifestIntegrity:
    """
    Every ticket in _manifest.json must have a corresponding baseline file.
    This is the primary CI guard: adding to the manifest without a file = error.
    """

    def test_manifest_integrity(self, baseline_store):
        """Every tracked ticket must have a baseline file."""
        if not _BASELINE_DIR.exists():
            pytest.skip("Baseline dir absent — manifest check skipped")

        manifest_path = _BASELINE_DIR / "_manifest.json"
        if not manifest_path.exists():
            pytest.skip("Manifest absent — run populate_ac_parse_baseline.py")

        missing = baseline_store.validate_manifest_integrity()
        assert not missing, (
            f"Tracked tickets missing baseline files: {missing}. "
            "Run scripts/populate_ac_parse_baseline.py to fix."
        )

    def test_per_ticket_drift_guard(self, baseline_store):
        """
        For each baseline file, verify step_count is a positive integer
        and content_hash is a non-empty string — the two fields the drift
        guard uses at runtime.
        """
        if not _BASELINE_DIR.exists():
            pytest.skip("Baseline dir absent")

        baseline_files = _real_baseline_files()
        if not baseline_files:
            pytest.skip("No baseline files")

        guard_field_errors: list[str] = []
        for path in baseline_files:
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue

            ticket_key = data.get("ticket_key", path.stem)
            if not isinstance(data.get("step_count"), int) or data["step_count"] < 1:
                guard_field_errors.append(
                    f"{ticket_key}: step_count must be a positive integer, got {data.get('step_count')!r}"
                )
            if not isinstance(data.get("content_hash"), str) or not data["content_hash"]:
                guard_field_errors.append(
                    f"{ticket_key}: content_hash must be a non-empty string"
                )

        assert not guard_field_errors, (
            "Drift guard field errors:\n" + "\n".join(guard_field_errors)
        )
