"""
vQA — AI Review Run Store
=========================
Module: backend/storage/ai_review_runs.py

SQLite-backed persistence for AI Review history. One row per review run
(reuse the dashboard review_id, e.g. ar-a1b2c3d4). Separate file from
Playwright suite runs and from vcAPI login.

Default path: memory/ai_review_runs.db
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.engine.ai_review_runner import summarize_review_rows

logger = logging.getLogger(__name__)

_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _VQAROOT / "memory" / "ai_review_runs.db"
_MAX_LOG_CHARS = 1_000_000


def _utc_now() -> str:
    """
    Return a timezone-aware UTC timestamp for storage.

    @returns ISO-8601 UTC string
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _trim_log(log_text: str) -> str:
    """
    Keep the tail of a review log so one run cannot grow the DB without bound.

    @param log_text: Full captured stdout/stderr
    @returns Trimmed log
    """
    if len(log_text) <= _MAX_LOG_CHARS:
        return log_text
    return log_text[-_MAX_LOG_CHARS:]


def _list_item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """
    Map a SQLite row to the history list payload (no log or checklist rows).

    @param row: Query row
    @returns List-item dict
    """
    return {
        "review_id": row["review_id"],
        "status": row["status"],
        "app": row["app"] if "app" in row.keys() else "platform",
        "branch": row["branch"],
        "base": row["base"],
        "commits": row["commits"],
        "pass_count": int(row["pass_count"] or 0),
        "fail_count": int(row["fail_count"] or 0),
        "skip_count": int(row["skip_count"] or 0),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


class AiReviewRunStore:
    """
    SQLite-backed store for AI Review history. Thread-safe writes.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("AiReviewRunStore: initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create the ai_review_runs table if it does not exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_review_runs (
                    review_id    TEXT PRIMARY KEY,
                    status       TEXT NOT NULL DEFAULT 'running',
                    branch       TEXT NOT NULL DEFAULT '',
                    base         TEXT NOT NULL DEFAULT '',
                    commits      TEXT NOT NULL DEFAULT '',
                    app          TEXT NOT NULL DEFAULT 'platform',
                    pass_count   INTEGER NOT NULL DEFAULT 0,
                    fail_count   INTEGER NOT NULL DEFAULT 0,
                    skip_count   INTEGER NOT NULL DEFAULT 0,
                    started_at   TEXT NOT NULL DEFAULT '',
                    finished_at  TEXT,
                    rows_json    TEXT NOT NULL DEFAULT '[]',
                    log_text     TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_review_started
                ON ai_review_runs(started_at)
                """
            )
            try:
                conn.execute(
                    "ALTER TABLE ai_review_runs ADD COLUMN app TEXT NOT NULL DEFAULT 'platform'"
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def create_run(
        self,
        review_id: str,
        branch: str,
        base: str,
        commits: str = "",
        app: str = "platform",
    ) -> None:
        """
        Insert a running review row when a run starts.

        @param review_id: Dashboard run id (ar-xxxxxxxx)
        @param branch: --branch value
        @param base: --base value
        @param commits: Optional --commits value
        @param app: platform or vcapi
        @returns None
        """
        started_at = _utc_now()
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO ai_review_runs (
                        review_id, status, branch, base, commits, app, started_at
                    ) VALUES (?, 'running', ?, ?, ?, ?, ?)
                    """,
                    (review_id, branch, base, commits, app, started_at),
                )
                conn.commit()

    def finish_run(
        self,
        review_id: str,
        status: str,
        rows: list[dict[str, str]],
        log_text: str,
    ) -> None:
        """
        Persist checklist rows, log, counts, and terminal status for a run.

        @param review_id: Dashboard run id
        @param status: completed, failed, or stopped
        @param rows: Parsed checklist rows
        @param log_text: Captured stdout/stderr
        @returns None
        """
        pass_count, fail_count, skip_count = summarize_review_rows(rows)
        finished_at = _utc_now()
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.execute(
                    """
                    UPDATE ai_review_runs
                    SET status = ?,
                        pass_count = ?,
                        fail_count = ?,
                        skip_count = ?,
                        finished_at = ?,
                        rows_json = ?,
                        log_text = ?
                    WHERE review_id = ?
                    """,
                    (
                        status,
                        pass_count,
                        fail_count,
                        skip_count,
                        finished_at,
                        json.dumps(rows),
                        _trim_log(log_text),
                        review_id,
                    ),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    logger.warning(
                        "AiReviewRunStore: finish_run found no row for %s", review_id
                    )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Return recent reviews newest first, without logs or full tables.

        @param limit: Max rows to return
        @returns List of history summary dicts
        """
        capped = max(1, min(int(limit), 200))
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT review_id, status, app, branch, base, commits,
                       pass_count, fail_count, skip_count, started_at, finished_at
                FROM ai_review_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (capped,),
            )
            return [_list_item_from_row(row) for row in cursor.fetchall()]

    def get_run(self, review_id: str) -> Optional[dict[str, Any]]:
        """
        Return one review including checklist rows and log.

        @param review_id: Dashboard run id
        @returns Detail dict, or None when missing
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT review_id, status, app, branch, base, commits,
                       pass_count, fail_count, skip_count, started_at, finished_at,
                       rows_json, log_text
                FROM ai_review_runs
                WHERE review_id = ?
                """,
                (review_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            item = _list_item_from_row(row)
            try:
                parsed_rows = json.loads(row["rows_json"] or "[]")
            except json.JSONDecodeError:
                logger.error("AiReviewRunStore: bad rows_json for %s", review_id)
                parsed_rows = []
            if not isinstance(parsed_rows, list):
                parsed_rows = []
            item["rows"] = parsed_rows
            item["log_text"] = row["log_text"] or ""
            return item

    def _clear_for_testing(self) -> None:
        """Clear all records from the store for testing purposes."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM ai_review_runs")
                conn.commit()


ai_review_run_store = AiReviewRunStore()
