"""
vQA — Accepted Test Store
==========================
Module: backend/storage/accepted_test_store.py

Filesystem-based persistence layer for accepted vQA test runs.

When a QA engineer or operator "accepts" a completed run (via POST
/runs/{run_id}/accept), the action sequence is serialized and stored
here.  On subsequent runs for the same Jira ticket with identical AC,
the ``ReplayEngine`` reads from this store to bypass the LLM planner
entirely.

Storage Layout
--------------
``{accepted_tests_dir}/``
├── index.json                              # ticket_id+ac_hash → filename map
├── VC2-9001-a3f8c12de901.json             # individual record files
└── VC2-9002-b92f4701c0e3.json

Record File Schema (JSON)
-------------------------
{
    "ticket_id":     "VC2-9001",
    "ac_hash":       "a3f8c12de901",
    "run_id":        "run-abc123",
    "accepted_at":   "2026-05-19T12:00:00Z",
    "execution_log": [ ...ExecutionStep dicts... ],
    "replay_actions": [ ...filtered successful-only steps... ]
}

Thread Safety
-------------
Writes use a ``threading.Lock`` to protect the index file.  Concurrent
saves to *different* tickets are serialized only at the index-write step,
which is fast (< 1ms).

Security
--------
``ticket_id`` is validated against a whitelist pattern and path-resolved
to ensure it stays within the store directory.  Directory traversal
attempts raise ``ValueError``.

Author: vQA Build Agent (TASK-031 Phase 2)
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.storage.spec_serializer import compute_ac_hash, extract_replay_actions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation: allowed characters in ticket_id
# ---------------------------------------------------------------------------
# Jira ticket IDs follow the pattern: PROJECT-12345 (letters, digits, hyphens).
# We also accept lowercase for flexibility.  Any other character (including
# dots, slashes, backslashes) is rejected to prevent path traversal.
_TICKET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]+$")

# ---------------------------------------------------------------------------
# Index file name
# ---------------------------------------------------------------------------
_INDEX_FILE = "index.json"


class AcceptedTestStore:
    """
    Filesystem-backed store for accepted vQA test action sequences.

    Each record maps a ``(ticket_id, ac_hash)`` pair to a serialized list
    of ``ExecutionStep`` dicts.  When the ReplayEngine finds a matching
    record, it replays the steps deterministically without invoking the
    LLM planner.

    Usage
    -----
    >>> store = AcceptedTestStore(store_dir="memory/accepted_tests")
    >>> store.save(
    ...     ticket_id="VC2-9001",
    ...     ac_steps=ac_steps,
    ...     execution_log=state.detailed_execution_log,
    ...     run_id=run_id,
    ... )
    >>> record = store.load(ticket_id="VC2-9001", ac_steps=ac_steps)
    >>> if record:
    ...     actions = record["replay_actions"]  # Use for deterministic replay

    Attributes
    ----------
    store_dir : Path
        Absolute path to the directory holding accepted test records.
    """

    def __init__(self, store_dir: str) -> None:
        """
        Initialise the store and create the directory if it doesn't exist.

        Args
        ----
        store_dir : str
            Path (absolute or relative) to the accepted test storage directory.
            Created automatically (including parent dirs) if it doesn't exist.
        """
        self.store_dir: Path = Path(store_dir).resolve()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        logger.info("AcceptedTestStore initialised at: %s", self.store_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        ticket_id: str,
        ac_steps: list[str],
        execution_log: list[dict[str, Any]],
        run_id: str,
    ) -> Path:
        """
        Serialize and store an accepted test run.

        If a record for the same ``ticket_id`` + ``ac_hash`` already exists,
        it is overwritten (atomic rename via tmp file).

        Args
        ----
        ticket_id : str
            Jira ticket ID (e.g. ``"VC2-9001"``).  Must match
            ``^[A-Za-z0-9][A-Za-z0-9-]+$``.
        ac_steps : list[str]
            The acceptance criteria steps used for this run.
            Their SHA-256 hash determines the cache key.
        execution_log : list[dict]
            The full ``VQAState.detailed_execution_log`` list.
            Failed steps are filtered out before storage.
        run_id : str
            The run ID of the accepted execution.

        Returns
        -------
        Path
            The absolute path to the saved record file.

        Raises
        ------
        ValueError
            If ``ticket_id`` contains invalid characters or path traversal sequences.
        """
        self._validate_ticket_id(ticket_id)
        ac_hash = compute_ac_hash(ac_steps)
        replay_actions = extract_replay_actions(execution_log)

        record: dict[str, Any] = {
            "ticket_id": ticket_id,
            "ac_hash": ac_hash,
            "run_id": run_id,
            "accepted_at": datetime.now(UTC).isoformat(),
            "last_used": datetime.now(UTC).isoformat(),
            "execution_log": execution_log,
            "replay_actions": replay_actions,
            "step_count": len(replay_actions),
        }

        file_name = self._record_filename(ticket_id, ac_hash)
        file_path = self._safe_path(file_name)

        # Atomic write: write to tmp then rename so concurrent readers never
        # see a partial file.
        tmp_path = file_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(record, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.rename(file_path)
        except Exception:
            # Clean up tmp on failure
            tmp_path.unlink(missing_ok=True)
            raise

        # Update the index (thread-safe)
        with self._lock:
            self._update_index(ticket_id, ac_hash, file_name)
            # Prune old records to stay within budget (TD-009/TD-010)
            self.prune()

        logger.info(
            "AcceptedTestStore.save: stored %d replay actions for %s (ac_hash=%s)",
            len(replay_actions),
            ticket_id,
            ac_hash,
        )
        return file_path

    def load(
        self,
        ticket_id: str,
        ac_steps: list[str],
    ) -> dict[str, Any] | None:
        """
        Load the accepted test record for a ``(ticket_id, ac_hash)`` pair.

        Updates the ``last_used`` timestamp in both the record file and the index.

        Args
        ----
        ticket_id : str
            Jira ticket ID.
        ac_steps : list[str]
            The acceptance criteria steps to hash.

        Returns
        -------
        dict | None
            The stored record dict (containing ``replay_actions`` etc.),
            or ``None`` if no matching record exists.
        """
        ac_hash = compute_ac_hash(ac_steps)
        file_name = self._record_filename(ticket_id, ac_hash)
        file_path = self._safe_path(file_name)

        if not file_path.exists():
            return None

        try:
            record = json.loads(file_path.read_text(encoding="utf-8"))

            # Update last_used
            now = datetime.now(UTC).isoformat()
            record["last_used"] = now

            # Update the record file atomically
            tmp_path = file_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.rename(file_path)

            # Update the index (thread-safe)
            with self._lock:
                self._update_index(ticket_id, ac_hash, file_name, last_used=now)

            logger.info(
                "AcceptedTestStore.load: found %d replay actions for %s (ac_hash=%s)",
                len(record.get("replay_actions", [])),
                ticket_id,
                ac_hash,
            )
            return record
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "AcceptedTestStore.load: failed to read/update record for %s/%s: %s",
                ticket_id,
                ac_hash,
                e,
            )
            return None

    def prune(self) -> int:
        """
        Remove old accepted test records based on age and total count.

        Configuration is read from ``settings.accepted_tests_max_count`` and
        ``settings.accepted_tests_max_age_days``.

        Returns
        -------
        int
            Number of records pruned.
        """
        from backend.config import settings

        index = self._load_index_raw()
        if not index:
            return 0

        now = datetime.now(UTC)
        pruned_count = 0

        # 1. Prune by age
        max_age = settings.accepted_tests_max_age_days
        keys_to_remove = []
        for key, info in index.items():
            last_used_str = info.get("last_used")
            if not last_used_str:
                continue
            try:
                last_used = datetime.fromisoformat(last_used_str).replace(tzinfo=UTC)
                age_days = (now - last_used).days
                if age_days > max_age:
                    keys_to_remove.append(key)
            except ValueError:
                continue

        for key in keys_to_remove:
            info = index.pop(key)
            file_path = self._safe_path(info["file_name"])
            file_path.unlink(missing_ok=True)
            pruned_count += 1

        # 2. Prune by total count
        max_count = settings.accepted_tests_max_count
        if len(index) > max_count:
            # Sort by last_used ascending (oldest first)
            sorted_entries = sorted(
                index.items(),
                key=lambda x: x[1].get("last_used", "")
            )
            num_to_prune = len(index) - max_count
            for i in range(num_to_prune):
                key, info = sorted_entries[i]
                index.pop(key)
                file_path = self._safe_path(info["file_name"])
                file_path.unlink(missing_ok=True)
                pruned_count += 1

        if pruned_count > 0:
            self._save_index_raw(index)
            logger.info("AcceptedTestStore.prune: removed %d records", pruned_count)

        return pruned_count

    def has_accepted(self, ticket_id: str, ac_steps: list[str]) -> bool:
        """
        Check whether an accepted test record exists for a ticket+AC pair.

        This is a fast filesystem existence check — no JSON parsing.

        Args
        ----
        ticket_id : str
            Jira ticket ID.
        ac_steps : list[str]
            The current acceptance criteria steps.

        Returns
        -------
        bool
            True if a matching accepted test exists.
        """
        ac_hash = compute_ac_hash(ac_steps)
        file_name = self._record_filename(ticket_id, ac_hash)
        file_path = self._safe_path(file_name)
        return file_path.exists()

    def delete(self, ticket_id: str, ac_steps: list[str]) -> bool:
        """
        Remove an accepted test record.

        Args
        ----
        ticket_id : str
        ac_steps : list[str]

        Returns
        -------
        bool
            True if the record existed and was deleted; False if not found.
        """
        self._validate_ticket_id(ticket_id)
        ac_hash = compute_ac_hash(ac_steps)
        file_name = self._record_filename(ticket_id, ac_hash)
        file_path = self._safe_path(file_name)

        if not file_path.exists():
            return False

        file_path.unlink()

        with self._lock:
            self._remove_from_index(ticket_id, ac_hash)

        logger.info("AcceptedTestStore.delete: removed record for %s (ac_hash=%s)", ticket_id, ac_hash)
        return True

    def list_all(self) -> list[dict[str, str]]:
        """
        Return a list of all accepted test records in the store.

        Returns
        -------
        list[dict]
            Each dict has ``ticket_id``, ``ac_hash``, and ``accepted_at``.
            Sorted by ``accepted_at`` descending (newest first).
        """
        index = self._load_index()
        result: list[dict[str, str]] = []
        for (ticket_id, ac_hash), file_name in index.items():
            file_path = self._safe_path(file_name)
            if file_path.exists():
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    result.append(
                        {
                            "ticket_id": data.get("ticket_id", ticket_id),
                            "ac_hash": data.get("ac_hash", ac_hash),
                            "accepted_at": data.get("accepted_at", ""),
                            "step_count": data.get("step_count", 0),
                            "run_id": data.get("run_id", ""),
                        }
                    )
                except (json.JSONDecodeError, OSError):
                    pass
        # Newest first
        result.sort(key=lambda r: r.get("accepted_at", ""), reverse=True)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_filename(ticket_id: str, ac_hash: str) -> str:
        """Return the deterministic filename for a record."""
        # Normalize ticket_id: uppercase, safe characters only
        safe_id = re.sub(r"[^A-Za-z0-9\-]", "_", ticket_id)
        return f"{safe_id}-{ac_hash}.json"

    def _safe_path(self, file_name: str) -> Path:
        """
        Resolve the file path and verify it stays within store_dir.

        This is the core directory-traversal guard.  Even if a crafted
        ``file_name`` contained ``../`` sequences, the resolved path would
        not start with ``store_dir`` and would raise ``ValueError``.
        """
        candidate = (self.store_dir / file_name).resolve()
        if not str(candidate).startswith(str(self.store_dir)):
            raise ValueError(f"Security: resolved path {candidate} escapes store dir {self.store_dir}")
        return candidate

    @staticmethod
    def _validate_ticket_id(ticket_id: str) -> None:
        """
        Validate the ticket_id against the whitelist pattern.

        Raises
        ------
        ValueError
            If the ticket_id contains path traversal sequences or
            characters not in ``[A-Za-z0-9-]``.
        """
        # Quick check for common traversal sequences first (fast path)
        if ".." in ticket_id or "/" in ticket_id or "\\" in ticket_id:
            raise ValueError(f"Invalid ticket_id: {ticket_id!r} contains path traversal sequences.")
        if not _TICKET_ID_PATTERN.match(ticket_id):
            raise ValueError(f"Invalid ticket_id: {ticket_id!r} must match ^[A-Za-z0-9][A-Za-z0-9-]+$")

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self.store_dir / _INDEX_FILE

    def _load_index_raw(self) -> dict[str, dict[str, Any]]:
        """
        Load the raw index JSON from disk.

        Returns
        -------
        dict
            Raw index mapping "ticket_id__ac_hash" to a dict of metadata.
        """
        idx_path = self._index_path()
        if not idx_path.exists():
            return {}
        try:
            raw = json.loads(idx_path.read_text(encoding="utf-8"))
            # Migration: convert old string values to dicts
            updated = False
            for k, v in raw.items():
                if isinstance(v, str):
                    raw[k] = {"file_name": v, "last_used": datetime.now(UTC).isoformat()}
                    updated = True
            if updated:
                self._save_index_raw(raw)
            return raw
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("AcceptedTestStore: corrupt index, rebuilding. Error: %s", e)
            return self._rebuild_index_raw()

    def _save_index_raw(self, index: dict[str, dict[str, Any]]) -> None:
        """Write the raw index atomically."""
        idx_path = self._index_path()
        tmp_path = idx_path.with_suffix(".idx.tmp")
        tmp_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.rename(idx_path)

    def _load_index(self) -> dict[tuple[str, str], str]:
        """
        Load the index and return a compatibility mapping (tuple -> filename).
        """
        raw = self._load_index_raw()
        return {
            tuple(k.split("__", 1)): v["file_name"]  # type: ignore[return-value]
            for k, v in raw.items()
        }

    def _save_index(self, index: dict[tuple[str, str], str]) -> None:
        """
        Compatibility wrapper for saving index.
        Note: This is now less preferred than _update_index.
        """
        raw = self._load_index_raw()
        for (ticket_id, ac_hash), file_name in index.items():
            key = f"{ticket_id}__{ac_hash}"
            if key not in raw:
                raw[key] = {"file_name": file_name, "last_used": datetime.now(UTC).isoformat()}
            else:
                raw[key]["file_name"] = file_name
        self._save_index_raw(raw)

    def _update_index(self, ticket_id: str, ac_hash: str, file_name: str, last_used: str | None = None) -> None:
        """Add or update an entry in the index (caller holds the lock)."""
        raw = self._load_index_raw()
        key = f"{ticket_id}__{ac_hash}"
        raw[key] = {
            "file_name": file_name,
            "last_used": last_used or datetime.now(UTC).isoformat()
        }
        self._save_index_raw(raw)

    def _remove_from_index(self, ticket_id: str, ac_hash: str) -> None:
        """Remove an entry from the index (caller holds the lock)."""
        raw = self._load_index_raw()
        key = f"{ticket_id}__{ac_hash}"
        raw.pop(key, None)
        self._save_index_raw(raw)

    def _rebuild_index_raw(self) -> dict[str, dict[str, Any]]:
        """
        Rebuild the raw index by scanning all .json files in the store directory.
        """
        index: dict[str, dict[str, Any]] = {}
        for json_file in self.store_dir.glob("*.json"):
            if json_file.name == _INDEX_FILE:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                ticket_id = data.get("ticket_id")
                ac_hash = data.get("ac_hash")
                if ticket_id and ac_hash:
                    key = f"{ticket_id}__{ac_hash}"
                    index[key] = {
                        "file_name": json_file.name,
                        "last_used": data.get("last_used") or data.get("accepted_at") or datetime.now(UTC).isoformat()
                    }
            except (json.JSONDecodeError, OSError):
                pass
        # Persist the rebuilt index
        self._save_index_raw(index)
        logger.info("AcceptedTestStore: rebuilt index with %d entries", len(index))
        return index

    def _rebuild_index(self) -> dict[tuple[str, str], str]:
        """Compatibility wrapper for rebuild."""
        raw = self._rebuild_index_raw()
        return {
            tuple(k.split("__", 1)): v["file_name"]  # type: ignore[return-value]
            for k, v in raw.items()
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def _get_store_singleton() -> AcceptedTestStore:
    """
    Lazy-initialise the global AcceptedTestStore from settings.

    Uses a module-level cache so the store is only created once per process,
    regardless of how many routes call ``get_accepted_test_store()``.
    """
    global _store_instance
    if _store_instance is None:
        from backend.config import settings

        _store_instance = AcceptedTestStore(store_dir=settings.accepted_tests_dir)
    return _store_instance


_store_instance: AcceptedTestStore | None = None


def get_accepted_test_store() -> AcceptedTestStore:
    """
    Return the application-wide AcceptedTestStore singleton.

    Initialised from ``settings.accepted_tests_dir`` on first call.
    Use this in FastAPI route handlers.
    """
    return _get_store_singleton()
