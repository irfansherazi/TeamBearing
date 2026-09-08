"""
backend/storage/memory_watch_runs.py
=====================================
SQLite persistence for Memory Watch history.

Default path: memory/memory_watch_runs.db
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _VQAROOT / "memory" / "memory_watch_runs.db"
_MAX_LOG_CHARS = 1_000_000


def _utc_now() -> str:
    """
    Return a timezone-aware UTC timestamp for storage.

    @returns ISO-8601 UTC string
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _trim_log(log_text: str) -> str:
    """
    Keep the tail of a log so one run cannot grow the DB without bound.

    @param log_text: Full captured stdout/stderr
    @returns Trimmed log
    """
    if len(log_text) <= _MAX_LOG_CHARS:
        return log_text
    return log_text[-_MAX_LOG_CHARS:]


def _list_item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """
    Map a SQLite row to the history list payload (no log or samples).

    @param row: Query row
    @returns List-item dict
    """
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "flow": row["flow"],
        "env": row["env"],
        "cycles": int(row["cycles"] or 0),
        "verdict_pass": bool(row["verdict_pass"]) if row["verdict_pass"] is not None else None,
        "growth_mb": row["growth_mb"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


class MemoryWatchRunStore:
    """SQLite-backed store for Memory Watch history. Thread-safe writes."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("MemoryWatchRunStore: initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create the memory_watch_runs table if it does not exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_watch_runs (
                    run_id        TEXT PRIMARY KEY,
                    status        TEXT NOT NULL DEFAULT 'running',
                    flow          TEXT NOT NULL DEFAULT '',
                    env           TEXT NOT NULL DEFAULT 'qa',
                    cycles        INTEGER NOT NULL DEFAULT 5,
                    verdict_pass  INTEGER,
                    growth_mb     REAL,
                    started_at    TEXT NOT NULL DEFAULT '',
                    finished_at   TEXT,
                    samples_json  TEXT NOT NULL DEFAULT '[]',
                    rows_json     TEXT NOT NULL DEFAULT '[]',
                    log_text      TEXT NOT NULL DEFAULT '',
                    report_dir    TEXT NOT NULL DEFAULT '',
                    video_file    TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_watch_started
                ON memory_watch_runs(started_at)
                """
            )
            conn.commit()

    def create_run(self, run_id: str, flow: str, env: str, cycles: int) -> None:
        """
        Insert a running row when a Memory Watch run starts.

        @param run_id: Dashboard run id (mw-xxxxxxxx)
        @param flow: Flow recipe id
        @param env: Target env
        @param cycles: Repeat count
        @returns None
        """
        started_at = _utc_now()
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO memory_watch_runs (
                        run_id, status, flow, env, cycles, started_at
                    ) VALUES (?, 'running', ?, ?, ?, ?)
                    """,
                    (run_id, flow, env, cycles, started_at),
                )
                conn.commit()

    def finish_run(
        self,
        run_id: str,
        status: str,
        samples: list[dict[str, Any]],
        rows: list[dict[str, str]],
        log_text: str,
        verdict_pass: bool | None,
        growth_mb: float | None,
        report_dir: str,
        video_file: str,
    ) -> None:
        """
        Persist samples, log, verdict, and artifact paths for a finished run.

        @param run_id: Dashboard run id
        @param status: completed, failed, or stopped
        @param samples: Heap sample dicts
        @param rows: Parsed checklist rows
        @param log_text: Captured stdout/stderr
        @param verdict_pass: Overall heap verdict
        @param growth_mb: Last minus baseline MB
        @param report_dir: Absolute report folder
        @param video_file: recording.webm or empty
        @returns None
        """
        finished_at = _utc_now()
        verdict_int: int | None
        if verdict_pass is None:
            verdict_int = None
        else:
            verdict_int = 1 if verdict_pass else 0
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                cursor = conn.execute(
                    """
                    UPDATE memory_watch_runs
                    SET status = ?,
                        verdict_pass = ?,
                        growth_mb = ?,
                        finished_at = ?,
                        samples_json = ?,
                        rows_json = ?,
                        log_text = ?,
                        report_dir = ?,
                        video_file = ?
                    WHERE run_id = ?
                    """,
                    (
                        status,
                        verdict_int,
                        growth_mb,
                        finished_at,
                        json.dumps(samples),
                        json.dumps(rows),
                        _trim_log(log_text),
                        report_dir,
                        video_file,
                        run_id,
                    ),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    logger.warning(
                        "MemoryWatchRunStore: finish_run found no row for %s", run_id
                    )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Return recent runs newest first, without logs or samples.

        @param limit: Max rows to return
        @returns List of history summary dicts
        """
        capped = max(1, min(int(limit), 200))
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT run_id, status, flow, env, cycles, verdict_pass, growth_mb,
                       started_at, finished_at
                FROM memory_watch_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (capped,),
            )
            return [_list_item_from_row(row) for row in cursor.fetchall()]

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """
        Return one run including samples, checklist rows, and log.

        @param run_id: Dashboard run id
        @returns Detail dict, or None when missing
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT run_id, status, flow, env, cycles, verdict_pass, growth_mb,
                       started_at, finished_at, samples_json, rows_json, log_text,
                       report_dir, video_file
                FROM memory_watch_runs
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            item = _list_item_from_row(row)
            item["samples"] = _load_json_list(row["samples_json"])
            item["rows"] = _load_json_list(row["rows_json"])
            item["log_text"] = row["log_text"] or ""
            item["report_dir"] = row["report_dir"] or ""
            item["video_file"] = row["video_file"] or ""
            return item

    def _clear_for_testing(self) -> None:
        """Clear all records from the store for testing purposes."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("DELETE FROM memory_watch_runs")
                conn.commit()


def _load_json_list(raw: str) -> list[Any]:
    """
    Parse a JSON array column, returning [] on bad data.

    @param raw: JSON text
    @returns List
    """
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


memory_watch_run_store = MemoryWatchRunStore()
