"""
Tests for T3-d AC Parse Drift Guard (FEAT-118 Phase 4).

Test strategy (per task file Phase-4 test guidance):
  - test_drift_fails_run:            step count deviates > tolerance → ACParseDriftError raised
  - test_no_drift_passes:            step count within tolerance → returns passing ACParseDriftResult
  - test_baseline_missing_behavior:  tracked ticket with missing baseline file → ACParseDriftError
  - test_untracked_writes_provisional: un-tracked ticket → provisional baseline written, run continues

RED phase: all assertions against ACParseBaselineStore / ACParseDriftGuard
before any implementation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from backend.engine.ac_parse_drift import (
    ACParseDriftError,
    ACParseDriftGuard,
    ACParseDriftResult,
    ACParseBaselineStore,
    BaselineRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_baseline_dir(tmp_path):
    """Return a fresh temporary directory for baseline files."""
    return tmp_path / "ac_parse_baseline"


@pytest.fixture()
def store(tmp_baseline_dir):
    """Return an ACParseBaselineStore backed by a temp directory."""
    return ACParseBaselineStore(tmp_baseline_dir)


def _seed_baseline(store: ACParseBaselineStore, ticket_key: str, step_count: int, content_hash: str = "abc123") -> None:
    """Helper: write a real baseline file and add the ticket to the manifest."""
    store.ensure_dir()
    record = BaselineRecord(
        ticket_key=ticket_key,
        step_count=step_count,
        content_hash=content_hash,
        captured_at="2026-07-29T00:00:00+00:00",
        captured_from="test_seed",
    )
    store.save(record)
    store.add_to_manifest(ticket_key, {"added_at": "2026-07-29T00:00:00+00:00"})


def _make_guard(tmp_baseline_dir, enabled: bool = True, tolerance: int = 2) -> ACParseDriftGuard:
    return ACParseDriftGuard(baseline_dir=tmp_baseline_dir, enabled=enabled, tolerance=tolerance)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDriftFailsRun:
    """
    AC-ERROR-2: A synthetic parse whose step count deviates > ±2 must
    raise ACParseDriftError; the run's terminal status MUST be 'failed'.
    """

    def test_drift_above_tolerance_raises(self, store, tmp_baseline_dir):
        """Baseline=6, current=9, delta=3 > tolerance=2 → ACParseDriftError."""
        _seed_baseline(store, "QA-358", step_count=6, content_hash="same_hash")
        guard = _make_guard(tmp_baseline_dir, tolerance=2)

        with pytest.raises(ACParseDriftError) as exc_info:
            guard.assert_drift(
                ticket_key="QA-358",
                current_step_count=9,
                raw_ac="same_hash_ac_text",  # hash won't match perfectly but drift check still fires
                run_id="test-run-drift-above",
            )

        err = exc_info.value
        assert err.ticket_key == "QA-358"
        assert err.baseline_step_count == 6
        assert err.current_step_count == 9
        assert err.delta == 3
        assert "AC_PARSE_DRIFT" in str(err)

    def test_drift_below_tolerance_raises(self, store, tmp_baseline_dir):
        """Baseline=8, current=4, delta=4 > tolerance=2 → ACParseDriftError."""
        _seed_baseline(store, "QA-196", step_count=8)
        guard = _make_guard(tmp_baseline_dir, tolerance=2)

        with pytest.raises(ACParseDriftError) as exc_info:
            guard.assert_drift(
                ticket_key="QA-196",
                current_step_count=4,
                raw_ac="some raw ac text",
                run_id="test-run-drift-below",
            )

        err = exc_info.value
        assert err.baseline_step_count == 8
        assert err.current_step_count == 4
        assert err.delta == 4

    def test_drift_exactly_at_tolerance_passes(self, store, tmp_baseline_dir):
        """Baseline=6, current=8, delta=2 == tolerance=2 → PASS (not raise)."""
        _seed_baseline(store, "QA-300", step_count=6)
        guard = _make_guard(tmp_baseline_dir, tolerance=2)

        result = guard.assert_drift(
            ticket_key="QA-300",
            current_step_count=8,
            raw_ac="some raw ac text",
            run_id="test-run-at-tolerance",
        )
        assert not result.drift_detected
        assert result.delta == 2


class TestNoDriftPasses:
    """
    A step count within tolerance must not raise and must return a passing result.
    """

    def test_identical_step_count_passes(self, store, tmp_baseline_dir):
        """Baseline=7, current=7, delta=0 → PASS."""
        _seed_baseline(store, "QA-358", step_count=7)
        guard = _make_guard(tmp_baseline_dir)

        result = guard.assert_drift(
            ticket_key="QA-358",
            current_step_count=7,
            raw_ac="raw ac text",
            run_id="test-run-identical",
        )

        assert isinstance(result, ACParseDriftResult)
        assert not result.drift_detected
        assert result.delta == 0
        assert result.baseline_step_count == 7
        assert result.current_step_count == 7

    def test_within_tolerance_positive_passes(self, store, tmp_baseline_dir):
        """Baseline=5, current=7, delta=2 ≤ tolerance=2 → PASS."""
        _seed_baseline(store, "QA-196", step_count=5)
        guard = _make_guard(tmp_baseline_dir, tolerance=2)

        result = guard.assert_drift(
            ticket_key="QA-196",
            current_step_count=7,
            raw_ac="some text",
            run_id="test-run-within-positive",
        )
        assert not result.drift_detected
        assert result.delta == 2

    def test_within_tolerance_negative_passes(self, store, tmp_baseline_dir):
        """Baseline=7, current=5, delta=2 ≤ tolerance=2 → PASS."""
        _seed_baseline(store, "QA-303", step_count=7)
        guard = _make_guard(tmp_baseline_dir, tolerance=2)

        result = guard.assert_drift(
            ticket_key="QA-303",
            current_step_count=5,
            raw_ac="some text",
            run_id="test-run-within-negative",
        )
        assert not result.drift_detected
        assert result.delta == 2


class TestBaselineMissingBehavior:
    """
    CQ-D2: A tracked ticket whose baseline file is missing must fail-fast.
    The manifest names the ticket but the .json file doesn't exist.
    """

    def test_tracked_missing_baseline_raises(self, store, tmp_baseline_dir):
        """Ticket is in manifest but .json file absent → ACParseDriftError."""
        store.ensure_dir()
        # Add to manifest but do NOT write a baseline file
        store.add_to_manifest("QA-999", {"added_at": "2026-07-29T00:00:00+00:00"})
        guard = _make_guard(tmp_baseline_dir)

        with pytest.raises(ACParseDriftError) as exc_info:
            guard.assert_drift(
                ticket_key="QA-999",
                current_step_count=5,
                raw_ac="raw ac",
                run_id="test-run-missing",
            )

        err = exc_info.value
        assert err.ticket_key == "QA-999"
        # Missing baseline means step_count=0 used as sentinel
        assert err.baseline_step_count == 0

    def test_disabled_guard_skips_even_missing_baseline(self, store, tmp_baseline_dir):
        """When guard is disabled, even missing tracked baselines don't raise."""
        store.ensure_dir()
        store.add_to_manifest("QA-998")
        guard = _make_guard(tmp_baseline_dir, enabled=False)

        result = guard.assert_drift(
            ticket_key="QA-998",
            current_step_count=10,
            raw_ac="anything",
            run_id="test-run-disabled",
        )
        assert result.skipped


