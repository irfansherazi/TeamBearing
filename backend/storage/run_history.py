"""
vQA — Run History Store (Phase 5C)
=====================================
Module: backend/storage/run_history.py

SQLite-backed persistence for run history and trend analytics.

Stores one row per completed test run with pass/fail status, duration,
cost, and AC step counts.  Provides aggregated analytics queries for
dashboards and CI/CD trend reporting.

Usage
-----
    from backend.storage.run_history import run_history

    # Record a completed run
    run_history.record_run(
        run_id="run-abc",
        ticket_id="VC2-8967",
        role="account_executive",
        status="passed",
        duration_ms=45000,
        ac_total=5,
        ac_passed=5,
        cost_usd=0.032,
    )

    # Query history
    runs = run_history.get_runs(limit=20)
    analytics = run_history.get_analytics(days=30)

See Also
--------
  - ``backend/engine/reporter.py``  — calls record_run() after completion
  - ``backend/api/routes.py``       — /runs/history and /runs/analytics endpoints
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _VQAROOT / "memory" / "run_history.db"


class RunHistory:
    """
    SQLite-backed run history store.

    Thread-safe — all writes are serialized through a lock.
    Reads use WAL mode for concurrent access.

    Attributes
    ----------
    db_path : Path
        Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("RunHistory: initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create the runs table if it doesn't exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL UNIQUE,
                    ticket_id   TEXT NOT NULL DEFAULT '',
                    role        TEXT NOT NULL DEFAULT '',
                    status      TEXT NOT NULL DEFAULT 'unknown',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    ac_total    INTEGER NOT NULL DEFAULT 0,
                    ac_passed   INTEGER NOT NULL DEFAULT 0,
                    cost_usd    REAL NOT NULL DEFAULT 0.0,
                    report_url  TEXT NOT NULL DEFAULT '',
                    video_url   TEXT NOT NULL DEFAULT '',
                    profile     TEXT NOT NULL DEFAULT 'vsuite',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_ticket
                ON runs(ticket_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_created
                ON runs(created_at)
            """)
            conn.commit()

    def record_run(
        self,
        run_id: str,
        ticket_id: str = "",
        role: str = "",
        status: str = "unknown",
        duration_ms: int = 0,
        ac_total: int = 0,
        ac_passed: int = 0,
        cost_usd: float = 0.0,
        report_url: str = "",
        video_url: str = "",
        profile: str = "vsuite",
    ) -> None:
        """
        Record a completed run.

        Parameters
        ----------
        run_id : str
            Unique run identifier.
        ticket_id : str
            Source ticket ID (Jira key, GitHub issue, etc.).
        role : str
            User role that was tested.
        status : str
            Run outcome: ``"passed"``, ``"failed"``, ``"error"``, ``"cancelled"``.
        duration_ms : int
            Total run duration in milliseconds.
        ac_total : int
            Total number of AC steps.
        ac_passed : int
            Number of AC steps that passed.
        cost_usd : float
            Estimated LLM cost.
        report_url : str
            S3 URL of the HTML report.
        video_url : str
            S3 URL of the session recording.
        profile : str
            AppProfile name used for the run.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                with sqlite3.connect(str(self._db_path)) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO runs
                        (run_id, ticket_id, role, status, duration_ms,
                         ac_total, ac_passed, cost_usd, report_url,
                         video_url, profile, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            ticket_id,
                            role,
                            status,
                            duration_ms,
                            ac_total,
                            ac_passed,
                            cost_usd,
                            report_url,
                            video_url,
                            profile,
                            now,
                        ),
                    )
                    conn.commit()
                logger.info(
                    "[%s] RunHistory: recorded %s — %s (%d/%d AC, $%.4f)",
                    run_id,
                    ticket_id,
                    status,
                    ac_passed,
                    ac_total,
                    cost_usd,
                )
            except Exception as e:
                logger.warning("[%s] RunHistory: failed to record: %s", run_id, e)

    def get_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        ticket_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get paginated run history.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return.
        offset : int
            Number of runs to skip (for pagination).
        ticket_id : str, optional
            Filter by ticket ID.
        status : str, optional
            Filter by status.

        Returns
        -------
        list[dict]
            List of run records, newest first.
        """
        query = "SELECT * FROM runs WHERE 1=1"
        params: list[Any] = []

        if ticket_id:
            query += " AND ticket_id = ?"
            params.append(ticket_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning("RunHistory: get_runs failed: %s", e)
            return []

    def get_analytics(self, days: int = 30) -> dict[str, Any]:
        """
        Get aggregated analytics for the last N days.

        Parameters
        ----------
        days : int
            Number of days to look back.

        Returns
        -------
        dict
            Analytics summary with pass rate, cost, duration, etc.
        """
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                # Total runs
                total = conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE created_at >= datetime('now', ?)",
                    (f"-{days} days",),
                ).fetchone()[0]

                if total == 0:
                    return {
                        "period_days": days,
                        "total_runs": 0,
                        "passed": 0,
                        "failed": 0,
                        "pass_rate": 0.0,
                        "total_cost_usd": 0.0,
                        "avg_cost_usd": 0.0,
                        "avg_duration_ms": 0,
                        "total_ac_steps": 0,
                        "total_ac_passed": 0,
                        "top_tickets": [],
                    }

                # Pass / fail counts
                passed = conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE status = 'passed' AND created_at >= datetime('now', ?)",
                    (f"-{days} days",),
                ).fetchone()[0]

                failed = total - passed

                # Cost and duration aggregates
                agg = conn.execute(
                    "SELECT SUM(cost_usd), AVG(cost_usd), AVG(duration_ms), "
                    "SUM(ac_total), SUM(ac_passed) "
                    "FROM runs WHERE created_at >= datetime('now', ?)",
                    (f"-{days} days",),
                ).fetchone()

                # Top tickets by run count
                top_tickets = conn.execute(
                    "SELECT ticket_id, COUNT(*) as count, "
                    "SUM(CASE WHEN status='passed' THEN 1 ELSE 0 END) as passes "
                    "FROM runs WHERE created_at >= datetime('now', ?) "
                    "AND ticket_id != '' "
                    "GROUP BY ticket_id ORDER BY count DESC LIMIT 10",
                    (f"-{days} days",),
                ).fetchall()

                return {
                    "period_days": days,
                    "total_runs": total,
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": round(passed / total * 100, 1) if total > 0 else 0.0,
                    "total_cost_usd": round(agg[0] or 0.0, 4),
                    "avg_cost_usd": round(agg[1] or 0.0, 6),
                    "avg_duration_ms": int(agg[2] or 0),
                    "total_ac_steps": int(agg[3] or 0),
                    "total_ac_passed": int(agg[4] or 0),
                    "top_tickets": [{"ticket_id": t[0], "runs": t[1], "passes": t[2]} for t in top_tickets],
                }
        except Exception as e:
            logger.warning("RunHistory: get_analytics failed: %s", e)
            return {"error": str(e)}

    def get_previous_run(
        self,
        ticket_id: str,
        before_run_id: str,
    ) -> dict[str, Any] | None:
        """
        Get the most recent run for a ticket BEFORE a given run.

        Used for regression detection — comparing current vs previous.

        Parameters
        ----------
        ticket_id : str
            The ticket to search for.
        before_run_id : str
            The run ID to look before (exclusive).

        Returns
        -------
        dict or None
            The previous run record, or None if no prior run exists.
        """
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                # Get the created_at of the reference run
                ref_row = conn.execute(
                    "SELECT created_at FROM runs WHERE run_id = ?",
                    (before_run_id,),
                ).fetchone()
                if not ref_row:
                    return None

                ref_time = ref_row["created_at"]
                row = conn.execute(
                    "SELECT * FROM runs WHERE ticket_id = ? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
                    (ticket_id, ref_time),
                ).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.warning("RunHistory: get_previous_run failed: %s", e)
            return None

    def detect_regression(
        self,
        ticket_id: str,
        current_run_id: str,
        current_status: str,
    ) -> bool:
        """
        Detect if the current run is a regression.

        A regression occurs when the previous run of the same ticket
        passed but the current one failed.

        Parameters
        ----------
        ticket_id : str
            The ticket being tested.
        current_run_id : str
            The current run ID.
        current_status : str
            The current run status ("passed" or "failed").

        Returns
        -------
        bool
            True if this is a regression (was passing, now failing).
        """
        if current_status == "passed":
            return False

        prev = self.get_previous_run(ticket_id, current_run_id)
        if prev and prev.get("status") == "passed":
            logger.warning(
                "[%s] REGRESSION DETECTED: %s was passing (run %s), now failing",
                current_run_id,
                ticket_id,
                prev["run_id"],
            )
            return True
        return False


# Module-level singleton
run_history = RunHistory()
