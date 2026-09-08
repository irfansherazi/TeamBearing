"""
vQA — Replay Engine
====================
Module: backend/engine/replay_engine.py

Deterministic replay of accepted test action sequences.

When an accepted test is found for a ticket+AC pair, the ReplayEngine
dispatches its stored actions through the existing Playwright executor
helpers, bypassing the LLM planner entirely.  This produces faster,
cheaper, and more consistent runs for validated test paths.

Architecture
------------
The ReplayEngine is invoked by the ``replay_check_node`` LangGraph node,
which sits between ``login`` and ``planner`` in the graph:

    login ─► replay_check ─► planner  (no accepted test → normal AI run)
                          └─► replay_executor ─► reporter  (accepted test found)

Design Principles
-----------------
1. **Transparent fallback**: if ANY step in the replay fails, the engine
   falls back to the normal AI-driven run from the beginning.  Users
   never get a stuck run from a stale replay.

2. **Full audit trail**: replay steps are recorded in
   ``detailed_execution_log`` with ``replay_source: "accepted_test"``,
   so reports are identical in structure to AI-driven runs.

3. **Settings-guarded**: the feature is disabled when
   ``settings.enable_smart_replay=False`` (e.g., CI environments that
   always want fresh AI runs).

4. **Read-only**: the engine reads from AcceptedTestStore but never
   writes to it.  Acceptance is always an explicit human action via
   POST /runs/{run_id}/accept.

Author: vQA Build Agent (TASK-031 Phase 3)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.browser.context import get_manager
from backend.config import settings
from backend.engine.executor import _dispatch_action as dispatch_action
from backend.storage.accepted_test_store import get_accepted_test_store

logger = logging.getLogger(__name__)


class ReplayEngine:
    """
    Executes an accepted action sequence through the Playwright executor.

    Responsibilities
    ----------------
    - Load the accepted record from AcceptedTestStore.
    - Dispatch each ``replay_action`` through the existing low-level
      executor helpers (``dispatch_action``).
    - Record results in the same format as AI-driven runs.
    - On any step failure, emit ``replay_failed=True`` so the graph
      falls back to the AI planner.

    Usage
    -----
    >>> engine = ReplayEngine(run_id="run-abc123")
    >>> result = await engine.replay(state)
    >>> if result["replay_succeeded"]:
    ...     # Route to reporter
    ... else:
    ...     # Fallback to planner
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._logger = logging.LoggerAdapter(logger, {"run_id": run_id})

    async def replay(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a stored action sequence from the AcceptedTestStore.

        Args
        ----
        state : dict
            Current VQAState. Must contain ``jira_ticket`` with
            ``ticket_id`` and ``acceptance_criteria_steps``.

        Returns
        -------
        dict
            Partial state update with:
            - ``replay_succeeded`` (bool): True if all steps passed.
            - ``replay_failed`` (bool): True if any step failed.
            - ``detailed_execution_log``: Updated execution log.
            - ``_next_node``: "reporter" or "planner".
        """
        ticket = state.get("jira_ticket", {})
        ticket_id = ticket.get("ticket_id", "")
        ac_steps = ticket.get("acceptance_criteria_steps", [])

        # Guard: feature must be enabled
        if not settings.enable_smart_replay:
            self._logger.info(
                "[%s] Smart replay disabled (ENABLE_SMART_REPLAY=False) — routing to planner",
                self.run_id,
            )
            return {
                "replay_succeeded": False,
                "replay_failed": False,
                "_next_node": "planner",
            }

        # Load the accepted record
        store = get_accepted_test_store()
        record = store.load(ticket_id=ticket_id, ac_steps=ac_steps)

        if record is None:
            self._logger.info(
                "[%s] No accepted test for ticket=%s — routing to planner",
                self.run_id,
                ticket_id,
            )
            return {
                "replay_succeeded": False,
                "replay_failed": False,
                "_next_node": "planner",
            }

        replay_actions = record.get("replay_actions", [])
        if not replay_actions:
            self._logger.warning(
                "[%s] Accepted record for %s has no replay_actions — routing to planner",
                self.run_id,
                ticket_id,
            )
            return {
                "replay_succeeded": False,
                "replay_failed": False,
                "_next_node": "planner",
            }

        self._logger.info(
            "[%s] Starting Smart Replay for ticket=%s: %d actions (accepted run_id=%s)",
            self.run_id,
            ticket_id,
            len(replay_actions),
            record.get("run_id", "?"),
        )

        # Dispatch actions
        execution_log = list(state.get("detailed_execution_log", []))
        succeeded_count = 0
        failed_step: dict | None = None

        for i, action in enumerate(replay_actions):
            step_result = await self._dispatch_replay_action(
                action=action,
                step_index=len(execution_log) + i,
                state=state,
            )
            execution_log.append(step_result)

            if not step_result["success"]:
                failed_step = step_result
                self._logger.warning(
                    "[%s] Replay step %d/%d FAILED (action_type=%s): %s",
                    self.run_id,
                    i + 1,
                    len(replay_actions),
                    action.get("action_type", "?"),
                    step_result.get("error", "unknown"),
                )
                break
            else:
                succeeded_count += 1
                self._logger.debug(
                    "[%s] Replay step %d/%d OK (action_type=%s)",
                    self.run_id,
                    i + 1,
                    len(replay_actions),
                    action.get("action_type", "?"),
                )

        all_passed = failed_step is None

        if all_passed:
            self._logger.info(
                "[%s] ✓ Smart Replay COMPLETE: all %d actions succeeded for ticket=%s — routing to reporter",
                self.run_id,
                len(replay_actions),
                ticket_id,
            )
            return {
                "replay_succeeded": True,
                "replay_failed": False,
                "detailed_execution_log": execution_log,
                "ac_steps_completed": list(range(len(ac_steps))),  # All steps done
                "_next_node": "reporter",
            }
        else:
            self._logger.warning(
                "[%s] Smart Replay FAILED at step %d — falling back to AI planner for ticket=%s",
                self.run_id,
                succeeded_count + 1,
                ticket_id,
            )
            return {
                "replay_succeeded": False,
                "replay_failed": True,
                "detailed_execution_log": [],  # Clear partial log for clean AI run
                "_next_node": "planner",
                "last_error": (
                    f"Smart Replay failed at step {succeeded_count + 1}: "
                    f"{failed_step.get('error', 'unknown') if failed_step else ''}"
                ),
            }

    async def _dispatch_replay_action(
        self,
        action: dict[str, Any],
        step_index: int,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Dispatch a single replay action through the Playwright executor.

        Uses the existing ``dispatch_action`` helper from the executor module.
        On success, returns a log entry with ``success=True``.
        On failure, returns a log entry with ``success=False`` and ``error``.

        Args
        ----
        action : dict
            A replay action dict from ``AcceptedTestStore`` (must have
            ``action_payload`` and ``action_type``).
        step_index : int
            Sequential index for the log entry.
        state : dict
            Current VQAState (used to access run_id and browser manager).

        Returns
        -------
        dict
            Log entry with at minimum: step_index, action_type, success,
            timestamp, replay_source.
        """
        action_payload = action.get("action_payload", {})
        action_type = action.get("action_type", action_payload.get("action", "unknown"))

        timestamp = datetime.now(UTC).isoformat()

        try:
            manager = get_manager(self.run_id)
            if manager is None:
                return self._failure_entry(
                    step_index=step_index,
                    action_type=action_type,
                    action_payload=action_payload,
                    error="BrowserManager not found — browser may not be running",
                    timestamp=timestamp,
                )

            page = manager.page
            if page is None or page.is_closed():
                return self._failure_entry(
                    step_index=step_index,
                    action_type=action_type,
                    action_payload=action_payload,
                    error="Browser page is closed",
                    timestamp=timestamp,
                )

            # Dispatch through the existing executor helper
            result = await dispatch_action(
                page=page,
                action=action_payload,
                run_id=self.run_id,
            )

            success = result.get("success", False)
            return {
                "step_index": step_index,
                "action_type": action_type,
                "action_payload": action_payload,
                "success": success,
                "timestamp": timestamp,
                "replay_source": "accepted_test",
                "locator_strategy": action.get("locator_strategy", ""),
                "locator_value": action.get("locator_value", ""),
                "error": result.get("error", "") if not success else "",
            }

        except Exception as exc:
            return self._failure_entry(
                step_index=step_index,
                action_type=action_type,
                action_payload=action_payload,
                error=str(exc),
                timestamp=timestamp,
            )

    @staticmethod
    def _failure_entry(
        step_index: int,
        action_type: str,
        action_payload: dict,
        error: str,
        timestamp: str,
    ) -> dict[str, Any]:
        """Create a failed step log entry."""
        return {
            "step_index": step_index,
            "action_type": action_type,
            "action_payload": action_payload,
            "success": False,
            "timestamp": timestamp,
            "replay_source": "accepted_test",
            "locator_strategy": "",
            "locator_value": "",
            "error": error,
        }
