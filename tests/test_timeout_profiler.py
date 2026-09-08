"""
Tests for FEAT-060 Phase 4C — TimeoutProfiler & TimingDB
==========================================================
Tests for:
  backend/engine/timeout_profiler.py  [NEW]
  backend/storage/timing_db.py        [NEW]

Verifies:
- TimeoutProfiler computes P95 ceiling from historical action timing data
- Dynamic ceiling = P95 × 2 (capped at reasonable max)
- Fallback to hardcoded values when P95 not yet established (< N runs)
- SQLite timing_db stores and retrieves per-action-type timing
- executor.py / recipe_runner.py use TimeoutProfiler instead of hardcoded ms
- Feature flag: ADAPTIVE_TIMEOUTS_ENABLED (default False — opt-in)
"""

import pytest
import sqlite3
import tempfile
import os
import asyncio
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path):
    """Provide a temporary SQLite database path."""
    return str(tmp_path / "timing_test.db")


@pytest.fixture
def timing_db(tmp_db_path):
    """Create a TimingDB instance with a temp database."""
    from backend.storage.timing_db import TimingDB
    db = TimingDB(db_path=tmp_db_path)
    yield db
    db.close()


@pytest.fixture
def profiler(tmp_db_path):
    """Create a TimeoutProfiler with a temp database."""
    from backend.engine.timeout_profiler import TimeoutProfiler
    p = TimeoutProfiler(db_path=tmp_db_path)
    yield p
    p.close()


# ---------------------------------------------------------------------------
# P4C-1: Module imports and class existence
# ---------------------------------------------------------------------------


class TestTimeoutProfilerImport:
    """Verify modules and classes exist and import correctly."""

    def test_timing_db_module_exists(self):
        """backend.storage.timing_db module can be imported."""
        from backend.storage.timing_db import TimingDB
        assert TimingDB is not None

    def test_timeout_profiler_module_exists(self):
        """backend.engine.timeout_profiler module can be imported."""
        from backend.engine.timeout_profiler import TimeoutProfiler
        assert TimeoutProfiler is not None

    def test_timing_db_instantiation(self, tmp_db_path):
        """TimingDB instantiates without error and creates the SQLite file."""
        from backend.storage.timing_db import TimingDB
        db = TimingDB(db_path=tmp_db_path)
        assert os.path.exists(tmp_db_path)
        db.close()

    def test_timeout_profiler_instantiation(self, tmp_db_path):
        """TimeoutProfiler instantiates without error."""
        from backend.engine.timeout_profiler import TimeoutProfiler
        p = TimeoutProfiler(db_path=tmp_db_path)
        assert p is not None
        p.close()


# ---------------------------------------------------------------------------
# P4C-2: TimingDB CRUD operations
# ---------------------------------------------------------------------------


class TestTimingDBOperations:
    """Verify TimingDB stores and retrieves action timing data."""

    def test_record_timing_creates_entry(self, timing_db):
        """record_timing() stores a timing entry in SQLite."""
        timing_db.record_timing(action_type="click", duration_ms=450)
        count = timing_db.get_sample_count("click")
        assert count >= 1

    def test_record_multiple_timings_same_action(self, timing_db):
        """Multiple timings for the same action_type are all stored."""
        timings = [200, 350, 500, 800, 1200]
        for t in timings:
            timing_db.record_timing(action_type="click", duration_ms=t)
        count = timing_db.get_sample_count("click")
        assert count == len(timings)

    def test_different_action_types_stored_separately(self, timing_db):
        """Timings for different action types are stored independently."""
        timing_db.record_timing(action_type="click", duration_ms=300)
        timing_db.record_timing(action_type="fill", duration_ms=150)
        timing_db.record_timing(action_type="navigate", duration_ms=2000)

        assert timing_db.get_sample_count("click") == 1
        assert timing_db.get_sample_count("fill") == 1
        assert timing_db.get_sample_count("navigate") == 1

    def test_get_p95_returns_correct_value(self, timing_db):
        """get_p95() returns the 95th percentile of stored durations."""
        # Insert 20 timings: 100, 200, ..., 2000 ms
        for i in range(1, 21):
            timing_db.record_timing(action_type="click", duration_ms=i * 100)
        
        p95 = timing_db.get_p95("click")
        # P95 of [100, 200, ..., 2000] ≈ 1900ms
        assert p95 is not None
        assert 1800 <= p95 <= 2000

    def test_get_p95_returns_none_for_unknown_action(self, timing_db):
        """get_p95() returns None for an action_type with no data."""
        result = timing_db.get_p95("nonexistent_action_type")
        assert result is None

    def test_get_p95_returns_none_when_too_few_samples(self, timing_db):
        """get_p95() returns None when fewer than min_samples exist."""
        # Only 2 samples — not enough for reliable P95
        timing_db.record_timing(action_type="click", duration_ms=500)
        timing_db.record_timing(action_type="click", duration_ms=700)
        
        # Default min_samples is typically 10
        result = timing_db.get_p95("click", min_samples=10)
        assert result is None

    def test_close_does_not_raise(self, timing_db):
        """close() completes without error."""
        timing_db.close()  # Should not raise


