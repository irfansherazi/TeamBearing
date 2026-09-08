"""
vQA — Circuit Breaker Telemetry
==================================
Module: backend/engine/cb_telemetry.py

MVE-001: Structured telemetry emitter for circuit breaker events.

Fires when any CB trips (amnesic loop, per-locator, AC-level cap,
global iteration, verifier NOT_YET). Writes structured JSON to both
the Python logger AND a JSONL file for offline analysis.

The 30-day data accumulation clock starts when this module is deployed.
This data blocks re-evaluation of DR-006 and DR-010.

Constraints
-----------
- Non-blocking: fire-and-forget with error suppression on disk write
- Must not add more than 5ms to the evaluator hot path
- Telemetry file: .agent-logs/telemetry/cb_events.jsonl

Usage
-----
    from backend.engine.cb_telemetry import emit_cb_telemetry

    emit_cb_telemetry(
        run_id=run_id,
        cb_type="amnesic_loop",
        cb_reason="3 stagnant actions",
        iteration_at_fire=15,
        action_at_fire="click",
        ac_step_index=2,
        wall_clock_elapsed_s=120.5,
        cost_usd_at_fire=0.45,
    )
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Default telemetry output directory (project root / .agent-logs / telemetry)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_TELEMETRY_DIR = str(_PROJECT_ROOT / ".agent-logs" / "telemetry")


def emit_cb_telemetry(
    *,
    run_id: str,
    cb_type: str,
    cb_reason: str,
    iteration_at_fire: int,
    action_at_fire: str,
    ac_step_index: int,
    wall_clock_elapsed_s: float,
    cost_usd_at_fire: float,
) -> None:
    """
    Emit a structured telemetry event when a circuit breaker trips.

    Writes to both the Python logger (structured log) and the JSONL
    telemetry file. Disk write failures are silently suppressed.

    Parameters
    ----------
    run_id : str
        The unique run identifier.
    cb_type : str
        CB classification: "amnesic_loop" | "per_locator" | "ac_level_cap"
        | "global_iter" | "verifier_not_yet"
    cb_reason : str
        Human-readable explanation of why the CB tripped.
    iteration_at_fire : int
        Which planner iteration the CB fired at.
    action_at_fire : str
        What action was being attempted when the CB fired.
    ac_step_index : int
        Which AC step was being executed.
    wall_clock_elapsed_s : float
        Seconds elapsed since run_started_at.
    cost_usd_at_fire : float
        RunMetrics.estimated_cost_usd at time of CB fire.
    """
    event = {
        "event": "CIRCUIT_BREAKER_TRIPPED",
        "run_id": run_id,
        "cb_type": cb_type,
        "cb_reason": cb_reason,
        "iteration_at_fire": iteration_at_fire,
        "action_at_fire": action_at_fire,
        "ac_step_index": ac_step_index,
        "wall_clock_elapsed_s": round(wall_clock_elapsed_s, 2),
        "cost_usd_at_fire": round(cost_usd_at_fire, 6),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Emit to structured logger
    logger.warning(
        "[%s] CIRCUIT_BREAKER_TRIPPED: cb_type=%s, reason=%s, iteration=%d, "
        "ac_step=%d, wall_clock=%.1fs, cost=$%.4f",
        run_id,
        cb_type,
        cb_reason,
        iteration_at_fire,
        ac_step_index,
        wall_clock_elapsed_s,
        cost_usd_at_fire,
    )

    # Emit to JSONL file (fire-and-forget)
    try:
        telemetry_dir = Path(_TELEMETRY_DIR)
        telemetry_dir.mkdir(parents=True, exist_ok=True)

        events_file = telemetry_dir / "cb_events.jsonl"
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as exc:
        # Non-blocking: suppress disk write errors
        logger.debug("CB telemetry disk write failed (suppressed): %s", exc)
