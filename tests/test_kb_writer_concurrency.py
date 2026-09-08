"""
Phase 5: KBWriter Concurrency Tests
====================================
Module: tests/test_kb_writer_concurrency.py

Tests backend/kb/writer.py KBWriter.append_with_lock():

  1. Two concurrent writers on the same JSON file each produce a valid entry,
     both landing with distinct recorded_by values (no data loss under lock).
  2. When fcntl.flock cannot be acquired within 5 seconds, a sidecar file
     is created at <file>.sidecar-<iso8601>.jsonl and a kb.write_lock_timeout
     WARN log line is emitted (AC-ERROR-9).
  3. Markdown file appends carry a <!-- recorded_by: ... --> prefix so the
     writer's identity is always traceable in human_guidance.md and vSuite-actions.md.

Acceptance Criteria Coverage:
  AC-ERROR-9 — KB write lock timeout → sidecar + WARN log
  Phase 5 — recorded_by attribution on every KB entry
"""

import fcntl
import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writer():
    """Return the KBWriter class."""
    from backend.kb.writer import KBWriter
    return KBWriter


# ---------------------------------------------------------------------------
# 1. Concurrent JSON writers — both entries land without loss
# ---------------------------------------------------------------------------


class TestConcurrentJsonWriters:
    """Two threads writing to the same JSON file both succeed under flock."""

    def test_two_writers_both_entries_land(self, tmp_path):
        """
        Two concurrent KBWriter.append_with_lock() calls to the same JSON file
        each write a distinct recorded_by entry; no data loss.
        """
        KBWriter = _make_writer()
        target = tmp_path / "learned_workflows.json"

        results = []
        errors = []

        def write_entry(step_key, user_email):
            try:
                KBWriter.append_with_lock(
                    file_path=target,
                    key=step_key,
                    value={"action": "click", "selector": f"#btn-{user_email}"},
                    recorded_by=user_email,
                )
                results.append(step_key)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=write_entry, args=("step-alice", "alice@vcreative.com"))
        t2 = threading.Thread(target=write_entry, args=("step-bob", "bob@vcreative.com"))

        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not errors, f"Writer raised exceptions: {errors}"
        assert len(results) == 2, f"Expected 2 successful writes; got {len(results)}"

        data = json.loads(target.read_text(encoding="utf-8"))
        assert "step-alice" in data, "Alice's entry missing from the JSON file"
        assert "step-bob" in data, "Bob's entry missing from the JSON file"

        assert data["step-alice"]["recorded_by"] == "alice@vcreative.com"
        assert data["step-bob"]["recorded_by"] == "bob@vcreative.com"

    def test_writer_creates_file_if_not_exists(self, tmp_path):
        """append_with_lock creates the target file (and parent dirs) if absent."""
        KBWriter = _make_writer()
        target = tmp_path / "new_subdir" / "learned_workflows.json"
        assert not target.exists()

        KBWriter.append_with_lock(
            file_path=target,
            key="step-init",
            value={"action": "navigate", "url": "https://example.com"},
            recorded_by="init@vcreative.com",
        )

        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert "step-init" in data


# ---------------------------------------------------------------------------
# 2. Lock-timeout sidecar fallback (AC-ERROR-9)
# ---------------------------------------------------------------------------


class TestLockTimeoutSidecar:
    """
    AC-ERROR-9: When flock cannot be acquired within the 5s deadline, a sidecar
    file is written and a kb.write_lock_timeout WARN log line is emitted.
    """

    def test_timeout_creates_sidecar_file(self, tmp_path):
        """
        Hold the .lock file externally, then call append_with_lock.
        Expect a sidecar *.jsonl file to appear (lock timeout path).
        """
        KBWriter = _make_writer()
        target = tmp_path / "learned_workflows.json"
        lock_file = tmp_path / "learned_workflows.json.lock"

        # Hold the lock from a background thread so KBWriter cannot acquire it.
        lock_held = threading.Event()
        release_lock = threading.Event()

        def hold_lock():
            with open(lock_file, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                lock_held.set()
                release_lock.wait(timeout=30)
                fcntl.flock(lf, fcntl.LOCK_UN)

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        lock_held.wait(timeout=5)

        try:
            KBWriter.append_with_lock(
                file_path=target,
                key="step-timeout",
                value={"action": "type", "text": "hello"},
                recorded_by="timeout@vcreative.com",
                lock_timeout=1,  # Use a short timeout for the test
            )
        finally:
            release_lock.set()
            holder.join(timeout=5)

        # A sidecar should have been created in the same directory.
        sidecars = list(tmp_path.glob("learned_workflows.json.sidecar-*.jsonl"))
        assert sidecars, (
            "Expected a sidecar .jsonl file after lock timeout; none found in "
            f"{tmp_path}: {list(tmp_path.iterdir())}"
        )

        sidecar_content = sidecars[0].read_text(encoding="utf-8").strip()
        entry = json.loads(sidecar_content)
        assert entry["key"] == "step-timeout"
        assert entry["recorded_by"] == "timeout@vcreative.com"

    def test_timeout_emits_warn_log(self, tmp_path, caplog):
        """
        AC-ERROR-9: lock timeout emits a WARN-level kb.write_lock_timeout log event.
        """
        KBWriter = _make_writer()
        target = tmp_path / "learned_workflows.json"
        lock_file = tmp_path / "learned_workflows.json.lock"

        lock_held = threading.Event()
        release_lock = threading.Event()

        def hold_lock():
            with open(lock_file, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                lock_held.set()
                release_lock.wait(timeout=30)
                fcntl.flock(lf, fcntl.LOCK_UN)

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        lock_held.wait(timeout=5)

        with caplog.at_level(logging.WARNING, logger="backend.kb.writer"):
            try:
                KBWriter.append_with_lock(
                    file_path=target,
                    key="step-warn",
                    value={"action": "click"},
                    recorded_by="warn@vcreative.com",
                    lock_timeout=1,
                )
            finally:
                release_lock.set()
                holder.join(timeout=5)

        warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("kb.write_lock_timeout" in m for m in warn_messages), (
            f"Expected a kb.write_lock_timeout WARN log; got: {warn_messages}"
        )


# ---------------------------------------------------------------------------
# 3. Markdown append attribution
# ---------------------------------------------------------------------------


class TestMarkdownAttribution:
    """Markdown appends carry a <!-- recorded_by: ... --> prefix."""

    def test_markdown_append_includes_recorded_by_comment(self, tmp_path):
        """
        KBWriter.append_markdown_with_lock writes a
        '<!-- recorded_by: <email> -->' prefix before the new block.
        """
        KBWriter = _make_writer()
        target = tmp_path / "human_guidance.md"
        target.write_text("# Existing content\n\n", encoding="utf-8")

        KBWriter.append_markdown_with_lock(
            file_path=target,
            content="## New guidance block\n\nSome text.",
            recorded_by="author@vcreative.com",
        )

        text = target.read_text(encoding="utf-8")
        assert "<!-- recorded_by: author@vcreative.com -->" in text, (
            f"Expected recorded_by attribution comment in markdown output; got:\n{text}"
        )
        assert "## New guidance block" in text
