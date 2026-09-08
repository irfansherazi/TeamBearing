"""
vQA — Async Suite Scheduler (Phase 7C)
=========================================
Module: backend/engine/scheduler.py

Background scheduler that checks enabled test suites for cron-matched
schedules and triggers batch execution when due.

Architecture
------------
Uses pure asyncio (no Celery, no Redis, no APScheduler):
  1. Runs as a single ``asyncio.Task`` started from FastAPI lifespan
  2. Wakes every 60s to check ``suite_store.get_scheduled_suites()``
  3. For each suite whose cron matches the current minute, triggers
     ``POST /suites/{suite_id}/run`` internally
  4. Records last-run time to prevent duplicate triggers within the
     same minute

Cron parsing uses ``croniter`` (pip install croniter) if available,
otherwise falls back to a simple minute-level cron matcher.

Usage
-----
    from backend.engine.scheduler import start_scheduler, stop_scheduler

    # In FastAPI lifespan startup:
    scheduler_task = await start_scheduler()

    # In lifespan shutdown:
    await stop_scheduler(scheduler_task)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Track last trigger time per suite to prevent duplicate fires
_last_triggered: dict[str, str] = {}

# The running scheduler task (set by start_scheduler)
_scheduler_task: asyncio.Task | None = None


def _cron_matches_now(cron_expr: str) -> bool:
    """
    Check if a cron expression matches the current UTC minute.

    Supports standard 5-field cron: minute hour day-of-month month day-of-week

    Uses croniter if available, otherwise falls back to simple parsing.

    Parameters
    ----------
    cron_expr : str
        Standard cron expression (e.g. "0 6 * * 1-5").

    Returns
    -------
    bool
        True if the cron matches the current UTC minute.
    """
    if not cron_expr or not cron_expr.strip():
        return False

    now = datetime.now(timezone.utc)

    try:
        # Try croniter first (most accurate)
        from croniter import croniter

        cron = croniter(cron_expr, now)
        prev = cron.get_prev(datetime)
        # Match if the previous fire time was within the last 60 seconds
        diff = (now - prev.replace(tzinfo=timezone.utc)).total_seconds()
        return 0 <= diff < 60
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Cron parse error for '%s': %s", cron_expr, e)
        return False

    # Fallback: simple 5-field cron parser
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        minute, hour, dom, month, dow = parts

        def _matches(field: str, value: int, max_val: int) -> bool:
            if field == "*":
                return True
            for part in field.split(","):
                if "-" in part:
                    lo, hi = part.split("-", 1)
                    if int(lo) <= value <= int(hi):
                        return True
                elif "/" in part:
                    base, step = part.split("/", 1)
                    base_val = 0 if base == "*" else int(base)
                    if (value - base_val) % int(step) == 0:
                        return True
                elif int(part) == value:
                    return True
            return False

        return (
            _matches(minute, now.minute, 59)
            and _matches(hour, now.hour, 23)
            and _matches(dom, now.day, 31)
            and _matches(month, now.month, 12)
            and _matches(dow, now.weekday(), 6)  # 0=Monday in Python
        )
    except Exception as e:
        logger.warning("Fallback cron parse error for '%s': %s", cron_expr, e)
        return False


async def _trigger_suite_run(suite: dict[str, Any]) -> None:
    """
    Trigger a suite run via the internal API.

    Instead of making an HTTP call to ourselves, we import the suite
    runner directly to avoid network overhead.
    """
    suite_id = suite.get("id", "")
    suite_name = suite.get("name", "")

    try:
        import uuid

        from backend.api.routes import (
            ExecuteRequest,
            _batch_registry,
            _execute_run,
            _run_states,
        )
        from backend.storage.test_suites import suite_store

        tickets = suite.get("tickets", [])
        if not tickets:
            logger.warning("[scheduler] Suite '%s' has no tickets — skipping", suite_name)
            return

        batch_id = f"sched-{suite_id}-{uuid.uuid4().hex[:6]}"
        _batch_registry[batch_id] = []

        from backend.config import settings

        for ticket_config in tickets:
            run_id = f"run-{uuid.uuid4().hex[:8]}"
            _batch_registry[batch_id].append(run_id)
            _run_states[run_id] = {"status": "pending", "state": {}}

            req = ExecuteRequest(
                jira_ticket_id=ticket_config.get("jira_ticket_id", ""),
                role=ticket_config.get("role", "account_executive"),
                target_url=settings.target_url,
                mode=settings.vqa_mode,
            )
            asyncio.create_task(_execute_run(run_id, req))

        suite_store.record_run(suite_id, batch_id, "running")
        logger.info(
            "[scheduler] 📅 Triggered suite '%s' — batch_id=%s, %d tickets",
            suite_name,
            batch_id,
            len(tickets),
        )

    except Exception as e:
        logger.error("[scheduler] Failed to trigger suite '%s': %s", suite_name, e)


async def _scheduler_loop() -> None:
    """
    Main scheduler loop — runs every 60 seconds.

    Checks all scheduled suites and triggers those whose cron matches.
    """
    logger.info("[scheduler] ✅ Scheduler started — checking suites every 60s")

    while True:
        try:
            await asyncio.sleep(60)

            from backend.storage.test_suites import suite_store

            suites = suite_store.get_scheduled_suites()

            if not suites:
                continue

            now_key = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            for suite in suites:
                suite_id = suite.get("id", "")
                cron = suite.get("schedule_cron", "")

                # Skip if already triggered this minute
                if _last_triggered.get(suite_id) == now_key:
                    continue

                if _cron_matches_now(cron):
                    _last_triggered[suite_id] = now_key
                    await _trigger_suite_run(suite)

        except asyncio.CancelledError:
            logger.info("[scheduler] Scheduler shutting down")
            break
        except Exception as e:
            logger.error("[scheduler] Scheduler loop error: %s", e)
            # Don't crash the scheduler on transient errors
            await asyncio.sleep(5)


async def start_scheduler() -> asyncio.Task:
    """Start the background scheduler task."""
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    return _scheduler_task


async def stop_scheduler(task: asyncio.Task | None = None) -> None:
    """Cancel the scheduler task gracefully."""
    t = task or _scheduler_task
    if t and not t.done():
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    logger.info("[scheduler] Scheduler stopped")
