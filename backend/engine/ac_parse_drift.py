"""
T3-d — AC Parse Drift Guard (FEAT-118)
=======================================
Module: backend/engine/ac_parse_drift.py

Provides deterministic drift assertion for the two-stage AC parser.

After Stage 2 JSON compilation completes, ``ACParseDriftGuard.assert_drift()``
compares the freshly-compiled step count against the per-ticket baseline stored in
``storage/ac_parse_baseline/<ticket_key>.json``.

Behaviour (per architecture doc CQ-D2 decision):

* **Tracked ticket** (entry in ``_manifest.json``):
  - If ``|current - baseline| > tolerance``:  raise ``ACParseDriftError``.
    The run terminates with ``failure_type="AC_PARSE_DRIFT"``.
  - If the raw-AC content hash has changed since baseline capture:
    log a WARNING banner ("AC EDITED" signal) — the baseline may be stale.
  - If the baseline file is missing for a tracked ticket:
    raise ``ACParseDriftError`` (treat missing baseline as misconfiguration,
    not as a silent skip).

* **Un-tracked ticket** (NOT in ``_manifest.json``):
  - Write a provisional baseline to
    ``storage/ac_parse_baseline/<ticket_key>.provisional.json``.
  - Log a WARNING; do NOT raise — the run continues.

The tolerance and enabled flag are controlled by environment variables
(12-Factor, per ``AC_PARSE_DRIFT_GUARD_ENABLED`` / ``AC_PARSE_DRIFT_TOLERANCE``
in ``backend/config.py``). Default: enabled, tolerance = ±2 steps.

Components
----------
``ACParseBaselineStore``
    Low-level read/write of ``storage/ac_parse_baseline/*.json`` and
    ``_manifest.json``.

``ACParseDriftGuard``
    High-level assertion logic; wires into ``ac_parser.py`` post-Stage-2.

``ACParseDriftError``
    Runtime exception raised on drift; caught by ``ac_parser_node`` which
    sets ``state.failure_type = "AC_PARSE_DRIFT"`` and terminates.

``ACParseDriftResult``
    Dataclass returned by ``ACParseDriftGuard.assert_drift()`` when the
    run is NOT terminated (i.e., for un-tracked tickets that get a
    provisional baseline).  Callers can inspect ``provisioned`` flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (12-Factor — read at import time, overridable via env)
# ---------------------------------------------------------------------------
_BASELINE_DIR = Path(
    os.environ.get("AC_PARSE_BASELINE_DIR", "storage/ac_parse_baseline")
)
_GUARD_ENABLED: bool = os.environ.get("AC_PARSE_DRIFT_GUARD_ENABLED", "true").lower() not in (
    "false",
    "0",
    "no",
    "off",
)
_DRIFT_TOLERANCE: int = int(os.environ.get("AC_PARSE_DRIFT_TOLERANCE", "2"))
_MANIFEST_FILENAME = "_manifest.json"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ACParseDriftError(Exception):
    """
    Raised when a tracked ticket's compiled step count deviates from baseline
    by more than ``AC_PARSE_DRIFT_TOLERANCE`` (default: ±2).

    Attributes
    ----------
    ticket_key : str
    baseline_step_count : int
    current_step_count : int
    delta : int
    """

    def __init__(
        self,
        ticket_key: str,
        baseline_step_count: int,
        current_step_count: int,
    ) -> None:
        self.ticket_key = ticket_key
        self.baseline_step_count = baseline_step_count
        self.current_step_count = current_step_count
        self.delta = abs(current_step_count - baseline_step_count)
        super().__init__(
            f"AC_PARSE_DRIFT: ticket={ticket_key} baseline={baseline_step_count} "
            f"current={current_step_count} delta={self.delta} tolerance={_DRIFT_TOLERANCE}"
        )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BaselineRecord:
    """Content of a ``storage/ac_parse_baseline/<ticket_key>.json`` file."""

    ticket_key: str
    step_count: int
    content_hash: str
    captured_at: str  # ISO-8601
    captured_from: str = ""
    provisional: bool = False

    def to_dict(self) -> dict:
        return {
            "ticket_key": self.ticket_key,
            "step_count": self.step_count,
            "content_hash": self.content_hash,
            "captured_at": self.captured_at,
            "captured_from": self.captured_from,
            "provisional": self.provisional,
        }

    @staticmethod
    def from_dict(data: dict) -> "BaselineRecord":
        return BaselineRecord(
            ticket_key=data["ticket_key"],
            step_count=data["step_count"],
            content_hash=data["content_hash"],
            captured_at=data.get("captured_at", ""),
            captured_from=data.get("captured_from", ""),
            provisional=data.get("provisional", False),
        )


@dataclass
class ACParseDriftResult:
    """
    Returned by ``ACParseDriftGuard.assert_drift()`` when the run is NOT
    terminated.

    ``provisioned=True`` means an un-tracked ticket just got a provisional baseline.
    ``drift_detected=False`` means a tracked ticket passed within tolerance.
    ``skipped=True`` means the guard was disabled or no baseline directory exists.
    """

    ticket_key: str
    baseline_step_count: int | None = None
    current_step_count: int = 0
    delta: int | None = None
    provisioned: bool = False
    drift_detected: bool = False
    skipped: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# ACParseBaselineStore
# ---------------------------------------------------------------------------


class ACParseBaselineStore:
    """
    Low-level persistence for per-ticket baselines.

    All paths are resolved relative to ``baseline_dir`` (default:
    ``storage/ac_parse_baseline/``).
    """

    def __init__(self, baseline_dir: Path | str | None = None) -> None:
        self._dir = Path(baseline_dir) if baseline_dir else _BASELINE_DIR
        self._manifest_path = self._dir / _MANIFEST_FILENAME

    # ------------------------------------------------------------------
    # Directory / manifest helpers
    # ------------------------------------------------------------------

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_manifest(self) -> dict[str, dict]:
        """
        Return the manifest dict (maps ``ticket_key → metadata``).
        Returns an empty dict if the manifest file does not exist.
        """
        if not self._manifest_path.exists():
            return {}
        try:
            return json.loads(self._manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ACParseBaselineStore: failed to read manifest: %s", exc)
            return {}

    def is_tracked(self, ticket_key: str) -> bool:
        """Return True if ``ticket_key`` appears in ``_manifest.json``."""
        return ticket_key in self.load_manifest()

    def save_manifest(self, manifest: dict[str, dict]) -> None:
        self.ensure_dir()
        self._manifest_path.write_text(json.dumps(manifest, indent=2))

    def add_to_manifest(self, ticket_key: str, metadata: dict | None = None) -> None:
        manifest = self.load_manifest()
        manifest[ticket_key] = metadata or {"added_at": _now_iso()}
        self.save_manifest(manifest)

    # ------------------------------------------------------------------
    # Baseline record I/O
    # ------------------------------------------------------------------

    def _baseline_path(self, ticket_key: str, provisional: bool = False) -> Path:
        suffix = ".provisional.json" if provisional else ".json"
        return self._dir / f"{ticket_key}{suffix}"

    def load(self, ticket_key: str) -> BaselineRecord | None:
        """
        Load the baseline for ``ticket_key``.
        Returns ``None`` if no baseline file exists.
        """
        path = self._baseline_path(ticket_key)
        if not path.exists():
            return None
        try:
            return BaselineRecord.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning(
                "ACParseBaselineStore: failed to load baseline for %s: %s",
                ticket_key,
                exc,
            )
            return None

    def save(self, record: BaselineRecord) -> None:
        self.ensure_dir()
        path = self._baseline_path(record.ticket_key, provisional=record.provisional)
        path.write_text(json.dumps(record.to_dict(), indent=2))
        logger.debug(
            "ACParseBaselineStore: saved baseline for %s (steps=%d, provisional=%s)",
            record.ticket_key,
            record.step_count,
            record.provisional,
        )

    def validate_manifest_integrity(self) -> list[str]:
        """
        Return a list of tracked ticket keys whose baseline file is missing.
        An empty list means manifest integrity is confirmed.
        """
        manifest = self.load_manifest()
        missing = [
            key
            for key in manifest
            if not self._baseline_path(key).exists()
        ]
        return missing


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _content_hash(raw_ac: str) -> str:
    """Return SHA-256 hex digest of ``raw_ac`` (UTF-8 encoded)."""
    return hashlib.sha256(raw_ac.encode("utf-8", errors="replace")).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# ACParseDriftGuard
# ---------------------------------------------------------------------------


class ACParseDriftGuard:
    """
    High-level drift assertion gate.

    Injected into ``ac_parser.py`` immediately after Stage-2 compilation
    (around line 1382–1386, after ``compiled_plan = await _stage_2_compile(...)``).

    Usage::

        from backend.engine.ac_parse_drift import ACParseDriftGuard, ACParseDriftError

        guard = ACParseDriftGuard()
        try:
            result = guard.assert_drift(
                ticket_key=ticket_id,
                current_step_count=len(compiled_plan.steps),
                raw_ac=raw_ac,
            )
        except ACParseDriftError:
            raise  # ac_parser_node catches this and sets failure_type=AC_PARSE_DRIFT

    Parameters
    ----------
    baseline_dir :
        Override the baseline directory (useful for testing).
    enabled :
        Override the ``AC_PARSE_DRIFT_GUARD_ENABLED`` env var.
    tolerance :
        Override the ``AC_PARSE_DRIFT_TOLERANCE`` env var.
    """

    def __init__(
        self,
        baseline_dir: Path | str | None = None,
        enabled: bool | None = None,
        tolerance: int | None = None,
    ) -> None:
        self._store = ACParseBaselineStore(baseline_dir)
        self._enabled = _GUARD_ENABLED if enabled is None else enabled
        self._tolerance = _DRIFT_TOLERANCE if tolerance is None else tolerance

    def assert_drift(
        self,
        ticket_key: str,
        current_step_count: int,
        raw_ac: str,
        run_id: str = "",
    ) -> ACParseDriftResult:
        """
        Assert that ``current_step_count`` does not deviate from the stored
        baseline by more than ``tolerance`` steps.

        Raises
        ------
        ACParseDriftError
            When the ticket is tracked and drift > tolerance (or when its
            baseline file is missing — misconfiguration).

        Returns
        -------
        ACParseDriftResult
            For un-tracked tickets (provisional baseline written) and for
            passes within tolerance.
        """
        if not self._enabled:
            return ACParseDriftResult(
                ticket_key=ticket_key,
                current_step_count=current_step_count,
                skipped=True,
                message="guard disabled via AC_PARSE_DRIFT_GUARD_ENABLED=false",
            )

        if not self._store._dir.exists():
            # Baseline directory not yet created — guard cannot run.
            logger.debug(
                "[%s] T3-d drift guard: baseline dir '%s' does not exist — skip",
                run_id,
                self._store._dir,
            )
            return ACParseDriftResult(
                ticket_key=ticket_key,
                current_step_count=current_step_count,
                skipped=True,
                message=f"baseline_dir '{self._store._dir}' not found",
            )

        is_tracked = self._store.is_tracked(ticket_key)
        current_hash = _content_hash(raw_ac)

        if is_tracked:
            return self._assert_tracked(ticket_key, current_step_count, current_hash, run_id)
        else:
            return self._handle_untracked(ticket_key, current_step_count, current_hash, run_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_tracked(
        self,
        ticket_key: str,
        current_step_count: int,
        current_hash: str,
        run_id: str,
    ) -> ACParseDriftResult:
        record = self._store.load(ticket_key)

        if record is None:
            # Tracked ticket but no baseline file — misconfiguration.
            logger.error(
                "[%s] T3-d drift guard: tracked ticket '%s' has no baseline file — "
                "run populate_ac_parse_baseline.py to fix",
                run_id,
                ticket_key,
            )
            raise ACParseDriftError(
                ticket_key=ticket_key,
                baseline_step_count=0,
                current_step_count=current_step_count,
            )

        delta = abs(current_step_count - record.step_count)

        # Content-hash change detection ("AC EDITED" signal)
        if current_hash != record.content_hash:
            logger.warning(
                "[%s] T3-d drift guard: ticket=%s AC content has changed since baseline "
                "(baseline_hash=%s…, current_hash=%s…). Baseline may be stale. "
                "Re-run populate_ac_parse_baseline.py if this is an intentional edit.",
                run_id,
                ticket_key,
                record.content_hash[:12],
                current_hash[:12],
            )

        if delta > self._tolerance:
            logger.error(
                "[%s] T3-d drift guard: AC_PARSE_DRIFT ticket=%s baseline=%d current=%d delta=%d > tolerance=%d",
                run_id,
                ticket_key,
                record.step_count,
                current_step_count,
                delta,
                self._tolerance,
            )
            raise ACParseDriftError(
                ticket_key=ticket_key,
                baseline_step_count=record.step_count,
                current_step_count=current_step_count,
            )

        logger.info(
            "[%s] T3-d drift guard: PASS ticket=%s baseline=%d current=%d delta=%d (tolerance=%d)",
            run_id,
            ticket_key,
            record.step_count,
            current_step_count,
            delta,
            self._tolerance,
        )
        return ACParseDriftResult(
            ticket_key=ticket_key,
            baseline_step_count=record.step_count,
            current_step_count=current_step_count,
            delta=delta,
            drift_detected=False,
        )

    def _handle_untracked(
        self,
        ticket_key: str,
        current_step_count: int,
        current_hash: str,
        run_id: str,
    ) -> ACParseDriftResult:
        """Write a provisional baseline and WARN. The run continues."""
        logger.warning(
            "[%s] T3-d drift guard: ticket='%s' is NOT tracked — writing provisional baseline "
            "(step_count=%d). Promote via populate_ac_parse_baseline.py --promote %s.",
            run_id,
            ticket_key,
            current_step_count,
            ticket_key,
        )
        record = BaselineRecord(
            ticket_key=ticket_key,
            step_count=current_step_count,
            content_hash=current_hash,
            captured_at=_now_iso(),
            captured_from="ac_parser.runtime.provisional",
            provisional=True,
        )
        try:
            self._store.save(record)
        except OSError as exc:
            logger.warning(
                "[%s] T3-d drift guard: could not write provisional baseline for '%s': %s",
                run_id,
                ticket_key,
                exc,
            )

        return ACParseDriftResult(
            ticket_key=ticket_key,
            baseline_step_count=None,
            current_step_count=current_step_count,
            provisioned=True,
            drift_detected=False,
            message=f"provisional baseline written for un-tracked ticket {ticket_key}",
        )