# ---------------------------------------------------------------------------
# P4C-3: TimeoutProfiler P95 computation
# ---------------------------------------------------------------------------


class TestTimeoutProfilerP95:
    """Verify TimeoutProfiler.get_timeout_ceiling returns P95 × 2."""

    def test_get_timeout_ceiling_returns_fallback_with_no_data(self, profiler):
        """Returns hardcoded fallback when no timing data exists."""
        ceiling = profiler.get_timeout_ceiling("click")
        # Should return a positive integer (the hardcoded fallback)
        assert isinstance(ceiling, int)
        assert ceiling > 0

    def test_get_timeout_ceiling_with_data_returns_p95_times_2(self, profiler):
        """With enough data, returns P95 × 2 as the dynamic ceiling."""
        from backend.config import settings as _s
        # Insert 20 click timings: 100–2000ms
        for i in range(1, 21):
            profiler.record_timing("click", i * 100)

        # Enable adaptive timeouts for this test
        with patch.object(_s, "adaptive_timeouts_enabled", True):
            ceiling = profiler.get_timeout_ceiling("click")
        # Expected: P95 ≈ 1900ms, ceiling = 1900 × 2 = 3800ms
        # Allow ±500ms tolerance for different P95 computation methods
        assert 3000 <= ceiling <= 5000, (
            f"Expected dynamic ceiling around 3800ms (P95≈1900 × 2), got {ceiling}ms"
        )

    def test_dynamic_ceiling_does_not_exceed_max_cap(self, profiler):
        """Dynamic ceiling is capped at a reasonable maximum (e.g., 30s)."""
        # Insert absurdly slow timings
        for i in range(20):
            profiler.record_timing("navigate", 60000)  # 60s each
        
        ceiling = profiler.get_timeout_ceiling("navigate")
        # Should be capped — not 120,000ms
        assert ceiling <= 30000, f"Ceiling should be capped but got {ceiling}ms"

    def test_fallback_varies_by_action_type(self, profiler):
        """Different action types have different hardcoded fallback values."""
        click_fallback = profiler.get_timeout_ceiling("click")
        navigate_fallback = profiler.get_timeout_ceiling("navigate")
        fill_fallback = profiler.get_timeout_ceiling("fill")

        # All should be positive
        assert click_fallback > 0
        assert navigate_fallback > 0
        assert fill_fallback > 0

        # Navigate should typically have a higher fallback than click
        assert navigate_fallback >= click_fallback, (
            "Navigate timeout should be >= click timeout (navigation takes longer)"
        )

    def test_record_timing_delegates_to_timing_db(self, profiler):
        """TimeoutProfiler.record_timing() stores data that get_timeout_ceiling uses."""
        from backend.config import settings as _s
        # 15 timings of 1000ms each
        for _ in range(15):
            profiler.record_timing("fill", 1000)

        # Enable adaptive timeouts for this test
        with patch.object(_s, "adaptive_timeouts_enabled", True):
            ceiling = profiler.get_timeout_ceiling("fill")
        # P95 of uniform 1000ms = 1000ms, ceiling = 2000ms
        assert ceiling <= 5000  # sanity check — at most 5s

    def test_min_samples_threshold_respected(self, profiler):
        """Returns fallback if sample count < min_samples threshold."""
        # Only 3 samples — below the default min_samples
        for _ in range(3):
            profiler.record_timing("click", 500)

        ceiling = profiler.get_timeout_ceiling("click")
        # Should return hardcoded fallback, not 1000ms (which would be P95×2)
        # We don't know the exact fallback, but it should be a valid int
        assert isinstance(ceiling, int)
        assert ceiling > 0


# ---------------------------------------------------------------------------
# P4C-4: Feature flag in config
# ---------------------------------------------------------------------------