class TestUntrackedWritesProvisional:
    """
    CQ-D2: Un-tracked tickets must write a provisional baseline and NOT fail the run.
    """

    def test_untracked_ticket_writes_provisional(self, store, tmp_baseline_dir):
        """Un-tracked ticket → provisional file created, result.provisioned=True."""
        store.ensure_dir()  # Dir exists but manifest is empty
        guard = _make_guard(tmp_baseline_dir)

        result = guard.assert_drift(
            ticket_key="QA-UNKNOWN",
            current_step_count=5,
            raw_ac="raw ac text for unknown ticket",
            run_id="test-run-untracked",
        )

        assert result.provisioned
        assert not result.drift_detected
        assert result.current_step_count == 5

        # Provisional baseline file must exist
        provisional_path = tmp_baseline_dir / "QA-UNKNOWN.provisional.json"
        assert provisional_path.exists()
        data = json.loads(provisional_path.read_text())
        assert data["ticket_key"] == "QA-UNKNOWN"
        assert data["step_count"] == 5
        assert data["provisional"] is True

    def test_untracked_does_not_add_to_manifest(self, store, tmp_baseline_dir):
        """Provisional baseline must NOT enter the manifest (would make it tracked)."""
        store.ensure_dir()
        guard = _make_guard(tmp_baseline_dir)

        guard.assert_drift(
            ticket_key="QA-PROVISIONAL",
            current_step_count=4,
            raw_ac="some raw ac",
            run_id="test-run-provisional",
        )

        manifest = store.load_manifest()
        assert "QA-PROVISIONAL" not in manifest

    def test_no_baseline_dir_skips_gracefully(self, tmp_path):
        """If the entire baseline dir is absent, guard skips without raising."""
        nonexistent_dir = tmp_path / "does_not_exist"
        guard = ACParseDriftGuard(baseline_dir=nonexistent_dir)

        result = guard.assert_drift(
            ticket_key="QA-000",
            current_step_count=3,
            raw_ac="some text",
            run_id="test-no-dir",
        )
        assert result.skipped


# ---------------------------------------------------------------------------
# ACParseBaselineStore unit tests
# ---------------------------------------------------------------------------


class TestACParseBaselineStore:
    """Unit tests for the low-level store."""

    def test_save_and_load_roundtrip(self, store, tmp_baseline_dir):
        store.ensure_dir()
        record = BaselineRecord(
            ticket_key="QA-123",
            step_count=8,
            content_hash="abc123def456",
            captured_at="2026-07-29T00:00:00+00:00",
        )
        store.save(record)
        loaded = store.load("QA-123")
        assert loaded is not None
        assert loaded.ticket_key == "QA-123"
        assert loaded.step_count == 8
        assert loaded.content_hash == "abc123def456"

    def test_load_nonexistent_returns_none(self, store):
        result = store.load("NONEXISTENT")
        assert result is None

    def test_manifest_integrity_detects_missing_file(self, store, tmp_baseline_dir):
        store.ensure_dir()
        store.add_to_manifest("QA-777")  # No baseline file written
        missing = store.validate_manifest_integrity()
        assert "QA-777" in missing

    def test_manifest_integrity_passes_when_files_present(self, store, tmp_baseline_dir):
        _seed_baseline(store, "QA-888", step_count=5)
        missing = store.validate_manifest_integrity()
        assert "QA-888" not in missing

    def test_is_tracked_returns_true_for_manifest_entry(self, store, tmp_baseline_dir):
        store.ensure_dir()
        store.add_to_manifest("QA-555")
        assert store.is_tracked("QA-555") is True

    def test_is_tracked_returns_false_for_unknown(self, store):
        assert store.is_tracked("QA-UNKNOWN-XYZ") is False
