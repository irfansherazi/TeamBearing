"""
backend/engine/memory_watch_runner.py
=====================================
Thin wrapper around ``npm run memory:test``.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any

_VREVIEW_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_FLOWS = frozenset(
    {
        "qo-open-close-snapshot",
        "po-open-spot",
        "po-open-spot-warm",
        "po-search-panel",
        "ai-intake-open-close",
        "sidebar-open-close",
    }
)
_ALLOWED_ENVS = frozenset({"local", "qa", "test", "smoke"})
_SAMPLE_PREFIX = "MEMORY_WATCH_SAMPLE "
_VERDICT_PREFIX = "MEMORY_WATCH_VERDICT "
_REPORT_PREFIX = "MEMORY_WATCH_REPORT "


class MemoryWatchValidationError(Exception):
    """Raised when flow / env / cycles fail input validation."""


class MemoryWatchConfigError(Exception):
    """Raised when the memory:test CLI cannot be used."""


def validate_flow(value: str) -> str:
    """
    Accept a known Memory Watch flow id.

    @param value: Raw form field
    @returns Stripped flow id
    """
    stripped = (value or "").strip()
    if stripped not in _ALLOWED_FLOWS:
        raise MemoryWatchValidationError(
            "Flow must be qo-open-close-snapshot, po-open-spot, po-open-spot-warm, "
            "po-search-panel, ai-intake-open-close, or sidebar-open-close"
        )
    return stripped


def validate_env(value: str) -> str:
    """
    Accept local, qa, test, or smoke.

    @param value: Raw form field
    @returns Stripped env id
    """
    stripped = (value or "qa").strip().lower()
    if stripped not in _ALLOWED_ENVS:
        raise MemoryWatchValidationError("Env must be local, qa, test, or smoke")
    return stripped


def validate_cycles(value: int | str) -> int:
    """
    Accept a cycle count from 1 to 20.

    @param value: Raw form field
    @returns Integer cycle count
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MemoryWatchValidationError("Cycles must be an integer from 1 to 20") from exc
    if parsed < 1 or parsed > 20:
        raise MemoryWatchValidationError("Cycles must be an integer from 1 to 20")
    return parsed


def build_memory_watch_argv(flow: str, env: str, cycles: int) -> list[str]:
    """
    Build subprocess argv for npm run memory:test (no shell).

    @param flow: --flow value
    @param env: --env value
    @param cycles: --cycles value
    @returns Argv list
    """
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    return [
        npm_bin,
        "run",
        "memory:test",
        "--",
        f"--flow={flow}",
        f"--env={env}",
        f"--cycles={cycles}",
    ]


def resolve_memory_watch_cwd() -> Path:
    """
    Resolve the vReview directory that can run npm run memory:test.

    @returns Absolute cwd for the subprocess
    """
    script = _VREVIEW_ROOT / "scripts" / "memory-test.js"
    if not script.is_file():
        raise MemoryWatchConfigError(f"vReview is missing {script}.")
    return _VREVIEW_ROOT.resolve()


def _parse_prefixed_json(line: str, prefix: str) -> dict[str, Any] | None:
    """
    Parse a prefixed JSON log line.

    @param line: Raw stdout line
    @param prefix: Expected prefix
    @returns Object, or None
    """
    stripped = line.strip()
    if not stripped.startswith(prefix):
        return None
    raw = stripped[len(prefix) :]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def parse_memory_sample_line(line: str) -> dict[str, Any] | None:
    """
    Parse MEMORY_WATCH_SAMPLE JSON.

    @param line: Raw stdout line
    @returns Sample dict, or None
    """
    return _parse_prefixed_json(line, _SAMPLE_PREFIX)


def parse_memory_verdict_line(line: str) -> dict[str, Any] | None:
    """
    Parse MEMORY_WATCH_VERDICT JSON.

    @param line: Raw stdout line
    @returns Verdict dict, or None
    """
    return _parse_prefixed_json(line, _VERDICT_PREFIX)


def parse_memory_report_line(line: str) -> dict[str, Any] | None:
    """
    Parse MEMORY_WATCH_REPORT JSON.

    @param line: Raw stdout line
    @returns Report paths dict, or None
    """
    parsed = _parse_prefixed_json(line, _REPORT_PREFIX)
    if parsed is None:
        return None
    report_dir = str(parsed.get("dir") or "")
    if not report_dir:
        return None
    return parsed


_SAFE_RUN_ID = re.compile(r"^mw-[a-f0-9]{8}$")


def is_memory_watch_run_id(run_id: str) -> bool:
    """
    Return True when the id matches mw- + 8 hex chars.

    @param run_id: Candidate run id
    @returns True when valid
    """
    return bool(_SAFE_RUN_ID.match(run_id))


def kill_memory_watch_pid(pid: int) -> None:
    """
    Stop a Memory Watch subprocess and its children.

    Windows needs taskkill /T because npm.cmd leaves Playwright running.

    @param pid: npm / node PID tracked for the run
    @returns None
    """
    if not isinstance(pid, int) or pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    os.kill(pid, signal.SIGTERM)
