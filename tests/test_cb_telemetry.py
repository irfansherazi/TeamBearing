"""
Tests for circuit breaker telemetry instrumentation (MVE-001).

Validates that emit_cb_telemetry:
1. Writes valid JSON to both logger and .agent-logs/telemetry/cb_events.jsonl
2. Emits correct cb_type for each CB type
3. Creates the file if not exists, appends if exists
4. Is non-blocking (fire-and-forget on disk errors)

See: backend/engine/cb_telemetry.py
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_telemetry_dir(tmp_path):
    """Provide a temp directory for telemetry output."""
    telemetry_dir = tmp_path / ".agent-logs" / "telemetry"
    return str(telemetry_dir)


class TestTelemetryEmission:
    """Tests that telemetry is emitted correctly for each CB type."""

    def test_amnesic_cb_emits_event(self, temp_telemetry_dir):
        """Amnesic CB trip → emits CIRCUIT_BREAKER_TRIPPED with cb_type='amnesic_loop'."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            emit_cb_telemetry(
                run_id="run-test",
                cb_type="amnesic_loop",
                cb_reason="3 stagnant actions detected",
                iteration_at_fire=15,
                action_at_fire="click",
                ac_step_index=2,
                wall_clock_elapsed_s=120.5,
                cost_usd_at_fire=0.45,
            )

        # Verify the file was created and contains valid JSON
        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        assert events_file.exists()

        with events_file.open() as f:
            line = f.readline().strip()
            event = json.loads(line)

        assert event["event"] == "CIRCUIT_BREAKER_TRIPPED"
        assert event["cb_type"] == "amnesic_loop"
        assert event["run_id"] == "run-test"
        assert event["iteration_at_fire"] == 15
        assert event["action_at_fire"] == "click"
        assert event["ac_step_index"] == 2
        assert event["wall_clock_elapsed_s"] == 120.5
        assert event["cost_usd_at_fire"] == 0.45
        assert "timestamp" in event

    def test_per_locator_cb_emits_event(self, temp_telemetry_dir):
        """Per-locator CB trip → emits with cb_type='per_locator'."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            emit_cb_telemetry(
                run_id="run-test",
                cb_type="per_locator",
                cb_reason="Locator 'get_by_role:button:Submit' failed 3 times",
                iteration_at_fire=25,
                action_at_fire="click",
                ac_step_index=5,
                wall_clock_elapsed_s=300.0,
                cost_usd_at_fire=1.20,
            )

        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        with events_file.open() as f:
            event = json.loads(f.readline().strip())

        assert event["cb_type"] == "per_locator"

    def test_ac_level_cap_cb_emits_event(self, temp_telemetry_dir):
        """AC-level cap CB trip → emits with cb_type='ac_level_cap'."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            emit_cb_telemetry(
                run_id="run-test",
                cb_type="ac_level_cap",
                cb_reason="20 total actions on AC step 3",
                iteration_at_fire=50,
                action_at_fire="fill",
                ac_step_index=3,
                wall_clock_elapsed_s=600.0,
                cost_usd_at_fire=1.80,
            )

        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        with events_file.open() as f:
            event = json.loads(f.readline().strip())

        assert event["cb_type"] == "ac_level_cap"


class TestTelemetryJsonValidity:
    """Tests that telemetry JSON is always valid and parseable."""

    def test_all_cb_types_produce_valid_json(self, temp_telemetry_dir):
        """Each CB type produces a valid, parseable JSON line."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        cb_types = ["amnesic_loop", "per_locator", "ac_level_cap", "global_iter", "verifier_not_yet"]

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            for cb_type in cb_types:
                emit_cb_telemetry(
                    run_id="run-test",
                    cb_type=cb_type,
                    cb_reason=f"Test reason for {cb_type}",
                    iteration_at_fire=10,
                    action_at_fire="click",
                    ac_step_index=1,
                    wall_clock_elapsed_s=100.0,
                    cost_usd_at_fire=0.50,
                )

        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        with events_file.open() as f:
            lines = f.readlines()

        assert len(lines) == 5
        for line in lines:
            event = json.loads(line.strip())
            assert event["event"] == "CIRCUIT_BREAKER_TRIPPED"
            assert event["cb_type"] in cb_types


class TestTelemetryFileManagement:
    """Tests for file creation and append behavior."""

    def test_file_created_if_not_exists(self, temp_telemetry_dir):
        """Telemetry file is created if it doesn't exist."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        assert not events_file.exists()

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            emit_cb_telemetry(
                run_id="run-test",
                cb_type="amnesic_loop",
                cb_reason="test",
                iteration_at_fire=1,
                action_at_fire="click",
                ac_step_index=0,
                wall_clock_elapsed_s=10.0,
                cost_usd_at_fire=0.10,
            )

        assert events_file.exists()

    def test_file_appended_if_exists(self, temp_telemetry_dir):
        """Telemetry file is appended to, not overwritten."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", temp_telemetry_dir):
            # First write
            emit_cb_telemetry(
                run_id="run-1",
                cb_type="amnesic_loop",
                cb_reason="first",
                iteration_at_fire=1,
                action_at_fire="click",
                ac_step_index=0,
                wall_clock_elapsed_s=10.0,
                cost_usd_at_fire=0.10,
            )
            # Second write (should append)
            emit_cb_telemetry(
                run_id="run-2",
                cb_type="per_locator",
                cb_reason="second",
                iteration_at_fire=2,
                action_at_fire="fill",
                ac_step_index=1,
                wall_clock_elapsed_s=20.0,
                cost_usd_at_fire=0.20,
            )

        events_file = Path(temp_telemetry_dir) / "cb_events.jsonl"
        with events_file.open() as f:
            lines = f.readlines()

        assert len(lines) == 2
        assert json.loads(lines[0])["run_id"] == "run-1"
        assert json.loads(lines[1])["run_id"] == "run-2"

    def test_disk_error_suppressed(self, temp_telemetry_dir):
        """Disk write errors are suppressed (fire-and-forget)."""
        from backend.engine.cb_telemetry import emit_cb_telemetry

        # Use a path that we'll make unwritable
        with patch("backend.engine.cb_telemetry._TELEMETRY_DIR", "/nonexistent/path/that/does/not/exist"):
            # Should NOT raise — errors are suppressed
            emit_cb_telemetry(
                run_id="run-test",
                cb_type="amnesic_loop",
                cb_reason="test",
                iteration_at_fire=1,
                action_at_fire="click",
                ac_step_index=0,
                wall_clock_elapsed_s=10.0,
                cost_usd_at_fire=0.10,
            )
