"""
vQA — Action Timing Database
===============================
Module: backend/storage/timing_db.py

FEAT-060 Phase 4C (TASK-080-P4C)

Persistent SQLite store for per-action-type execution timing data.
Used by ``TimeoutProfiler`` to compute dynamic P95-based timeout ceilings.

Schema
------
Table: ``action_timings``
  - id         INTEGER PRIMARY KEY AUTOINCREMENT
  - action_type TEXT NOT NULL         — e.g. "click", "fill", "navigate"
  - duration_ms INTEGER NOT NULL      — observed action duration in milliseconds
  - recorded_at REAL NOT NULL         — Unix timestamp (float) of recording

Design decisions
----------------
- SQLite is co-located in the ``memory/`` directory (no schema migration needed).
- All writes use ``INSERT INTO`` with WAL mode for concurrent read safety.
- P95 is computed via SQL window function / ORDER BY approach.
- Data is never automatically pruned (can be done via TTL in a future pass).

Thread safety
-------------
Each ``TimingDB`` instance creates its own connection. Multiple instances
to the same file are safe under SQLite's WAL journal mode (concurrent reads,
serialized writes).
"""

import logging
import os
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Default database path — can be overridden in config or tests
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "memory",
    "timing.db",
)

# DDL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS action_timings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type  TEXT    NOT NULL,
    duration_ms  INTEGER NOT NULL,
    recorded_at  REAL    NOT NULL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_action_timings_type
    ON action_timings (action_type, recorded_at DESC);
"""


class TimingDB:
    """
    SQLite-backed store for action timing data.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.
        Defaults to ``memory/timing.db`` in the project root.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        # Ensure the directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_CREATE_TABLE_SQL + _CREATE_INDEX_SQL)
        self._conn.commit()
        logger.debug("TimingDB: opened at %s", db_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_timing(self, action_type: str, duration_ms: int) -> None:
        """
        Record an observed action duration.

        Parameters
        ----------
        action_type : str
            Action category (e.g. "click", "fill", "navigate").
        duration_ms : int
            Elapsed time in milliseconds for this action.
        """
        now = time.time()
        try:
            self._conn.execute(
                "INSERT INTO action_timings (action_type, duration_ms, recorded_at) VALUES (?, ?, ?)",
                (action_type, int(duration_ms), now),
            )
            self._conn.commit()
            logger.debug("TimingDB: recorded %s=%dms", action_type, duration_ms)
        except sqlite3.Error as exc:
            logger.warning("TimingDB: failed to record timing: %s", exc)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_sample_count(self, action_type: str) -> int:
        """
        Return the number of timing samples stored for ``action_type``.

        Parameters
        ----------
        action_type : str
            The action category to count.

        Returns
        -------
        int
            Number of stored samples (0 if none).
        """
        try:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM action_timings WHERE action_type = ?",
                (action_type,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error as exc:
            logger.warning("TimingDB: get_sample_count failed: %s", exc)
            return 0

    def get_p95(self, action_type: str, min_samples: int = 10) -> Optional[int]:
        """
        Compute the 95th-percentile duration for ``action_type``.

        Returns ``None`` if fewer than ``min_samples`` samples exist —
        indicating the P95 estimate is not yet reliable enough to use
        as a dynamic timeout ceiling.

        Parameters
        ----------
        action_type : str
            The action category to analyse.
        min_samples : int
            Minimum number of samples required to return a P95 estimate.
            Default: 10.

        Returns
        -------
        int | None
            P95 duration in milliseconds, or ``None`` if insufficient data.
        """
        count = self.get_sample_count(action_type)
        if count < min_samples:
            logger.debug(
                "TimingDB: get_p95 '%s' — insufficient data (%d/%d samples)",
                action_type,
                count,
                min_samples,
            )
            return None

        try:
            # Sort all durations for this action_type, take the row at the 95th percentile
            cursor = self._conn.execute(
                "SELECT duration_ms FROM action_timings WHERE action_type = ? ORDER BY duration_ms ASC",
                (action_type,),
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            durations = [row[0] for row in rows]
            idx = max(0, int(len(durations) * 0.95) - 1)
            p95_value = int(durations[idx])
            logger.debug("TimingDB: P95 for '%s' = %dms (%d samples)", action_type, p95_value, count)
            return p95_value

        except sqlite3.Error as exc:
            logger.warning("TimingDB: get_p95 failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
            logger.debug("TimingDB: closed")
        except sqlite3.Error:
            pass

    def __del__(self) -> None:
        """Best-effort close on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