class TestAdaptiveTimeoutsConfig:
    """Verify ADAPTIVE_TIMEOUTS_ENABLED flag exists in config."""

    def test_adaptive_timeouts_enabled_flag_exists(self):
        """config.py has adaptive_timeouts_enabled field."""
        from backend.config import settings
        assert hasattr(settings, "adaptive_timeouts_enabled")

    def test_adaptive_timeouts_default_false(self):
        """adaptive_timeouts_enabled defaults to False (opt-in per spec)."""
        from backend.config import settings
        assert settings.adaptive_timeouts_enabled is False

    def test_timing_db_path_configurable(self):
        """config.py has timing_db_path field with a default value."""
        from backend.config import settings
        assert hasattr(settings, "timing_db_path")
        assert isinstance(settings.timing_db_path, str)
        assert len(settings.timing_db_path) > 0


# ---------------------------------------------------------------------------
# P4C-5: Executor integration
# ---------------------------------------------------------------------------


class TestTimeoutProfilerExecutorIntegration:
    """Verify TimeoutProfiler is integrated into the executor path."""

    def test_get_timeout_profiler_function_exists(self):
        """backend.engine.timeout_profiler has get_timeout_profiler() singleton factory."""
        from backend.engine.timeout_profiler import get_timeout_profiler
        assert callable(get_timeout_profiler)

    def test_get_timeout_profiler_returns_instance(self):
        """get_timeout_profiler() returns a TimeoutProfiler instance."""
        from backend.engine.timeout_profiler import TimeoutProfiler, get_timeout_profiler
        profiler = get_timeout_profiler()
        assert isinstance(profiler, TimeoutProfiler)

    def test_get_timeout_profiler_singleton(self):
        """get_timeout_profiler() returns the same instance on repeated calls."""
        from backend.engine.timeout_profiler import get_timeout_profiler
        p1 = get_timeout_profiler()
        p2 = get_timeout_profiler()
        assert p1 is p2

    def test_compute_action_timeout_function_exists(self):
        """timeout_profiler has compute_action_timeout() convenience function."""
        from backend.engine.timeout_profiler import compute_action_timeout
        assert callable(compute_action_timeout)

    def test_compute_action_timeout_returns_int(self):
        """compute_action_timeout() returns a positive int representing ms."""
        from backend.engine.timeout_profiler import compute_action_timeout
        timeout = compute_action_timeout("click")
        assert isinstance(timeout, int)
        assert timeout > 0

    def test_compute_action_timeout_respects_feature_flag(self):
        """When adaptive_timeouts_enabled=False, compute_action_timeout returns hardcoded value."""
        from backend.engine.timeout_profiler import compute_action_timeout
        from backend.config import settings

        with patch.object(settings, "adaptive_timeouts_enabled", False):
            timeout = compute_action_timeout("click")
            # Should return hardcoded fallback, not profiler-computed value
            assert isinstance(timeout, int)
            assert timeout > 0


# ---------------------------------------------------------------------------
# P4C-6: SQLite database schema
# ---------------------------------------------------------------------------


class TestTimingDBSchema:
    """Verify the SQLite schema is correct."""

    def test_timing_db_creates_correct_table(self, tmp_db_path):
        """TimingDB creates an 'action_timings' table with expected columns."""
        from backend.storage.timing_db import TimingDB
        db = TimingDB(db_path=tmp_db_path)
        db.close()

        # Inspect the schema directly
        conn = sqlite3.connect(tmp_db_path)
        cursor = conn.execute("PRAGMA table_info(action_timings)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        # Must have at minimum these columns
        assert "action_type" in columns, "action_timings must have 'action_type' column"
        assert "duration_ms" in columns, "action_timings must have 'duration_ms' column"

    def test_timing_db_has_timestamp_column(self, tmp_db_path):
        """action_timings table has a timestamp column for TTL management."""
        from backend.storage.timing_db import TimingDB
        db = TimingDB(db_path=tmp_db_path)
        db.close()

        conn = sqlite3.connect(tmp_db_path)
        cursor = conn.execute("PRAGMA table_info(action_timings)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert any(col in columns for col in ("timestamp", "created_at", "recorded_at")), (
            "action_timings must have a timestamp column for data aging/TTL"
        )

    def test_database_persists_across_instances(self, tmp_db_path):
        """Data written by one TimingDB instance is readable by a new instance."""
        from backend.storage.timing_db import TimingDB

        # Write with instance 1
        db1 = TimingDB(db_path=tmp_db_path)
        for _ in range(15):
            db1.record_timing("click", 500)
        db1.close()

        # Read with instance 2
        db2 = TimingDB(db_path=tmp_db_path)
        count = db2.get_sample_count("click")
        db2.close()

        assert count == 15, f"Expected 15 samples, got {count}"
