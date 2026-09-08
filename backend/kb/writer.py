"""
KB Writer — Phase 5: fcntl.flock-based concurrency-safe KB writes.
===================================================================
Module: backend/kb/writer.py

Provides a single class ``KBWriter`` with two class methods:

- ``append_with_lock(file_path, key, value, recorded_by, lock_timeout=5)``
  Atomically appends or updates a JSON entry in a KB JSON file (last-write-wins
  within the lock window).  Every entry is stamped with ``recorded_by`` and
  ``recorded_at`` so the contributing session is always traceable.

  On ``fcntl.flock`` acquisition failure after ``lock_timeout`` seconds, the
  entry is written to a sidecar file at
  ``<file>.sidecar-<iso8601>.jsonl`` and a ``kb.write_lock_timeout`` WARN log
  is emitted.  The user-visible "Done" flow does NOT surface an error — the
  write is best-effort with a manual reconciliation path (AC-ERROR-9).

- ``append_markdown_with_lock(file_path, content, recorded_by, lock_timeout=5)``
  Appends a markdown block to a ``.md`` KB file (e.g. human_guidance.md,
  vSuite-actions.md) under an exclusive flock.  The new content is prefixed
  with ``<!-- recorded_by: <email> -->`` for attribution tracing.

Architecture notes
------------------
- Uses a lock-sidecar file at ``<target>.lock`` (created if absent) so flock
  can be used even on files that are consumed by external readers who may not
  open the target exclusively.
- flock is a *per-process* / *per-file-descriptor* lock (POSIX advisory lock).
  It guards concurrent vQA processes/threads on the same host — the single-
  worker uvicorn invariant (``--workers 1``) means all requests run in one
  process; multiple threads (asyncio executor pool) require the flock.
- Lock acquisition uses LOCK_EX | LOCK_NB (non-blocking) inside a retry loop
  so we can enforce an arbitrary deadline rather than blocking indefinitely.
- File handles are passed through the call chain (not stored as class state) so
  the implementation is thread-safe under concurrent callers.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_LOCK_TIMEOUT_SECONDS: int = 5
_LOCK_POLL_INTERVAL_SECONDS: float = 0.05  # 50 ms retry cadence


class KBWriter:
    """Concurrency-safe KB writer using fcntl.flock advisory locks.

    All methods are **class methods** — instantiation is unnecessary.  Callers
    import the class and call the method directly:

        KBWriter.append_with_lock(file_path=..., key=..., value=..., recorded_by=...)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def append_with_lock(
        cls,
        file_path: Path | str,
        key: str,
        value: dict[str, Any],
        recorded_by: str,
        recorded_at: str | None = None,
        lock_timeout: int = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        """Atomically append / update a JSON entry under an exclusive flock.

        Parameters
        ----------
        file_path : Path | str
            The JSON file to write (e.g. knowledge/blueprints/learned_workflows.json).
        key : str
            The top-level JSON key to set / overwrite (last-write-wins).
        value : dict
            The value dict for ``key``.  The writer stamps ``recorded_by`` and
            ``recorded_at`` onto the dict before writing.
        recorded_by : str
            User email (or "anonymous") identifying the session that triggered this write.
        recorded_at : str | None
            ISO-8601 timestamp.  Defaults to ``datetime.now(timezone.utc).isoformat()``.
        lock_timeout : int
            Seconds to wait for the exclusive lock before falling back to the sidecar path.
        """
        target = Path(file_path)
        _recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()
        stamped_value = {**value, "recorded_by": recorded_by, "recorded_at": _recorded_at}

        target.parent.mkdir(parents=True, exist_ok=True)
        lock_file = target.with_name(target.name + ".lock")

        with cls._try_lock(lock_file, timeout=lock_timeout) as acquired:
            if not acquired:
                cls._write_sidecar(
                    target, key=key, value=stamped_value, recorded_by=recorded_by
                )
                return

            # Read-modify-write under the lock.
            existing: dict[str, Any] = {}
            if target.exists():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}

            existing[key] = stamped_value
            target.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    @classmethod
    def append_jsonl_with_lock(
        cls,
        file_path: Path | str,
        record: dict[str, Any],
        recorded_by: str,
        recorded_at: str | None = None,
        lock_timeout: int = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        """Append a single JSONL record under an exclusive flock.

        Stamps ``recorded_by`` and ``recorded_at`` onto the record before
        writing. On lock timeout, falls back to the sidecar path.
        """
        target = Path(file_path)
        _recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()
        stamped = {**record, "recorded_by": recorded_by, "recorded_at": _recorded_at}

        target.parent.mkdir(parents=True, exist_ok=True)
        lock_file = target.with_name(target.name + ".lock")

        with cls._try_lock(lock_file, timeout=lock_timeout) as acquired:
            if not acquired:
                cls._write_sidecar(
                    target, key="__jsonl_append__", value=stamped, recorded_by=recorded_by
                )
                return
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")

    @classmethod
    def append_markdown_with_lock(
        cls,
        file_path: Path | str,
        content: str,
        recorded_by: str,
        lock_timeout: int = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        """Append a markdown block with a ``<!-- recorded_by: ... -->`` prefix.

        Parameters
        ----------
        file_path : Path | str
            The markdown file to append to (e.g. knowledge/human_guidance.md).
        content : str
            The new markdown block to append.
        recorded_by : str
            User email identifying the session that triggered the write.
        lock_timeout : int
            Seconds to wait for the exclusive lock before falling back to sidecar.
        """
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        attribution_comment = f"<!-- recorded_by: {recorded_by} -->"
        block = f"\n{attribution_comment}\n{content}\n"

        lock_file = target.with_name(target.name + ".lock")

        with cls._try_lock(lock_file, timeout=lock_timeout) as acquired:
            if not acquired:
                cls._write_sidecar(
                    target,
                    key="__markdown_append__",
                    value={"content": content},
                    recorded_by=recorded_by,
                )
                return

            with open(target, "a", encoding="utf-8") as fh:
                fh.write(block)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    @contextlib.contextmanager
    def _try_lock(cls, lock_file: Path, timeout: int) -> Iterator[bool]:
        """Context manager: yields True if LOCK_EX acquired within ``timeout`` seconds.

        Yields False and does NOT release (no lock held) if the deadline is exceeded.
        Uses non-blocking flock in a polling loop so the deadline is precise.
        """
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout

        fh = open(lock_file, "w")  # noqa: WPS515 — held until lock released in finally
        try:
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Lock acquired — run the body.
                    try:
                        yield True
                    finally:
                        fcntl.flock(fh, fcntl.LOCK_UN)
                    return  # normal exit after unlock
                except (IOError, OSError):
                    pass  # lock held by another thread/process

                if time.monotonic() >= deadline:
                    # Timeout — yield False so the caller can write the sidecar.
                    yield False
                    return

                time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        finally:
            fh.close()

    @classmethod
    def _write_sidecar(
        cls,
        target: Path,
        key: str,
        value: dict[str, Any],
        recorded_by: str,
    ) -> None:
        """Write the entry to a sidecar JSONL file and emit a WARN log.

        The sidecar is named ``<target>.sidecar-<iso8601>.jsonl`` in the same
        directory as ``target``.  The timestamp uses colons replaced by hyphens
        so the filename is filesystem-safe on all platforms.
        """
        ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
        sidecar_path = target.with_name(f"{target.name}.sidecar-{ts}.jsonl")
        try:
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_entry = {
                "key": key,
                "value": value,
                "recorded_by": recorded_by,
                "sidecar_reason": "lock_timeout",
            }
            sidecar_path.write_text(json.dumps(sidecar_entry) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.error("kb.writer: failed to write sidecar %s: %s", sidecar_path, exc)

        logger.warning(
            "kb.write_lock_timeout file=%s recorded_by=%s sidecar_path=%s",
            target,
            recorded_by,
            sidecar_path,
        )
