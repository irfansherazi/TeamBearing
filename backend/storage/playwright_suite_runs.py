"""
vQA — Playwright Suite Run Store
====================================
Module: backend/storage/playwright_suite_runs.py

SQLite-backed persistence for Playwright parallel suite runs.
Allows suite run state to be shared across multiple ECS replicas
behind the Application Load Balancer.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _VQAROOT / "memory" / "playwright_suite_runs.db"


class PlaywrightSuiteRunStore:
    """
    SQLite-backed store for Playwright suite runs.

    Thread-safe — all writes are serialized through a lock.
    Reads use WAL mode for concurrent access.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("PlaywrightSuiteRunStore: initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create the suite_runs table if it doesn't exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playwright_suite_runs (
                    suite_run_id  TEXT PRIMARY KEY,
                    status        TEXT NOT NULL DEFAULT 'running',
                    data          TEXT NOT NULL DEFAULT '{}',
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def create_run(self, suite_run_id: str, data: Dict[str, Any]) -> None:
        """Create a new suite run entry in the store."""
        status = data.get("status", "running")
        serialized_data = json.dumps(data)
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "INSERT INTO playwright_suite_runs (suite_run_id, status, data, updated_at) VALUES (?, ?, ?, datetime('now'))",
                    (suite_run_id, status, serialized_data)
                )
                conn.commit()

    def update_run(self, suite_run_id: str, data: Dict[str, Any]) -> None:
        """Update an existing suite run's data and status."""
        status = data.get("status", "running")
        serialized_data = json.dumps(data)
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE playwright_suite_runs SET status = ?, data = ?, updated_at = datetime('now') WHERE suite_run_id = ?",
                    (status, serialized_data, suite_run_id)
                )
                conn.commit()

    def get_run(self, suite_run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and parse a suite run's data from the store."""
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data FROM playwright_suite_runs WHERE suite_run_id = ?",
                (suite_run_id,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except Exception as e:
                    logger.error("Failed to parse JSON for suite run %s: %s", suite_run_id, e)
                    return None
            return None

    def get_active_run_id(self) -> Optional[str]:
        """Check if any suite run is currently in status 'running' and return its ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT suite_run_id FROM playwright_suite_runs WHERE status = 'running' LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def list_runs(self) -> List[Dict[str, Any]]:
        """List all suite runs from the store."""
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data FROM playwright_suite_runs ORDER BY updated_at DESC"
            )
            rows = cursor.fetchall()
            runs = []
            for row in rows:
                try:
                    runs.append(json.loads(row[0]))
                except Exception:
                    pass
            return runs

    def delete_run(self, suite_run_id: str) -> None:
        """Delete a suite run from the store."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "DELETE FROM playwright_suite_runs WHERE suite_run_id = ?",
                    (suite_run_id,)
                )
                conn.commit()

    def update_test_status(
        self,
        suite_run_id: str,
        test_id: str,
        status: str,
        duration_ms: Optional[float] = None,
        error_snippet: Optional[str] = None,
    ) -> None:
        """Atomically update the status of a specific test inside a suite run's results."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data FROM playwright_suite_runs WHERE suite_run_id = ?",
                    (suite_run_id,)
                )
                row = cursor.fetchone()
                if row:
                    try:
                        data = json.loads(row[0])
                        for res in data.get("results", []):
                            if res["test_id"] == test_id:
                                res["status"] = status
                                if duration_ms is not None:
                                    res["duration_ms"] = round(duration_ms, 2)
                                if error_snippet is not None:
                                    res["error_snippet"] = error_snippet
                                break

                        serialized_data = json.dumps(data)
                        conn.execute(
                            "UPDATE playwright_suite_runs SET data = ?, updated_at = datetime('now') WHERE suite_run_id = ?",
                            (serialized_data, suite_run_id)
                        )
                        conn.commit()
                    except Exception as e:
                        logger.error("Failed to update test status in database for run %s: %s", suite_run_id, e)

    def update_suite_totals_and_status(
        self,
        suite_run_id: str,
        passed_delta: int = 0,
        failed_delta: int = 0,
        status: Optional[str] = None,
        outcome: Optional[str] = None,
        fail_reason: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Atomically update suite run counters, overall status/outcome, and fail reason."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data FROM playwright_suite_runs WHERE suite_run_id = ?",
                    (suite_run_id,)
                )
                row = cursor.fetchone()
                if row:
                    try:
                        data = json.loads(row[0])
                        if passed_delta:
                            data["passed"] = data.get("passed", 0) + passed_delta
                        if failed_delta:
                            data["failed"] = data.get("failed", 0) + failed_delta
                        if status is not None:
                            data["status"] = status
                        if outcome is not None:
                            data["outcome"] = outcome
                        if fail_reason is not None:
                            data["fail_reason"] = fail_reason
                        if completed_at is not None:
                            data["completed_at"] = completed_at

                        serialized_data = json.dumps(data)
                        db_status = status if status is not None else data.get("status", "running")

                        conn.execute(
                            "UPDATE playwright_suite_runs SET status = ?, data = ?, updated_at = datetime('now') WHERE suite_run_id = ?",
                            (db_status, serialized_data, suite_run_id)
                        )
                        conn.commit()
                    except Exception as e:
                        logger.error("Failed to update suite totals in database for run %s: %s", suite_run_id, e)

    def abort_stale_runs(self, max_age_minutes: Optional[int] = None) -> None:
        """Mark active 'running' runs as failed.

        If max_age_minutes is given, only abort runs whose updated_at is older
        than that many minutes (skips genuinely in-progress runs).
        """
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.cursor()
                if max_age_minutes is not None:
                    cursor.execute(
                        "SELECT suite_run_id, data FROM playwright_suite_runs "
                        "WHERE status = 'running' "
                        "AND updated_at <= datetime('now', ? || ' minutes')",
                        (f"-{max_age_minutes}",),
                    )
                else:
                    cursor.execute(
                        "SELECT suite_run_id, data FROM playwright_suite_runs WHERE status = 'running'"
                    )
                rows = cursor.fetchall()
                for row in rows:
                    suite_run_id, raw_data = row
                    try:
                        data = json.loads(raw_data)
                        data["status"] = "failed"
                        data["outcome"] = "FAIL"
                        data["fail_reason"] = "Suite run aborted on server restart / startup"
                        data["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        
                        # Mark any PENDING or RUNNING tests in the results list as FAIL
                        for res in data.get("results", []):
                            if res.get("status") in ("PENDING", "RUNNING"):
                                res["status"] = "FAIL"
                                res["error_snippet"] = "Suite run aborted on server restart / startup."
                                data["failed"] = data.get("failed", 0) + 1
                                
                        serialized_data = json.dumps(data)
                        conn.execute(
                            "UPDATE playwright_suite_runs SET status = 'failed', data = ?, updated_at = datetime('now') WHERE suite_run_id = ?",
                            (serialized_data, suite_run_id)
                        )
                    except Exception as e:
                        logger.error("Failed to abort stale run %s on startup: %s", suite_run_id, e)
                conn.commit()

    def _clear_for_testing(self) -> None:
        """Clear all records from the store for testing purposes."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM playwright_suite_runs")
                conn.commit()


# Singleton instance
playwright_suite_run_store = PlaywrightSuiteRunStore()
