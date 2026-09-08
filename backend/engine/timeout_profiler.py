"""
vQA — Adaptive Timeout Profiler
================================
Module: backend/engine/timeout_profiler.py

FEAT-060 Phase 4C (TASK-080-P4C)

Provides dynamic, per-action-type Playwright timeout ceilings derived from
historical P95 execution timing data stored in ``backend/storage/timing_db.py``.

Replaces hardcoded ``timeout=15000`` scatter across ``executor.py`` and
``recipe_runner.py`` with data-driven ceilings that auto-tune as vQA
collects real-world timing observations.

Algorithm
---------
1. At runtime, ``record_timing(action_type, duration_ms)`` is called after
   every successful Playwright action.
2. ``get_timeout_ceiling(action_type)`` queries the TimingDB for the P95
   of all recorded durations for that action type and returns ``P95 × 2``
   as the dynamic ceiling.
3. If fewer than ``_MIN_SAMPLES`` observations exist for the action type,
   the function falls back to the hardcoded ``_DEFAULT_TIMEOUTS`` map.

Design decisions
----------------
- P95 × 2 ensures the ceiling is 2× the 95th-percentile — generous enough
  to accommodate outliers while still far below the worst-case 30s.
- Hardcoded fallbacks are preserved so the system works correctly for
  first N runs before P95 is established.
- The module exposes a ``get_timeout_profiler()`` singleton factory and a
  ``compute_action_timeout(action_type)`` convenience function for direct
  use in executor.py and recipe_runner.py.

Feature flag: ``ADAPTIVE_TIMEOUTS_ENABLED`` (default ``False`` — opt-in
after data collection, per TASK-080 spec)

Maximum ceiling cap: 30,000ms (30s) — prevents degenerate timeouts from
a few extremely slow outlier runs.
"""

import logging
import os
from typing import Optional

from backend.storage.timing_db import TimingDB, _DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum samples before we trust the P95 estimate
_MIN_SAMPLES = 10

# Maximum dynamic ceiling (prevents degenerate P95 × 2 from slow outliers)
_MAX_CEILING_MS = 30_000

# P95 ceiling multiplier
_CEILING_MULTIPLIER = 2

# Hardcoded fallback timeouts (ms) — one per action type
# These match pre-FEAT-060 behavioral defaults scattered across the codebase.
_DEFAULT_TIMEOUTS: dict[str, int] = {
    "click": 15_000,
    "fill": 10_000,
    "navigate": 20_000,
    "select_option": 12_000,
    "check": 10_000,
    "uncheck": 10_000,
    "verify": 8_000,
    "wait": 5_000,
    "scroll": 5_000,
    "press_key": 5_000,
    "set_input_files": 10_000,
    "primeng_dropdown": 12_000,
    "recipe": 20_000,
    "done": 5_000,
    # Default for unknown action types
    "_default": 15_000,
}


# ---------------------------------------------------------------------------
# TimeoutProfiler
# ---------------------------------------------------------------------------


class TimeoutProfiler:
    """
    Adaptive Playwright timeout profiler backed by per-action P95 timing data.

    Parameters
    ----------
    db_path : str
        Path to the SQLite timing database.
        Defaults to ``memory/timing.db`` in the project root.
    min_samples : int
        Minimum number of timing observations required before P95 is used.
        Below this count, hardcoded fallbacks are returned.  Default: 10.
    """

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        min_samples: int = _MIN_SAMPLES,
    ) -> None:
        self._db = TimingDB(db_path=db_path)
        self._min_samples = min_samples

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_timing(self, action_type: str, duration_ms: int) -> None:
        """
        Record an observed Playwright action duration.

        Should be called after every successfully completed browser action.
        The data feeds the P95 computation for future timeout decisions.

        Parameters
        ----------
        action_type : str
            The action category (e.g. "click", "fill", "navigate").
        duration_ms : int
            Observed execution time in milliseconds.
        """
        try:
            self._db.record_timing(action_type=action_type, duration_ms=duration_ms)
        except Exception as exc:
            logger.debug("TimeoutProfiler: record_timing failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_timeout_ceiling(self, action_type: str) -> int:
        """
        Return the dynamic timeout ceiling for ``action_type`` in milliseconds.

        If sufficient timing data exists (≥ ``min_samples``), returns
        ``P95 × 2`` capped at ``_MAX_CEILING_MS``.

        If insufficient data exists (first N runs), returns the hardcoded
        fallback from ``_DEFAULT_TIMEOUTS``.

        Parameters
        ----------
        action_type : str
            The action category to get a timeout for.

        Returns
        -------
        int
            Timeout ceiling in milliseconds.
        """
        try:
            from backend.config import settings
            if not settings.adaptive_timeouts_enabled:
                return self._fallback(action_type)
        except Exception:
            return self._fallback(action_type)

        # Try to get P95 from the timing database
        try:
            p95 = self._db.get_p95(action_type=action_type, min_samples=self._min_samples)
        except Exception as exc:
            logger.warning("TimeoutProfiler: DB query failed — using fallback: %s", exc)
            return self._fallback(action_type)

        if p95 is None:
            # Not enough data yet — use hardcoded fallback
            return self._fallback(action_type)

        # Apply P95 × ceiling_multiplier, cap at max
        dynamic = p95 * _CEILING_MULTIPLIER
        ceiling = min(dynamic, _MAX_CEILING_MS)

        logger.debug(
            "TimeoutProfiler: %s → P95=%dms × %d = %dms (cap=%d)",
            action_type,
            p95,
            _CEILING_MULTIPLIER,
            dynamic,
            ceiling,
        )
        return ceiling

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying TimingDB connection."""
        self._db.close()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _fallback(self, action_type: str) -> int:
        """Return the hardcoded fallback timeout for ``action_type``."""
        return _DEFAULT_TIMEOUTS.get(action_type, _DEFAULT_TIMEOUTS["_default"])


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[TimeoutProfiler] = None


def get_timeout_profiler() -> TimeoutProfiler:
    """
    Return the process-level singleton TimeoutProfiler.

    Thread-safe on CPython (GIL protects single-object assignment).

    Returns
    -------
    TimeoutProfiler
        The singleton instance.
    """
    global _singleton
    if _singleton is None:
        try:
            from backend.config import settings
            db_path = settings.timing_db_path
        except Exception:
            db_path = _DEFAULT_DB_PATH
        _singleton = TimeoutProfiler(db_path=db_path)
    return _singleton


def compute_action_timeout(action_type: str) -> int:
    """
    Convenience function: return the timeout ceiling for ``action_type``.

    Uses the process-level singleton TimeoutProfiler.  Falls back to the
    hardcoded default when ``ADAPTIVE_TIMEOUTS_ENABLED`` is False.

    Parameters
    ----------
    action_type : str
        The action category (e.g. "click", "fill", "navigate").

    Returns
    -------
    int
        Timeout ceiling in milliseconds.
    """
    try:
        from backend.config import settings
        if not settings.adaptive_timeouts_enabled:
            # Feature flag disabled: return hardcoded default
            return _DEFAULT_TIMEOUTS.get(action_type, _DEFAULT_TIMEOUTS["_default"])
    except Exception:
        return _DEFAULT_TIMEOUTS.get(action_type, _DEFAULT_TIMEOUTS["_default"])

    return get_timeout_profiler().get_timeout_ceiling(action_type)
