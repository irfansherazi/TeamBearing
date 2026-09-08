"""
vQA — Test Suite Store (Phase 7A)
====================================
Module: backend/storage/test_suites.py

SQLite-backed persistence for reusable test suites.

A "suite" groups multiple Jira tickets into a named, re-runnable
collection with an optional cron schedule for recurring execution.

Usage
-----
    from backend.storage.test_suites import suite_store

    # Create a suite
    suite_id = suite_store.create_suite(
        name="Smoke Suite",
        description="Critical path validation",
        tickets=[
            {"jira_ticket_id": "QA-280", "role": "account_executive"},
            {"jira_ticket_id": "QA-281", "role": "production_manager"},
        ],
        schedule_cron="0 6 * * 1-5",  # weekdays at 6 AM
    )

    # List all suites
    suites = suite_store.list_suites()

    # Run a suite
    suite = suite_store.get_suite(suite_id)
    for ticket in suite["tickets"]:
        ...  # trigger execution

See Also
--------
  - ``backend/api/routes.py``          — suite CRUD endpoints
  - ``backend/engine/scheduler.py``    — cron-based suite execution
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VQAROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _VQAROOT / "memory" / "test_suites.db"


class SuiteStore:
    """
    SQLite-backed test suite store.

    Thread-safe — all writes serialized through a lock.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("SuiteStore: initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create the suites table if it doesn't exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suites (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL UNIQUE,
                    description   TEXT NOT NULL DEFAULT '',
                    tickets       TEXT NOT NULL DEFAULT '[]',
                    schedule_cron TEXT NOT NULL DEFAULT '',
                    enabled       INTEGER NOT NULL DEFAULT 1,
                    last_run_id   TEXT NOT NULL DEFAULT '',
                    last_run_at   TEXT NOT NULL DEFAULT '',
                    last_status   TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def create_suite(
        self,
        name: str,
        description: str = "",
        tickets: list[dict[str, str]] | None = None,
        schedule_cron: str = "",
    ) -> str:
        """
        Create a new test suite.

        Parameters
        ----------
        name : str
            Unique suite name (e.g. "Smoke Suite").
        description : str
            Human-readable description.
        tickets : list[dict]
            List of ticket configs: ``[{"jira_ticket_id": "QA-280", "role": "account_executive"}]``
        schedule_cron : str
            Optional cron expression for recurring runs (e.g. "0 6 * * 1-5").

        Returns
        -------
        str
            The generated suite ID.
        """
        suite_id = f"suite-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        tickets_json = json.dumps(tickets or [])

        with self._lock:
            try:
                with sqlite3.connect(str(self._db_path)) as conn:
                    conn.execute(
                        """
                        INSERT INTO suites
                        (id, name, description, tickets, schedule_cron, enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (suite_id, name, description, tickets_json, schedule_cron, now, now),
                    )
                    conn.commit()
                logger.info("Suite created: %s (%s) — %d tickets", suite_id, name, len(tickets or []))
                return suite_id
            except sqlite3.IntegrityError as e:
                logger.warning("Suite creation failed (duplicate name?): %s", e)
                raise ValueError(f"Suite with name '{name}' already exists") from e

    def get_suite(self, suite_id: str) -> dict[str, Any] | None:
        """Get a suite by ID."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM suites WHERE id = ?", (suite_id,)).fetchone()
                if not row:
                    return None
                d = dict(row)
                d["tickets"] = json.loads(d.get("tickets", "[]"))
                return d
        except Exception as e:
            logger.warning("SuiteStore: get_suite failed: %s", e)
            return None

    def get_suite_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a suite by name."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM suites WHERE name = ?", (name,)).fetchone()
                if not row:
                    return None
                d = dict(row)
                d["tickets"] = json.loads(d.get("tickets", "[]"))
                return d
        except Exception as e:
            logger.warning("SuiteStore: get_suite_by_name failed: %s", e)
            return None

    def list_suites(self) -> list[dict[str, Any]]:
        """Get all suites, newest first."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM suites ORDER BY created_at DESC").fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["tickets"] = json.loads(d.get("tickets", "[]"))
                    result.append(d)
                return result
        except Exception as e:
            logger.warning("SuiteStore: list_suites failed: %s", e)
            return []

    def update_suite(
        self,
        suite_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tickets: list[dict[str, str]] | None = None,
        schedule_cron: str | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """
        Update a suite. Only provided fields are changed.

        Returns True if the suite was found and updated.
        """
        updates: list[str] = []
        params: list[Any] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if tickets is not None:
            updates.append("tickets = ?")
            params.append(json.dumps(tickets))
        if schedule_cron is not None:
            updates.append("schedule_cron = ?")
            params.append(schedule_cron)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(suite_id)

        with self._lock:
            try:
                with sqlite3.connect(str(self._db_path)) as conn:
                    result = conn.execute(
                        f"UPDATE suites SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                    conn.commit()
                    return result.rowcount > 0
            except Exception as e:
                logger.warning("SuiteStore: update_suite failed: %s", e)
                return False

    def record_run(self, suite_id: str, run_id: str, status: str) -> None:
        """Record the last run result for a suite."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                with sqlite3.connect(str(self._db_path)) as conn:
                    conn.execute(
                        "UPDATE suites SET last_run_id = ?, last_run_at = ?, last_status = ?, updated_at = ? WHERE id = ?",
                        (run_id, now, status, now, suite_id),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning("SuiteStore: record_run failed: %s", e)

    def delete_suite(self, suite_id: str) -> bool:
        """Delete a suite. Returns True if it existed."""
        with self._lock:
            try:
                with sqlite3.connect(str(self._db_path)) as conn:
                    result = conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))
                    conn.commit()
                    return result.rowcount > 0
            except Exception as e:
                logger.warning("SuiteStore: delete_suite failed: %s", e)
                return False

    def get_scheduled_suites(self) -> list[dict[str, Any]]:
        """Get all enabled suites with a cron schedule."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM suites WHERE enabled = 1 AND schedule_cron != '' ORDER BY name"
                ).fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["tickets"] = json.loads(d.get("tickets", "[]"))
                    result.append(d)
                return result
        except Exception as e:
            logger.warning("SuiteStore: get_scheduled_suites failed: %s", e)
            return []


# Module-level singleton
suite_store = SuiteStore()
