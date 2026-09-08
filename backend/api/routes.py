"""
vQA — FastAPI Route Handlers
==============================
Module: backend/api/routes.py

Defines all REST and WebSocket endpoint handlers for the vQA API.

Endpoints
---------
    POST   /execute             — Start a single-ticket test run
    POST   /execute-batch       — Start a batch of test runs (CI/CD)
    GET    /status/{run_id}     — Get run status + artifacts
    GET    /batch-status/{id}   — Get batch status
    GET    /health              — Health check (Bedrock, S3, Jira)
    WS     /ws/{run_id}         — Real-time execution log stream

Architecture Context
--------------------
The ``/execute`` endpoint creates an initial ``VQAState``, compiles
the LangGraph, and runs it in a background task (``asyncio.create_task``).
The response returns immediately with a ``run_id`` and WebSocket URL.

The React dashboard connects to ``/ws/{run_id}`` for real-time log
updates.  Each time the executor appends an ``ExecutionStep`` to the
state, a ``WSStepMessage`` is broadcast to all connected WebSocket
clients for that run.

Run State Storage
-----------------
In-progress and completed run states are stored in an in-memory dict
(``_run_states``).  This is sufficient for single-container deployments.
For horizontal scaling, this would be replaced with Redis or a database.

Dependencies
------------
  - ``fastapi`` — APIRouter, WebSocket, BackgroundTasks
  - ``backend/engine/graph.py`` — build_graph()
  - ``backend/engine/state.py`` — make_initial_state()
  - ``backend/api/schemas.py``  — request/response models

See Also
--------
  - ``backend/main.py``        — mounts this router
  - ``backend/config.py``      — settings
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from langgraph.checkpoint.memory import MemorySaver

from backend.api.auth_middleware import verify_api_key
from backend.api.schemas import (
    ArtifactsInfo,
    BatchExecuteRequest,
    BatchExecuteResponse,
    BatchRunItem,
    BatchStatusResponse,
    CaptureClickRequest,
    CaptureClickResponse,
    CredentialCheckResponse,
    ExecuteRequest,
    ExecuteResponse,
    GhostCredentialsRequest,
    GhostCredentialsResponse,
    HealthCheck,
    HitlDialogResponseRequest,
    HumanTakeoverDoneRequest,
    InteractRequest,
    InteractResponse,
    PersonaCredentialsRequest,
    PersonaCredentialsResponse,
    PreviewStepsRequest,
    PreviewStepsResponse,
    ResumeRequest,
    StatusResponse,
    SuiteCreate,
    SuiteListResponse,
    SuiteResponse,
    SuiteTicketItem,
    SuiteUpdate,
    SyncACRequest,
    SyncACResponse,
    TeachRequest,
    TeachResponse,
    WSAcProgressMessage,
    WSAcStep,
    WSCopilotReadyMessage,
    WSHitlActionRecordedMessage,
    WSHitlDialogMessage,
    WSHitlScreenshotMessage,
    WSHumanTakeoverMessage,
    WSStepMessage,
    WSTerminalLogMessage,
    WSTerminalMessage,
    WSThinkingMessage,
    WSTriageMessage,
    CodegenStartRequest,
    CodegenStartResponse,
)
from backend.browser.context import BrowserManager, get_manager
from backend.browser.screenshot import capture_screenshot_b64
from backend.browser.vnc_builder import vnc_builder
from backend.config import settings
from backend.engine.graph import build_graph
from backend.engine.human_takeover import (
    complete_takeover,
    get_takeover_step,
    is_waiting,
    skip_takeover,
)
from backend.engine.linear_bridge import LinearRunResult, run_linear_pipeline  # TASK-106
from backend.engine.persona_switch_node import has_ghost_credentials, set_ghost_credentials, set_persona_credentials
from backend.engine.preflight_check import PreflightFailure, run_preflight_checks
from backend.engine.state import VQAState, make_initial_state
from backend.jira.client import JiraClientError, fetch_board_tickets, fetch_ticket_context
from backend.storage.playwright_registry import PlaywrightRegistry

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# Separate router for WebSocket endpoints — no auth dependency.
# FastAPI's Security(APIKeyHeader) requires an HTTP Request object which
# WebSocket connections don't provide.  Applying the auth dependency to
# WebSocket routes causes a silent TypeError crash that prevents ALL
# WebSocket connections from being accepted.
ws_router = APIRouter()


# ---------------------------------------------------------------------------
# Run state storage (pluggable backend)
# ---------------------------------------------------------------------------
# The state store is resolved from settings.state_store:
#   "memory" (default) → InMemoryStateStore (zero-config, single-process)
#   "redis"            → RedisStateStore (multi-container, persistence)
#
# InMemoryStateStore supports __contains__, __getitem__, __setitem__
# for backward compatibility with existing synchronous access patterns.

from backend.store import get_state_store

_run_states = get_state_store()

# Maps run_id → list of connected WebSocket instances
_ws_connections: dict[str, list[WebSocket]] = {}

# Maps batch_id → list of run_ids
_batch_registry: dict[str, list[str]] = {}

# Process lifecycle counters for /health endpoint
import time as _time

_BOOT_TIME = _time.monotonic()
_total_runs_completed: int = 0


# ---------------------------------------------------------------------------
# WebSocket broadcast helpers
# ---------------------------------------------------------------------------


async def _broadcast_step(run_id: str, step: dict) -> None:
    """
    Broadcast an execution step to all WebSocket clients for a run.

    Called by the graph execution callback after each executor step.

    Args
    ----
    run_id : str
        The run to broadcast to.
    step : dict
        ExecutionStep data to send.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    msg = WSStepMessage(
        step_index=step.get("step_index", 0),
        timestamp=step.get("timestamp", ""),
        action_type=step.get("action_type", ""),
        locator=step.get("locator_value", ""),
        success=step.get("success", False),
        screenshot_url=step.get("screenshot_url", ""),
        llm_reasoning=step.get("llm_reasoning", ""),
    )

    msg_json = msg.model_dump_json()

    # Send to all connections, removing any that have disconnected
    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_thinking(run_id: str, text: str, ac_step: int, ac_total: int) -> None:
    """
    Broadcast an agent thinking message before a step executes.
    Frontend uses this to show the live reasoning strip.
    """
    if not text:
        return
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return
    msg = WSThinkingMessage(
        run_id=run_id,
        text=text,
        ac_step=ac_step,
        ac_total=ac_total,
    )
    msg_json = msg.model_dump_json()
    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_human_takeover(
    run_id: str,
    ac_step: str,
    ac_step_index: int,
    error_message: str,
    instructions: str = "",
    novnc_url: str | None = None,
) -> None:
    """
    Broadcast a human_takeover event to all connected WebSocket clients.

    Called directly from human_takeover_node (NOT via state diff) so the
    frontend receives the event BEFORE the node awaits the asyncio.Event.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    # Use provided novnc_url if available, else build it from first connection
    if not novnc_url:
        ws = connections[0]
        novnc_url = vnc_builder.build_url(ws, "interactive")

    msg = WSHumanTakeoverMessage(
        run_id=run_id,
        ac_step=ac_step,
        ac_step_index=ac_step_index,
        error_message=error_message,
        novnc_url=novnc_url,
    )
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)

    logger.info("[%s] Broadcast human_takeover WS event for AC step %d", run_id, ac_step_index + 1)

    # Also send copilot_ready so the CopilotSidebar surfaces the Takeover panel
    await _broadcast_human_takeover_copilot(
        run_id=run_id,
        ac_step=ac_step,
        ac_step_index=ac_step_index,
        error_message=error_message,
        instructions=instructions,
    )


async def _broadcast_hitl_screenshot(run_id: str, data: str) -> None:
    """
    Broadcast a real-time HITL screencast frame (JPEG) to all connected clients.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    msg = WSHitlScreenshotMessage(run_id=run_id, data=data)
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_hitl_action_recorded(run_id: str, action: dict) -> None:
    """
    Broadcast a real-time HITL action echo to all connected clients.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    msg = WSHitlActionRecordedMessage(run_id=run_id, action=action)
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_hitl_dialog(
    run_id: str, message: str, dialog_type: str, default_value: str = ""
) -> None:
    """
    Broadcast an intercepted browser dialog to all connected clients.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    msg = WSHitlDialogMessage(
        run_id=run_id,
        message=message,
        dialog_type=dialog_type,
        default_value=default_value,
    )
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_human_takeover_copilot(
    run_id: str,
    ac_step: str,
    ac_step_index: int,
    error_message: str,
    instructions: str = "",
) -> None:
    """
    Broadcast a copilot_ready event in addition to the legacy human_takeover.

    The copilot_ready message tells the CopilotSidebar to show the
    'Takeover & Resume' panel.  Sent alongside the original message for
    backwards compatibility.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    copilot_msg = WSCopilotReadyMessage(
        run_id=run_id,
        ac_step_index=ac_step_index,
        ac_step_text=ac_step,
        error_message=error_message,
        instructions=instructions or WSCopilotReadyMessage.model_fields["instructions"].default,
    )
    copilot_json = copilot_msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(copilot_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)

    logger.info("[%s] Broadcast copilot_ready WS event for AC step %d", run_id, ac_step_index + 1)


async def _broadcast_ac_progress(run_id: str, steps: list[dict]) -> None:
    """
    Broadcast the full AC step list with current statuses to all WS clients.

    Called on every astream loop tick where AC state changes.  The frontend
    CopilotSidebar replaces its entire step list on each receipt.

    Args
    ----
    run_id : str
        The run to broadcast to.
    steps : list[dict]
        List of step dicts matching WSAcStep fields:
        {index, text, status, error, human_selector}.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        # Buffer the message for late-connecting clients
        try:
            import time

            from backend.api.playwright_routes import _playwright_msg_buffer  # noqa: PLC0415
            msg = WSAcProgressMessage(
                run_id=run_id,
                steps=[WSAcStep(**s) for s in steps],
            )
            _playwright_msg_buffer.setdefault(run_id, []).append(
                {
                    "type": "ac_progress",
                    "run_id": run_id,
                    "steps": [s.model_dump() for s in msg.steps],
                    "_ts": time.monotonic(),
                }
            )
        except Exception as ex:
            logger.warning("[%s] Failed to buffer ac_progress message: %s", run_id, ex)
        return

    msg = WSAcProgressMessage(
        run_id=run_id,
        steps=[WSAcStep(**s) for s in steps],
    )
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


async def _broadcast_terminal_log(run_id: str, line: str, stream: str = "stdout") -> None:
    """
    Broadcast a raw terminal log line to WebSocket clients.
    """
    connections = _ws_connections.get(run_id, [])
    if not connections:
        return

    msg = WSTerminalLogMessage(
        run_id=run_id,
        line=line,
        stream=stream,  # type: ignore
    )
    msg_json = msg.model_dump_json()

    disconnected: list[WebSocket] = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)

    for ws in connections:
        if ws in disconnected:
            connections.remove(ws)


async def _broadcast_terminal(run_id: str, msg: WSTerminalMessage) -> None:
    """
    Broadcast a terminal (completion/failure) message and close connections.

    Args
    ----
    run_id : str
        The run to broadcast to.
    msg : WSTerminalMessage
        The terminal message.
    """
    connections = _ws_connections.pop(run_id, [])
    msg_json = msg.model_dump_json()

    for ws in connections:
        try:
            await ws.send_text(msg_json)
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Graph execution (background task)
# ---------------------------------------------------------------------------


async def _execute_run(run_id: str, initial_state: VQAState) -> None:
    """
    Execute a vQA graph run as a background task.

    Compiles the LangGraph, invokes it with the initial state, and
    updates ``_run_states`` with the result.

    Args
    ----
    run_id : str
        Unique run identifier.
    initial_state : VQAState
        The initial state to pass to the graph.
    """
    _run_states[run_id]["status"] = "running"
    logger.info("[%s] Starting graph execution...", run_id)

    try:
        # ── DR-007: Pre-flight session health check ────────────────────
        try:
            _role = initial_state.get("role_queue", ["account_executive"])[0]
            _base_url = initial_state.get("target_url", settings.target_url)
            # Ghost login: the ghost_login_node handles all authentication using
            # admin credentials — the selected role's stored auth state is irrelevant.
            # Detection has three paths:
            #   1. A GHOST_LOGIN step type in override_ac_steps (structured parser)
            #   2. Ghost credentials pre-populated by the UI before execution starts
            #   3. Plain 'ghost' keyword in the ticket description (mirrors the
            #      preview endpoint's detection at routes.py:1184) — covers tickets
            #      where the structured AC parser didn't emit a GHOST_LOGIN step
            #      but the ticket clearly requires ghost login (e.g., vpromotions
            #      tickets that use the ghost-user flow)
            _override_steps = initial_state.get("override_ac_steps") or []
            _ticket_desc = (initial_state.get("jira_ticket") or {}).get("description", "") or ""
            _has_ghost_step = (
                any(
                    isinstance(s, dict)
                    and s.get("step_type") in ("GHOST_LOGIN", "AUTHENTICATE_AND_GHOST")
                    for s in _override_steps
                )
                or has_ghost_credentials(run_id)
                or "ghost" in _ticket_desc.lower()
            )
            # User-supplied credentials bypass the stored auth state — the login_node
            # uses injected_login_email/password directly, so the role's cached state
            # is irrelevant for this run.
            _has_user_credentials = bool(
                initial_state.get("injected_login_email")
                and initial_state.get("injected_login_password")
            )
            await run_preflight_checks(
                run_id=run_id,
                role=_role,
                base_url=_base_url,
                skip_auth_check=_has_ghost_step or _has_user_credentials,
            )
        except PreflightFailure as pf:
            logger.error("[%s] Pre-flight check FAILED: %s", run_id, pf)
            _run_states[run_id]["status"] = "failed"
            _run_states[run_id]["error"] = f"Preflight: {pf.details}"
            await _broadcast_terminal(
                run_id,
                WSTerminalMessage(
                    type="failed",
                    run_id=run_id,
                    report_url="",
                    video_url="",
                    ac_steps_passed=0,
                    ac_steps_total=0,
                    bugs_found=0,
                ),
            )
            return

        # Build and run the graph with checkpointer for pause/resume state updates
        graph = build_graph(checkpointer=_memory_checkpointer)
        config = {
            "configurable": {"thread_id": run_id},
            # LangGraph counts GRAPH NODE VISITS, not planner iterations.
            "recursion_limit": 3000,
            "max_concurrency": 1,
        }

        # FEAT-114: Register graph for HITL resume-executor when interrupt mode is active.
        if settings.enable_hitl_before_executor:
            _hitl_graphs[run_id] = graph
            logger.info("[%s] HITL mode: graph registered in _hitl_graphs for resume-executor support", run_id)

        # Initialize pause event for this run (Set by default = not paused)
        pause_event = asyncio.Event()
        pause_event.set()
        _pause_events[run_id] = pause_event

        # Use astream with updates mode to get per-node partial state diffs
        final_state: dict = dict(initial_state)
        prev_log_len = 0

        async for event in graph.astream(
            initial_state,
            stream_mode="updates",
            config=config,
        ):
            # ── Pause Check (TASK-067) ──────────────────────────────────
            # If the user clicked Pause, the event is cleared. We block here
            # BEFORE processing the current node's output, effectively
            # suspending the graph between nodes.
            if not pause_event.is_set():
                logger.info("[%s] Graph execution PAUSED — awaiting resume event", run_id)
                _run_states[run_id]["status"] = "paused"
                await pause_event.wait()
                logger.info("[%s] Graph execution RESUMED", run_id)
                _run_states[run_id]["status"] = "running"

                # Check for state updates (e.g. injected steps) provided during pause
                if run_id in _resume_data:
                    updates = _resume_data.pop(run_id)
                    if "override_steps" in updates:
                        new_steps = updates["override_steps"]
                        logger.info("[%s] Injecting %d modified steps into running state", run_id, len(new_steps))

                        # Fetch current jira_ticket from final_state
                        current_ticket = final_state.get("jira_ticket", {}).copy()
                        current_ticket["acceptance_criteria_steps"] = new_steps

                        # Update the graph's internal state so nodes see the new steps
                        await graph.aupdate_state(config, {"jira_ticket": current_ticket})

                        # Synchronize our local tracker
                        final_state["jira_ticket"] = current_ticket

            # In "updates" mode, event is {node_name: partial_state_update}
            for node_name, partial_update in event.items():
                # Merge partial_update into final_state using reducer semantics:
                # list fields (matching LangGraph operator.add) are APPENDED,
                # all other fields are REPLACED.
                if isinstance(partial_update, dict):
                    _LIST_FIELDS = {
                        "detailed_execution_log",
                        "screenshots",
                        "bug_log",
                        "ac_steps_completed",
                        "long_term_memory",
                    }
                    for k, v in partial_update.items():
                        if k in _LIST_FIELDS and isinstance(v, list):
                            existing = final_state.get(k, [])
                            final_state[k] = existing + v
                        else:
                            final_state[k] = v

                    # Broadcast new execution steps via WebSocket
                    new_steps = partial_update.get("detailed_execution_log", [])
                    ac_steps_list = final_state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
                    ac_step_idx = final_state.get("ac_step_index", 0)
                    for step in new_steps:
                        # Broadcast thinking BEFORE step card
                        reasoning = (step.get("llm_reasoning", "") or "").strip()
                        if reasoning:
                            await _broadcast_thinking(
                                run_id=run_id,
                                text=reasoning,
                                ac_step=ac_step_idx + 1,
                                ac_total=len(ac_steps_list),
                            )
                        await _broadcast_step(run_id, step)

                    # ── Broadcast AC step progress for CopilotSidebar ──────
                    # Recompute full step status list on every state update so
                    # the sidebar reflects real-time progress immediately.
                    if ac_steps_list:
                        ac_completed_set = set(final_state.get("ac_steps_completed", []))
                        bug_log = final_state.get("bug_log", [])
                        awaiting_human = final_state.get("awaiting_human_takeover", False)
                        step_statuses = []
                        for i, text in enumerate(ac_steps_list):
                            if i in ac_completed_set:
                                status = "passed"
                            elif i == ac_step_idx:
                                if awaiting_human:
                                    status = "awaiting_human"
                                else:
                                    status = "in_progress"
                            elif i < ac_step_idx:
                                failed = any(b.get("ac_step_index") == i for b in bug_log)
                                status = "failed" if failed else "skipped"
                            else:
                                status = "pending"
                            step_statuses.append(
                                {
                                    "index": i,
                                    "text": text,
                                    "status": status,
                                    "error": "",
                                    "human_selector": "",
                                }
                            )
                        await _broadcast_ac_progress(run_id, step_statuses)

            # Cancel check — user requested early stop, break and generate report
            if run_id in _cancelled_runs:
                logger.info("[%s] Cancellation detected — breaking astream loop", run_id)
                _cancelled_runs.discard(run_id)
                break

        # Run completed successfully
        _run_states[run_id]["status"] = "completed"
        _run_states[run_id]["state"] = final_state

        global _total_runs_completed
        _total_runs_completed += 1
        logger.info("[%s] Graph execution completed", run_id)

        # Determine true pass/fail: all AC steps passed AND no bugs
        ac_steps = final_state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
        ac_passed = final_state.get("ac_steps_completed", [])
        bugs = final_state.get("bug_log", [])
        # Use set-based coverage: operator.add duplication appends out-of-range
        # indices when the verifier routes back to evaluator on the last step,
        # making len(ac_passed) > len(ac_steps) and falsely showing FAILED.
        _ac_passed_set = set(ac_passed)
        all_passed = len(ac_steps) > 0 and all(i in _ac_passed_set for i in range(len(ac_steps))) and len(bugs) == 0

        terminal_type = "completed" if all_passed else "failed"

        # On failure: broadcast triage analysis BEFORE closing the WS
        if not all_passed:
            failure_analysis = final_state.get("failure_analysis") or {}
            if failure_analysis.get("steps"):
                connections = _ws_connections.get(run_id, [])
                triage_msg = WSTriageMessage(
                    run_id=run_id,
                    overall=failure_analysis.get("overall", "unknown"),
                    summary=failure_analysis.get("summary", ""),
                    steps=failure_analysis.get("steps", []),
                    jira_comment=failure_analysis.get("jira_comment", ""),
                )
                triage_json = triage_msg.model_dump_json()
                for ws in connections:
                    try:
                        await ws.send_text(triage_json)
                    except Exception:
                        pass
                logger.info("[%s] Triage message broadcast (%s)", run_id, triage_msg.overall)

        await _broadcast_terminal(
            run_id,
            WSTerminalMessage(
                type=terminal_type,
                run_id=run_id,
                report_url=final_state.get("s3_report_url", ""),
                video_url=final_state.get("s3_video_url", ""),
                ac_steps_passed=len(ac_passed) if isinstance(ac_passed, list) else 0,
                ac_steps_total=len(ac_steps),
                bugs_found=len(bugs),
            ),
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        _run_states[run_id]["status"] = "failed"
        _run_states[run_id]["error"] = error_msg

        # ── Distinguish page-closed / cancelled from genuine errors ───────
        # TargetClosedError and our RuntimeError(page.is_closed) are expected
        # when the user cancels a run or closes the browser window. Log at
        # WARNING (no traceback) to avoid flooding logs with 200-line traces.
        _is_page_closed = any(
            kw in error_msg.lower()
            for kw in (
                "targetclosederror",
                "page is closed",
                "browser has been closed",
                "target page",
                "context was destroyed",
                "run was cancelled",
                "routing to reporter",
            )
        )

        # ── GraphRecursionError: treat as graceful over-budget termination ─
        # LangGraph raises GraphRecursionError when the node-visit ceiling is
        # hit. This is a safety net for pathologically long runs — NOT an
        # application bug. Log at WARNING (no traceback) and surface a clear
        # message to the client so it can be acted on.
        _is_recursion_limit = "graphrecursionerror" in error_msg.lower()

        # ── ENOSPC: disk full — browser cannot create its temp directory ──
        # Playwright raises this when /var/folders or /tmp is out of space.
        # Log at WARNING (no traceback) so the file handler doesn't itself
        # fail and spam "--- Logging error ---" to stderr.
        _is_disk_full = any(
            kw in error_msg.lower()
            for kw in ("enospc", "no space left on device")
        )

        if _is_page_closed:
            logger.warning(
                "[%s] Graph halted cleanly — page/browser closed (cancel or disconnect): %s",
                run_id,
                str(e)[:160],
            )
        elif _is_recursion_limit:
            logger.warning(
                "[%s] Graph halted — recursion limit reached (run exceeded maximum node visits). "
                "Consider reducing max_planner_iterations or the ticket's AC step count: %s",
                run_id,
                str(e)[:160],
            )
        elif _is_disk_full:
            logger.warning(
                "[%s] Graph halted — disk full (ENOSPC): Playwright cannot create browser temp directory. "
                "Free up disk space and retry: %s",
                run_id,
                str(e)[:200],
            )
        else:
            logger.error("[%s] Graph execution failed: %s", run_id, error_msg, exc_info=True)

        # Include partial results in the terminal message so the frontend can
        # show how many steps completed before the early stop.
        _partial_state = final_state if "final_state" in locals() else {}
        _partial_ac = _partial_state.get("ac_steps_completed", [])
        _partial_ac_steps = _partial_state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
        _partial_bugs = _partial_state.get("bug_log", [])

        _user_error = (
            "Disk full — free up space on this machine and retry."
            if _is_disk_full
            else error_msg
        )
        await _broadcast_terminal(
            run_id,
            WSTerminalMessage(
                type="failed",
                run_id=run_id,
                error=_user_error,
                ac_steps_passed=len(_partial_ac) if isinstance(_partial_ac, list) else 0,
                ac_steps_total=len(_partial_ac_steps),
                bugs_found=len(_partial_bugs) if isinstance(_partial_bugs, list) else 0,
            ),
        )

    finally:
        # ── Step 10: Final Cleanup (TASK-067) ─────────────────────────
        # Ensure the BrowserManager is closed and unregistered regardless
        # of whether the run passed, failed, or was cancelled.
        # Idempotent: BrowserManager.close() handles redundant calls safely.
        try:
            from backend.browser.context import get_manager, unregister_manager
            manager = get_manager(run_id)
            if manager.is_active:
                logger.info("[%s] Cleanup: closing active BrowserManager in finally block", run_id)
                await manager.close()
            unregister_manager(run_id)
        except KeyError:
            # Manager never registered (e.g. failed before login_node)
            pass
        except Exception as cleanup_err:
            logger.warning("[%s] Cleanup failed in finally block: %s", run_id, cleanup_err)

        # FEAT-114: Clean up HITL graph registry entry to prevent memory leak.
        _hitl_graphs.pop(run_id, None)

        # AC-ENTRY-3: release the run_id from the owning session so the
        # active_run_ids list stays accurate for teardown / observability.
        _sid = (_run_states.get_sync(run_id) or {}).get("session_id")
        if _sid:
            try:
                from backend.session.manager import get_session_manager as _get_sm
                _get_sm().remove_active_run_id(_sid, run_id)
            except Exception as _sm_err:
                logger.warning("[%s] Session run-id release failed: %s", run_id, _sm_err)


# ---------------------------------------------------------------------------
# Linear pipeline execution (TASK-106) — background task
# ---------------------------------------------------------------------------


async def _execute_linear_run(
    run_id: str,
    request: "ExecuteRequest",
    initial_state: VQAState,
) -> None:
    """
    Execute a vQA run using the deterministic linear pipeline (TASK-105/TASK-106).

    Replaces the LangGraph cyclic loop for runs where ``execution_engine='linear'``.
    Orchestrates the Generate → Validate → Execute → Analyze DAG entirely in
    Python, streaming structured log lines to WebSocket clients via
    ``_broadcast_terminal_log``.

    Args
    ----
    run_id : str
        Unique run identifier (matches the run registered in ``_run_states``).
    request : ExecuteRequest
        The original API request (used for ticket_id, tenant_id, role).
    initial_state : VQAState
        Pre-built initial state (used only for ticket/role metadata; the linear
        pipeline does not consume VQAState internally).
    """
    _run_states[run_id]["status"] = "running"
    logger.info("[%s] Starting LINEAR pipeline for ticket=%s", run_id, request.jira_ticket_id)

    # Build corpus card dict from the API request for the pipeline nodes.
    # We fetch the Jira ticket context here using the existing client so the
    # generator_node receives a structured card (with acceptance_criteria +
    # expected_steps) rather than a raw ticket ID string.
    card: dict = {
        "ticket_id": request.jira_ticket_id,
        "summary": "",
        "acceptance_criteria": "",
        "expected_steps": [],
        "description": "",
    }

    try:
        from backend.jira.client import fetch_ticket_context as _fetch
        raw_ticket = await _fetch(request.jira_ticket_id)
        if raw_ticket:
            card["summary"] = raw_ticket.get("summary", "")
            card["acceptance_criteria"] = raw_ticket.get("acceptance_criteria", "")
            card["description"] = raw_ticket.get("description", "")
            # Use parsed AC steps if available; fall back to raw AC text
            ac_steps = raw_ticket.get("acceptance_criteria_steps", [])
            if isinstance(ac_steps, list) and ac_steps:
                card["expected_steps"] = ac_steps
            logger.info(
                "[%s] Linear: Jira fetch OK for %s — %d AC steps",
                run_id, request.jira_ticket_id, len(card["expected_steps"]),
            )
    except Exception as jira_err:
        logger.warning(
            "[%s] Linear: Jira fetch failed (%s) — proceeding with empty card",
            run_id, jira_err,
        )

    # ── Two-stage AC Parser wiring ───────────────────────────────────────
    if not card.get("expected_steps") and card.get("acceptance_criteria"):
        logger.info(
            "[%s] Linear: expected_steps empty, running ac_parser_node with domain-aware enrichment",
            run_id,
        )
        try:
            from backend.engine.ac_parser import ac_parser_node
            stub_state = {
                "run_id": run_id,
                "jira_ticket": {
                    "ticket_id": request.jira_ticket_id,
                    "summary": card["summary"],
                    "acceptance_criteria": card["acceptance_criteria"],
                    "description": card["description"],
                },
                "pre_parse_guidance": getattr(request, "pre_parse_guidance", "") or "",
                "pre_parse_guidance_approved": getattr(request, "pre_parse_guidance_approved", False) or False,
                "override_ac_steps": getattr(request, "override_steps", []) or [],
                "user_guidance": "",
            }
            parsed_result = await ac_parser_node(stub_state)
            legacy_steps = parsed_result["jira_ticket"].get("acceptance_criteria_steps", [])
            card["expected_steps"] = legacy_steps
            logger.info(
                "[%s] Linear: ac_parser_node compiled %d steps successfully",
                run_id, len(legacy_steps),
            )
        except Exception as parser_err:
            logger.error("[%s] Linear: ac_parser_node failed: %s", run_id, parser_err)

    # ── FAIR Quality Gate Wiring (Log-Only MVP — TASK-106) ────────────────
    try:
        from backend.engine.ac_quality_gate import score_ac_quality
        ac_text = card.get("acceptance_criteria", "")
        if ac_text:
            q_result = score_ac_quality(ac_text)
            logger.info(
                "[%s] Linear: AC Quality score=%d/10, grade=%s",
                run_id, q_result.overall_score, q_result.quality_grade
            )
    except Exception as q_err:
        logger.warning("[%s] Linear: FAIR Quality Gate call failed: %s", run_id, q_err)

    # ── A11y Tree Snapshot Capture (WU-2.2 — TASK-106) ───────────────────
    a11y_elements = []
    try:
        import os

        from playwright.async_api import async_playwright

        from backend.engine.a11y_discovery import capture_a11y_snapshot, prune_and_map_a11y_tree

        auth_state_path = "playwright/storage/vpromedia_auth.json"
        target_url = request.target_url or "https://two-test.vcreative.net"

        logger.info("[%s] Linear: Capturing A11y tree snapshot from %s", run_id, target_url)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx_opts = {}
            if os.path.exists(auth_state_path):
                ctx_opts["storage_state"] = auth_state_path

            context = await browser.new_context(**ctx_opts)
            page = await context.new_page()

            await page.goto(target_url, timeout=30000)
            raw_snapshot = await capture_a11y_snapshot(page)
            a11y_elements = prune_and_map_a11y_tree(raw_snapshot)

            await context.close()
            await browser.close()

        logger.info("[%s] Linear: A11y captured %d interactive elements", run_id, len(a11y_elements))
    except Exception as a11y_err:
        logger.warning("[%s] Linear: A11y Tree capture failed/skipped: %s", run_id, a11y_err)

    card["a11y_elements"] = a11y_elements

    # Broadcast helper: wraps _broadcast_terminal_log for the pipeline
    async def _pipe_broadcast(line: str, stream: str = "stdout") -> None:
        await _broadcast_terminal_log(run_id, line, stream=stream)  # type: ignore[arg-type]

    tenant_id = getattr(request, "tenant_id", "vpromedia") or "vpromedia"

    try:
        result: LinearRunResult = await run_linear_pipeline(
            run_id=run_id,
            card=card,
            tenant_id=tenant_id,
            broadcast_fn=_pipe_broadcast,
            timeout_s=300,
        )

        # Update run state with linear result
        _run_states[run_id].update({
            "status": result.status if result.status in ("completed", "failed") else "failed",
            "pipeline_status": result.pipeline_status,
            "analysis": result.analysis,
            "failure_analysis": {"jira_comment": result.analysis} if result.analysis else None,
            "elapsed_s": result.elapsed_s,
            "spec_path": result.spec_path,
            "engine": "linear",
            "error": result.error,
        })

        global _total_runs_completed

        if result.status == "completed":
            _total_runs_completed += 1
            logger.info(
                "[%s] LINEAR pipeline COMPLETED for %s in %.1fs",
                run_id, request.jira_ticket_id, result.elapsed_s,
            )
            await _broadcast_terminal(
                run_id,
                WSTerminalMessage(
                    type="completed",
                    run_id=run_id,
                    ac_steps_passed=len(card.get("expected_steps", [])),
                    ac_steps_total=len(card.get("expected_steps", [])),
                ),
            )
        else:
            error_summary = result.analysis or result.error or result.pipeline_status
            logger.warning(
                "[%s] LINEAR pipeline FAILED for %s: %s (%.1fs)",
                run_id, request.jira_ticket_id, result.pipeline_status, result.elapsed_s,
            )
            await _broadcast_terminal(
                run_id,
                WSTerminalMessage(
                    type="failed",
                    run_id=run_id,
                    error=error_summary[:500],
                    ac_steps_total=len(card.get("expected_steps", [])),
                ),
            )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        _run_states[run_id]["status"] = "failed"
        _run_states[run_id]["error"] = error_msg
        _run_states[run_id]["engine"] = "linear"
        logger.exception("[%s] LINEAR pipeline unexpected exception: %s", run_id, error_msg)
        await _broadcast_terminal(
            run_id,
            WSTerminalMessage(
                type="failed",
                run_id=run_id,
                error=error_msg,
            ),
        )

    finally:
        # AC-ENTRY-3: release the run_id from the owning session.
        _sid = (_run_states.get_sync(run_id) or {}).get("session_id")
        if _sid:
            try:
                from backend.session.manager import get_session_manager as _get_sm
                _get_sm().remove_active_run_id(_sid, run_id)
            except Exception as _sm_err:
                logger.warning("[%s] Session run-id release failed (linear): %s", run_id, _sm_err)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/preview-steps",
    response_model=PreviewStepsResponse,
    summary="Preview parsed AC steps for human review",
    description=(
        "Fetches a Jira ticket, parses its Acceptance Criteria into discrete "
        "browser steps using Claude, and returns them WITHOUT starting a run. "
        "The product team reviews and edits the steps in the UI, then passes "
        "them back via /execute with override_steps to skip re-parsing."
    ),
)
async def preview_steps(
    ticket_id: str,
    pre_parse_guidance: str = "",
    product: str = "",
    force_reparse: bool = False,
) -> PreviewStepsResponse:
    """
    Parse a Jira ticket's AC into steps and return for human review.

    This is the first half of the human-in-the-loop flow:
    1. Client calls GET /preview-steps?ticket_id=VC2-8967
    2. Server fetches ticket + parses steps via LLM
    3. Returns steps to the frontend for display + editing
    4. User confirms steps and client calls POST /execute with override_steps=[...]

    force_reparse
        When true, invalidates the content-hash disk cache entry for this
        ticket's raw AC BEFORE parsing, forcing a fresh LLM run. Use this
        escape hatch when the AC changed in Jira or you want a fresh look —
        otherwise the cached canonical parse is served (deterministic across
        restarts, saves ~3min of Bedrock calls per select).
    """
    import uuid as _uuid

    from backend.engine.graph import ac_parser_node, jira_fetch_node
    from backend.engine.state import make_initial_state

    ticket_id = ticket_id.strip().upper()
    logger.info(
        "POST /preview-steps — ticket=%s force_reparse=%s",
        ticket_id, force_reparse,
    )

    try:
        # Run only jira_fetch + ac_parser (no browser, no execution)
        stub_state = make_initial_state(
            run_id=f"preview-{_uuid.uuid4().hex[:6]}",
            jira_ticket_id=ticket_id,
            role="account_executive",  # role doesn't matter for parsing
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        # Bypass the FAIR guardrail for preview calls — the guardrail blocks on
        # an asyncio.Event that is only unblocked via a WebSocket /resume call,
        # but preview runs have no active WebSocket connection, so the event
        # would never be set and the request would hang indefinitely.
        # Steps are still generated and the quality warning still surfaces to
        # the frontend so the human can decide whether to refine the ticket.
        stub_state["pre_parse_guidance_approved"] = True
        # Skip the GHOST_LOGIN pre-flight credential gate for the same reason:
        # preview has no WebSocket, so the 300s wait would always time out and
        # degrade the structured plan to the legacy flat parser.
        stub_state["is_preview"] = True

        # Override the default active_product so the AC parser, quality gate, and
        # KB semantic RAG all query product-scoped workflows. Without this, every
        # preview runs under the vpromedia default, which strips vpromotions-only
        # PRF/select2 guidance out of retrieval and biases step targets toward
        # PrimeNG p-dropdown when the real widget is legacy select2.
        _product_slug = (product or "").strip().lower()
        if _product_slug:
            stub_state["active_product"] = _product_slug

        # Inject pre-parse guidance so the AC parser Bedrock call
        # can use any human context provided before step preview.
        if pre_parse_guidance and pre_parse_guidance.strip():
            stub_state["pre_parse_guidance"] = pre_parse_guidance.strip()
            logger.info(
                "[preview] pre_parse_guidance injected: %d chars — '%s'",
                len(pre_parse_guidance),
                pre_parse_guidance[:80],
            )
        fetched = await jira_fetch_node(stub_state)
        stub_state["jira_ticket"] = fetched["jira_ticket"]

        # force_reparse: invalidate the canonical baseline disk-cache entry for
        # this ticket's raw AC so ac_parser_node re-runs the full pipeline.
        # Uses the pre-enrichment raw AC (same value the disk cache is keyed on)
        # — see backend/engine/ac_parse_cache.py.
        if force_reparse:
            from backend.engine import ac_parse_cache as _content_cache
            _raw_ac = (
                fetched["jira_ticket"].get("acceptance_criteria")
                or fetched["jira_ticket"].get("description")
                or ""
            ).strip()
            if _raw_ac:
                removed = _content_cache.invalidate(_raw_ac)
                logger.info(
                    "[preview:%s] force_reparse=true — canonical baseline %s",
                    ticket_id,
                    "invalidated" if removed else "was not present",
                )

        parsed = await ac_parser_node(stub_state)
        ticket = parsed.get("jira_ticket", stub_state["jira_ticket"])

        test_plan_dict = parsed.get("test_plan")
        has_ghost_login = bool(
            test_plan_dict
            and any(
                s.get("step_type") in ("GHOST_LOGIN", "AUTHENTICATE_AND_GHOST")
                for s in test_plan_dict.get("steps", [])
            )
        )
        # Fallback: when structured parser falls back to legacy, detect ghost via
        # quality gate warnings (ac_quality_gate already scans raw_ac for \bghost\b).
        if not has_ghost_login:
            _aq = parsed.get("ac_quality_result") or {}
            has_ghost_login = any(
                "GHOST_CREDENTIALS_REQUIRED" in w
                for w in (_aq.get("warnings") or [])
            )
        if has_ghost_login:
            logger.info("[preview:%s] Ghost Login detected (credential gate required)", ticket_id)

        # Detect "ghost" keyword in the Jira description. When present the
        # frontend prompts the operator for email/password credentials which are
        # injected as override_email/override_password — superseding stored role
        # credentials and skipping the preflight auth check.
        _description_text = ticket.get("description", "") or ""
        has_ghost_description = "ghost" in _description_text.lower()
        if has_ghost_description:
            logger.info(
                "[preview:%s] 'ghost' detected in ticket description — credential prompt required",
                ticket_id,
            )

        return PreviewStepsResponse(
            ticket_id=ticket_id,
            summary=ticket.get("summary", ""),
            acceptance_criteria=ticket.get("acceptance_criteria", ""),
            steps=ticket.get("acceptance_criteria_steps", []),
            parse_quality=parsed.get("parse_quality"),
            parse_quality_reason=parsed.get("parse_quality_reason"),
            ac_quality=parsed.get("ac_quality_result"),
            detected_paths=parsed.get("detected_paths", []),
            ambiguities=parsed.get("ambiguities", []),
            pending_jira_comment=fetched.get("pending_jira_comment"),
            has_ghost_login=has_ghost_login,
            has_ghost_description=has_ghost_description,
        )
    except Exception as e:
        logger.error("preview-steps failed for %s: %s", ticket_id, e, exc_info=True)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview steps for {ticket_id}: {str(e)}",
        )


@router.post(
    "/preview-steps",
    response_model=PreviewStepsResponse,
    summary="Author a pinned TestPlan from inline acceptance criteria (Lock B)",
    description=(
        "Accepts inline acceptance_criteria text, authors a TestPlan via the "
        "vQA AC parser (Stage 1 + Stage 2), persists the result under an "
        "opaque plan_id, and returns it.  Pass the plan_id to POST /execute "
        "to replay the plan verbatim without re-invoking any LLM stage. "
        "The existing GET /preview-steps?ticket_id=... path is unchanged."
    ),
)
async def post_preview_steps(
    body: PreviewStepsRequest,
) -> PreviewStepsResponse:
    """
    Author a pinned TestPlan from inline acceptance criteria.

    Lock B for the ``/vc`` pipeline's red→green transition:
    1. Client calls POST /preview-steps with {acceptance_criteria: "..."}
    2. Server authors a TestPlan via the AC parser (same stages as GET path)
    3. Persists the plan under an opaque plan_id (UUID4) at startup-pruned TTL
    4. Returns the plan_id so POST /execute can replay it verbatim

    The GET /preview-steps path is unaffected — existing callers that omit
    a request body continue to work identically.
    """
    import uuid as _uuid

    from backend.engine.graph import ac_parser_node as _ac_parser_node
    from backend.engine.graph import jira_fetch_node as _jira_fetch_node
    from backend.engine.pinned_plans import save as _pinned_save
    from backend.engine.state import make_initial_state as _make_state

    logger.info(
        "POST /preview-steps (pinned-plan authoring) — ac_len=%d",
        len(body.acceptance_criteria),
    )

    try:
        # Build a stub state that skips Jira fetch by injecting the inline AC
        # directly. We use a synthetic ticket so the AC parser stages receive
        # the text in the expected shape without touching Jira.
        stub_state = _make_state(
            run_id=f"preview-pinned-{_uuid.uuid4().hex[:6]}",
            jira_ticket_id="INLINE",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        # Bypass FAIR guardrail and ghost-login gate (same as GET path)
        stub_state["pre_parse_guidance_approved"] = True
        stub_state["is_preview"] = True

        # Inject inline AC as a synthetic Jira ticket so ac_parser_node
        # receives it in the expected state shape.
        stub_state["jira_ticket"] = {
            "ticket_id": "INLINE",
            "acceptance_criteria": body.acceptance_criteria,
            "acceptance_criteria_steps": [],
            "summary": "Inline AC (POST /preview-steps)",
            "description": "",
        }

        parsed = await _ac_parser_node(stub_state)
        test_plan_dict = parsed.get("test_plan")

        if not test_plan_dict:
            raise HTTPException(
                status_code=500,
                detail="AC parser returned no test_plan — cannot author pinned plan",
            )

        # Persist the compiled plan and return its opaque id
        plan_id = _pinned_save(
            test_plan=test_plan_dict,
            acceptance_criteria=body.acceptance_criteria,
        )
        logger.info("POST /preview-steps: pinned plan authored — plan_id=%s", plan_id)

        # Build the response in the same shape as the GET path, with plan_id set
        ticket_after = parsed.get("jira_ticket", stub_state["jira_ticket"])
        return PreviewStepsResponse(
            ticket_id="INLINE",
            summary=ticket_after.get("summary", "Inline AC"),
            acceptance_criteria=body.acceptance_criteria,
            steps=ticket_after.get("acceptance_criteria_steps", []),
            parse_quality=parsed.get("parse_quality"),
            parse_quality_reason=parsed.get("parse_quality_reason"),
            ac_quality=parsed.get("ac_quality_result"),
            detected_paths=parsed.get("detected_paths", []),
            ambiguities=parsed.get("ambiguities", []),
            pending_jira_comment=None,
            has_ghost_login=False,
            has_ghost_description=False,
            plan_id=plan_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST /preview-steps failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to author pinned plan: {str(e)}",
        )


@router.post(
    "/jira/{ticket_id}/post-comment",
    summary="Post a pending vQA comment to a Jira ticket after user confirmation",
)
async def post_jira_comment_confirmed(ticket_id: str, body: dict) -> dict:
    """
    Posts a comment to the Jira ticket. Called by the frontend after the user
    confirms the pending comment surfaced by /preview-steps.
    """
    from backend.jira.client import post_jira_comment as _post_comment

    comment = body.get("comment", "").strip()
    if not comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="comment field is required")

    ticket_id = ticket_id.strip().upper()
    success = await _post_comment(ticket_id, comment)
    return {"success": success}


@router.get(
    "/ticket/{ticket_id}/credentials",
    response_model=CredentialCheckResponse,
    summary="Check login credentials in a Jira ticket",
    description=(
        "Fetches a Jira ticket and determines whether it contains login "
        "credentials (email and/or password). Used by the frontend to "
        "show inline prompts for missing fields before starting a run."
    ),
)
async def check_ticket_credentials(ticket_id: str) -> CredentialCheckResponse:
    """
    Pre-check credential status for a Jira ticket.

    Fetches the ticket from Jira and runs the credential extraction
    without starting a test run.  The frontend calls this (debounced)
    when the user types a ticket ID so it can show the credential status
    badge and prompt for any missing fields.
    """
    ticket_id = ticket_id.strip().upper()
    try:
        ctx = await fetch_ticket_context(ticket_id)
        email = ctx.get("override_login_email", "")
        password = ctx.get("override_login_password", "")
        status = ctx.get("credential_status", "none")

        if status == "complete":
            message = f"✅ Using credentials from ticket ({email})"
        elif status == "partial":
            missing = "password" if email else "email"
            message = f"⚠️ Ticket has {'email' if email else 'password'} but is missing {missing}"
        else:
            message = "ℹ️ No login credentials in ticket — will use role credentials"

        return CredentialCheckResponse(
            ticket_id=ticket_id,
            status=status,
            email_found=bool(email),
            password_found=bool(password),
            email=email,
            message=message,
        )
    except Exception as e:
        logger.warning("credential check failed for %s: %s", ticket_id, e)
        return CredentialCheckResponse(
            ticket_id=ticket_id,
            status="none",
            email_found=False,
            password_found=False,
            email="",
            message="Could not fetch ticket — will use role credentials",
        )


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="Start a single-ticket test run",
    description=(
        "Launches an autonomous test run for a single Jira ticket, "
        "executing as the specified user role.  Returns immediately "
        "with a run_id; connect to the WebSocket for live updates."
    ),
)
async def execute_single(
    request: ExecuteRequest,
    http_request: Request,
) -> ExecuteResponse:
    """
    Start a single-ticket test execution.

    Creates the initial VQAState and launches the LangGraph in a
    background task.  The response is returned immediately so the
    client can connect to the WebSocket for real-time updates.

    Args
    ----
    request : ExecuteRequest
        Contains jira_ticket_id, role, target_url, mode.
    http_request : Request
        The incoming FastAPI request object.

    Returns
    -------
    ExecuteResponse
        Contains run_id, status, stream_url, novnc_url.
    """
    # Phase 4 (AC-ENTRY-3): when session isolation is enabled, every /execute*
    # call must carry the vqa_session cookie so the run is bound to the caller's
    # session.  Kill-switch SESSION_ISOLATION_ENABLED=false bypasses this check
    # and uses the legacy anonymous-run path.
    if settings.session_isolation_enabled:
        from backend.auth.cookies import read_session_cookie as _read_cookie
        from fastapi import HTTPException as _HTTPException

        _session_id = _read_cookie(http_request)
        if not _session_id:
            raise _HTTPException(
                status_code=401,
                detail="Session cookie required. Call POST /api/session/start first.",
            )
    else:
        _session_id = None

    # ── Pinned-plan mutex guard (AC-ERROR-3) ──────────────────────────────────
    # plan_id and override_steps are mutually exclusive. Enforced here, before
    # any run state is created, so no LLM call is ever issued on a bad request.
    if request.plan_id and request.override_steps:
        raise HTTPException(
            status_code=400,
            detail="plan_id and override_steps are mutually exclusive — supply one or neither",
        )

    # ── Resolve pinned plan (AC-ERROR-1, AC-ERROR-2, AC-VERIFY-5) ────────────
    # When plan_id is provided, load the pinned plan BEFORE creating any run
    # state so that 404/410 errors are returned synchronously and cheaply
    # (no background task spawned, no LLM called). Resolving here — before
    # make_initial_state — ensures the error contracts are tight.
    _resolved_pinned_plan: dict | None = None
    if request.plan_id:
        from backend.engine.pinned_plans import (
            PinnedPlanExpired as _PPExpired,
            PinnedPlanNotFound as _PPNotFound,
            load as _pinned_load,
        )
        try:
            _resolved_pinned_plan = _pinned_load(request.plan_id)
        except _PPNotFound:
            raise HTTPException(
                status_code=404,
                detail=f"pinned plan not found: {request.plan_id}",
            )
        except _PPExpired:
            raise HTTPException(
                status_code=410,
                detail=f"pinned plan expired: {request.plan_id}",
            )

    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Human-readable label for the product team — shown in UI instead of the UUID
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from backend.engine.roles import get_role_display_name as _role_name

    _now = _dt.now(_tz.utc)
    _role_display = _role_name(request.role)
    _ts_label = _now.strftime("%-m/%-d %-I:%M %p")
    run_label = f"{request.jira_ticket_id.upper()} \u00b7 {_role_display} \u00b7 {_ts_label}"

    logger.info(
        "POST /execute — ticket=%s, role=%s, mode=%s → run_id=%s (%s)",
        request.jira_ticket_id,
        request.role,
        request.mode,
        run_id,
        run_label,
    )

    # Create initial state
    initial_state = make_initial_state(
        run_id=run_id,
        jira_ticket_id=request.jira_ticket_id,
        role=request.role,
        target_url=request.target_url,
        mode=request.mode,
        max_retries=settings.max_retries,
        max_planner_iterations=settings.max_planner_iterations,
        vision_mode=request.vision_mode,
    )

    if request.vision_mode != "dom":
        logger.info(
            "[%s] Vision mode override: %s (requested via /execute)",
            run_id,
            request.vision_mode,
        )

    # ── Resolve AppProfile ────────────────────────────────────────────
    # Priority: API request → VQA_PROFILE env var → "vsuite" default
    try:
        from backend.profiles import get_active_profile

        _profile = get_active_profile(request.profile if hasattr(request, "profile") else "")
        initial_state["active_profile"] = _profile.name
        logger.info("[%s] Active profile: %s (%s)", run_id, _profile.name, _profile.display_name)
    except Exception as _profile_err:
        initial_state["active_profile"] = "vsuite"
        logger.warning("[%s] Profile resolution failed, defaulting to vsuite: %s", run_id, _profile_err)

    # Inject user-supplied credential overrides (for partial credential cases)
    if request.override_email:
        initial_state["injected_login_email"] = request.override_email
    if request.override_password:
        initial_state["injected_login_password"] = request.override_password
    # Inject failed login testing flag
    if request.expect_login_failure:
        initial_state["expect_login_failure"] = True
        logger.info("[%s] Failed login testing mode enabled", run_id)
    # Inject optional human guidance into the planner state
    if request.user_guidance:
        initial_state["user_guidance"] = request.user_guidance
        logger.info("[%s] User guidance injected (%d chars)", run_id, len(request.user_guidance))
        # ── Persist to Human Guidance KB ─────────────────────────────────────
        # user_guidance is currently injected only into the ephemeral run state.
        # Writing it to human_guidance.md makes it TF-IDF indexed and retrievable
        # on ALL future runs that encounter a similar AC step — not just this one.
        try:
            from backend.engine.human_takeover import persist_user_guidance as _persist_guidance

            # Use ticket_id + summary as the AC step key since the run hasn't started
            guidance_step_key = f"[ticket: {request.jira_ticket_id}] {request.user_guidance[:120]}"
            asyncio.create_task(
                _persist_guidance(
                    guidance_text=request.user_guidance,
                    ac_step=guidance_step_key,
                    ticket_id=request.jira_ticket_id,
                    source="user_guidance_pre_run",
                    run_id=run_id,
                    product=(request.product or None),
                )
            )
        except Exception as _persist_err:
            logger.warning("[%s] Could not schedule user_guidance persistence: %s", run_id, _persist_err)
    # ── Inject resolved pinned plan into VQAState (AC-VERIFY-5) ─────────────
    # When a valid plan_id was supplied and resolved above, inject the pinned
    # plan into state so ac_parser_node short-circuits verbatim (Phase 3 lock).
    # This must happen BEFORE the background graph task is created.
    if _resolved_pinned_plan is not None:
        initial_state["pinned_plan"] = _resolved_pinned_plan
        initial_state["pinned_plan_id"] = request.plan_id
        logger.info(
            "[%s] Pinned plan injected — plan_id=%s (ac_parser_node will short-circuit)",
            run_id,
            request.plan_id,
        )

    # Inject pre-confirmed steps (skips LLM parsing in ac_parser_node)
    if request.override_steps:
        initial_state["override_ac_steps"] = request.override_steps
        logger.info("[%s] Override AC steps injected: %d steps", run_id, len(request.override_steps))
    # Inject pre-parse guidance into state so ac_parser_node Stage 1 can use it
    if request.pre_parse_guidance:
        initial_state["pre_parse_guidance"] = request.pre_parse_guidance
        logger.info(
            "[%s] Pre-parse guidance injected (%d chars): '%s'",
            run_id,
            len(request.pre_parse_guidance),
            request.pre_parse_guidance[:80],
        )

    # Pre-populate ghost credentials when supplied up-front by the UI.
    # This bypasses the mid-run GHOST_CREDENTIALS_REQUIRED WebSocket gate so
    # the run proceeds without operator intervention.
    if request.ghost_admin_email:
        set_ghost_credentials(
            run_id,
            email=request.ghost_admin_email,
            password=request.ghost_admin_password or "",
        )
        logger.info(
            "[%s] Pre-flight ghost credentials provided — Admin credential gate will be skipped",
            run_id,
        )

    # Inject product slug into state so nodes can use product-specific context.
    if request.product:
        initial_state["active_product"] = request.product

    # Register the run; stamp session_id when isolation is active (AC-ENTRY-3).
    _run_states[run_id] = {
        "status": "queued",
        "state": initial_state,
        "error": None,
        "jira_ticket_id": request.jira_ticket_id,
        "role": request.role,
        "run_label": run_label,
        "started_at": _now.isoformat(),
        "session_id": _session_id,  # None when isolation disabled (kill switch)
    }

    # AC-ENTRY-3: track the run on the session so lifecycle teardown can
    # cancel outstanding runs and observability sees which runs belong to
    # which session. No-op when SESSION_ISOLATION_ENABLED=false.
    if _session_id:
        from backend.session.manager import get_session_manager as _get_sm
        _get_sm().add_active_run_id(_session_id, run_id)

    # Launch execution in background — engine-gated (TASK-106)
    if request.execution_engine == "linear":
        logger.info(
            "[%s] execution_engine='linear' — routing to deterministic linear pipeline",
            run_id,
        )
        asyncio.create_task(_execute_linear_run(run_id, request, initial_state))
    else:
        asyncio.create_task(_execute_run(run_id, initial_state))

    # Build response (dynamic host/protocol support)
    host = http_request.headers.get("host", "localhost").split(":")[0]
    proto_ws = "wss" if http_request.url.scheme == "https" else "ws"

    stream_url = f"{proto_ws}://{host}:{settings.api_port}/ws/{run_id}"
    novnc_url = vnc_builder.build_url(http_request, request.mode)

    return ExecuteResponse(
        run_id=run_id,
        run_label=run_label,
        status="running",
        stream_url=stream_url,
        novnc_url=novnc_url,
    )


@router.post(
    "/run/{run_id}/post-to-jira",
    summary="Manually post failure triage to Jira",
    description=(
        "Posts the failure analysis from a completed run as a Jira comment. "
        "Called from the Triage Panel when the user clicks 'Post to Jira'."
    ),
)
async def post_triage_to_jira(run_id: str):
    """
    Post the failure triage comment to the Jira ticket for a failed run.

    Reads the stored failure_analysis from the run state and posts it.
    Returns 404 if the run is not found, 400 if the run passed or has
    no analysis, 200 on success.
    """
    from backend.jira.client import post_jira_comment

    if run_id not in _run_states:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run_data = _run_states[run_id]
    final_state = run_data.get("state") or {}
    failure_analysis = final_state.get("failure_analysis") or run_data.get("failure_analysis") or {}

    if not failure_analysis:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="No failure analysis available for this run (run may have passed or analysis failed)",
        )

    ticket_id = (
        final_state.get("jira_ticket", {}).get("ticket_id")
        or run_data.get("jira_ticket_id")
        or ""
    )
    if not ticket_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="No ticket ID found in run state")

    comment = failure_analysis.get("jira_comment", "")
    report_url = final_state.get("s3_report_url", "")
    if report_url and report_url not in comment:
        comment += f"\n\nFull report: {report_url}"

    ok = await post_jira_comment(ticket_id, comment)
    if ok:
        return {"status": "posted", "ticket_id": ticket_id}
    else:
        from fastapi import HTTPException

        raise HTTPException(status_code=502, detail="Failed to post comment to Jira")


@router.post(
    "/ticket/{ticket_id}/sync-ac",
    response_model=SyncACResponse,
    summary="Sync user-added ACs back to a Jira ticket",
    description=(
        "Appends new acceptance criteria steps to a Jira ticket's AC field "
        "without overwriting existing content. Called from the AC Confirmation "
        "Gate when the user adds new steps and clicks 'Update Jira'."
    ),
)
async def sync_ac_to_jira(
    ticket_id: str,
    request: SyncACRequest,
) -> SyncACResponse:
    """
    Append user-added acceptance criteria to a Jira ticket.

    Performs an append-only update: fetches the current AC field,
    adds the new steps with a separator, writes back, and posts
    an audit comment.

    Args
    ----
    ticket_id : str
        Jira issue key (e.g. "QA-280").
    request : SyncACRequest
        Contains the user-added steps to append.

    Returns
    -------
    SyncACResponse
        Contains sync success status, added count, and final AC text.
    """
    ticket_id = ticket_id.strip().upper()
    logger.info(
        "POST /ticket/%s/sync-ac — %d steps to append",
        ticket_id,
        len(request.added_steps),
    )

    try:
        from backend.jira.client import append_to_ticket_ac

        success, new_ac_text = await append_to_ticket_ac(
            ticket_id=ticket_id,
            new_steps=request.added_steps,
            audit_source="vQA Dashboard (AC Confirmation Gate)",
        )

        return SyncACResponse(
            ticket_id=ticket_id,
            synced=success,
            added_count=len(request.added_steps),
            new_ac_text=new_ac_text,
            comment_posted=success,
            error="" if success else "Jira API returned an error during AC update.",
        )

    except Exception as e:
        logger.error(
            "sync-ac failed for %s: %s",
            ticket_id,
            e,
            exc_info=True,
        )
        return SyncACResponse(
            ticket_id=ticket_id,
            synced=False,
            added_count=0,
            error=f"Sync failed: {str(e)}",
        )


@router.post(
    "/execute-batch",
    response_model=BatchExecuteResponse,
    summary="Start a batch of test runs (CI/CD)",
    description=("Launches multiple test runs in parallel for CI/CD pipeline gating.  Always runs in headless mode."),
)
async def execute_batch(
    request: BatchExecuteRequest,
    http_request: Request,
) -> BatchExecuteResponse:
    """
    Start batch test execution for CI/CD pipelines.

    Each ticket+role pair becomes an independent run.  All runs
    execute in headless mode.

    Args
    ----
    request : BatchExecuteRequest
        Contains list of tickets and target_url.
    http_request : Request
        The incoming FastAPI request object — carries the vqa_session
        cookie when SESSION_ISOLATION_ENABLED is on.

    Returns
    -------
    BatchExecuteResponse
        Contains batch_id and individual run statuses.
    """
    # AC-ENTRY-3: batch is headless (no display) but the spec requires every
    # /execute* endpoint to enforce the session cookie when isolation is on.
    if settings.session_isolation_enabled:
        from backend.auth.cookies import read_session_cookie as _read_cookie
        from fastapi import HTTPException as _HTTPException

        _session_id = _read_cookie(http_request)
        if not _session_id:
            raise _HTTPException(
                status_code=401,
                detail="Session cookie required. Call POST /api/session/start first.",
            )
    else:
        _session_id = None

    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    run_ids: list[str] = []
    runs: list[BatchRunItem] = []

    logger.info(
        "POST /execute-batch — %d tickets → batch_id=%s",
        len(request.tickets),
        batch_id,
    )

    _sm = None
    if _session_id:
        from backend.session.manager import get_session_manager as _get_sm
        _sm = _get_sm()

    for item in request.tickets:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        run_ids.append(run_id)

        initial_state = make_initial_state(
            run_id=run_id,
            jira_ticket_id=item.jira_ticket_id,
            role=item.role,
            target_url=request.target_url,
            mode="headless",
            max_retries=settings.max_retries,
            max_planner_iterations=settings.max_planner_iterations,
        )

        _run_states[run_id] = {
            "status": "queued",
            "state": initial_state,
            "error": None,
            "jira_ticket_id": item.jira_ticket_id,
            "role": item.role,
            "session_id": _session_id,
        }

        if _sm is not None:
            _sm.add_active_run_id(_session_id, run_id)

        # Launch each run as a background task
        asyncio.create_task(_execute_run(run_id, initial_state))

        runs.append(
            BatchRunItem(
                run_id=run_id,
                jira_ticket_id=item.jira_ticket_id,
                role=item.role,
                status="queued",
            )
        )

    _batch_registry[batch_id] = run_ids

    return BatchExecuteResponse(
        batch_id=batch_id,
        total_tickets=len(request.tickets),
        runs=runs,
    )


@router.get(
    "/status/{run_id}",
    response_model=StatusResponse,
    summary="Get run status and artifacts",
    description="Returns the current status, progress, and artifact URLs for a run.",
)
async def get_status(run_id: str, http_request: Request) -> StatusResponse:
    """
    Get the status of a test run.

    Args
    ----
    run_id : str
        The run identifier returned by /execute.
    http_request : Request
        The incoming FastAPI request object.

    Returns
    -------
    StatusResponse
        Current status, AC progress, and artifact URLs.
    """
    if run_id not in _run_states:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Run '{run_id}' not found"},
        )

    run = _run_states[run_id]
    state = run.get("state") or {}

    # Extract progress from state
    ticket = state.get("jira_ticket", {}) if isinstance(state, dict) else {}
    ac_steps = ticket.get("acceptance_criteria_steps", [])
    completed = state.get("ac_steps_completed", [])
    log = state.get("detailed_execution_log", [])
    bugs = state.get("bug_log", [])

    # Calculate duration
    duration_ms = 0
    if log and len(log) >= 2:
        try:
            from datetime import datetime as dt

            t1 = dt.fromisoformat(log[0].get("timestamp", "").replace("Z", "+00:00"))
            t2 = dt.fromisoformat(log[-1].get("timestamp", "").replace("Z", "+00:00"))
            duration_ms = int((t2 - t1).total_seconds() * 1000)
        except Exception:
            pass

    artifacts = ArtifactsInfo(
        video_url=state.get("s3_video_url", ""),
        report_url=state.get("s3_report_url", ""),
        screenshots=state.get("screenshots", []),
    )

    return StatusResponse(
        run_id=run_id,
        status=run["status"],
        jira_ticket_id=run.get("jira_ticket_id", ""),
        role=run.get("role", ""),
        duration_ms=duration_ms,
        ac_steps_total=len(ac_steps),
        ac_steps_completed=(
            sum(1 for i in range(len(ac_steps)) if i in set(completed)) if isinstance(completed, list) else 0
        ),
        browser_actions=len(log),
        bugs_found=len(bugs),
        artifacts=artifacts,
        run_metrics=state.get("run_metrics", {}),
        kb_update_proposals=state.get("kb_update_proposals", []),
        novnc_url=vnc_builder.build_url(http_request, state.get("mode", "interactive")),
    )


@router.get(
    "/runs/{run_id}/report",
    response_class=HTMLResponse,
    summary="Get the HTML audit report for a run",
    description="Returns the full HTML report string directly from memory for recent runs.",
)
@router.head(
    "/runs/{run_id}/report",
    response_class=HTMLResponse,
    include_in_schema=False,
)
@router.get(
    "/report/{run_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
@router.head(
    "/report/{run_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def get_run_report(run_id: str):
    """
    Serve the HTML audit report for a specific run.

    Args
    ----
    run_id : str
        The run identifier.

    Returns
    -------
    HTMLResponse
        The rendered HTML report.
    """
    if run_id not in _run_states:
        # Fallback: check if we have it in history?
        # (Currently run_history only stores URLs, not full HTML)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found in memory. Please use the S3 link if available.",
        )

    run = _run_states[run_id]
    state = run.get("state", {})
    html = state.get("final_html_report", "")

    if not html:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail=f"HTML report not yet generated for run '{run_id}'.",
        )

    return HTMLResponse(content=html)


@router.get(
    "/kb-proposals",
    response_model=None,
    summary="Get KB update proposals",
    description="Returns auto-generated KB update proposals from patterns proven 3+ times across runs.",
)
async def get_kb_proposals():
    """
    Retrieve Knowledge Base update proposals from cross-run learning.

    Returns proposals for locator strategies that have been proven
    successful 3+ times across different test runs. These can be
    reviewed and applied to the KB for permanent agent improvement.

    Returns
    -------
    dict
        ``total`` and ``proposals`` list.
    """
    from backend.api.schemas import KBProposalItem, KBProposalsResponse
    from backend.memory.persistent import persistent_memory

    proposals = persistent_memory.propose_kb_updates(min_success_count=3)

    items = [
        KBProposalItem(
            situation=p.get("situation", ""),
            strategy=p.get("strategy", ""),
            success_count=p.get("success_count", 0),
            proposed_kb_entry=p.get("proposed_kb_entry", ""),
        )
        for p in proposals
    ]

    return KBProposalsResponse(
        total=len(items),
        proposals=items,
    )


# ---------------------------------------------------------------------------
# Run History & Analytics (Phase 5C)
# ---------------------------------------------------------------------------


@router.get(
    "/runs/history",
    response_model=None,
    summary="Get run history",
    description="Returns paginated run history with optional ticket and status filters.",
)
async def get_run_history(
    limit: int = 50,
    offset: int = 0,
    ticket_id: str | None = None,
    status: str | None = None,
):
    """
    Retrieve paginated run history.

    Parameters
    ----------
    limit : int
        Max runs to return (default 50).
    offset : int
        Pagination offset.
    ticket_id : str, optional
        Filter by ticket ID.
    status : str, optional
        Filter by status (``"passed"``, ``"failed"``).
    """
    from backend.api.schemas import RunHistoryItem, RunHistoryResponse
    from backend.storage.run_history import run_history

    runs = run_history.get_runs(
        limit=limit,
        offset=offset,
        ticket_id=ticket_id,
        status=status,
    )

    items = [
        RunHistoryItem(
            run_id=r.get("run_id", ""),
            ticket_id=r.get("ticket_id", ""),
            role=r.get("role", ""),
            status=r.get("status", ""),
            duration_ms=r.get("duration_ms", 0),
            ac_total=r.get("ac_total", 0),
            ac_passed=r.get("ac_passed", 0),
            cost_usd=r.get("cost_usd", 0.0),
            report_url=r.get("report_url", ""),
            video_url=r.get("video_url", ""),
            profile=r.get("profile", "vsuite"),
            created_at=r.get("created_at", ""),
        )
        for r in runs
    ]

    return RunHistoryResponse(total=len(items), runs=items)


@router.get(
    "/runs/analytics",
    response_model=None,
    summary="Get run analytics",
    description="Returns aggregated analytics: pass rate, cost trends, top tickets.",
)
async def get_run_analytics(days: int = 30):
    """
    Get aggregated run analytics for the last N days.

    Parameters
    ----------
    days : int
        Number of days to look back (default 30).
    """
    from backend.api.schemas import RunAnalyticsResponse, TopTicket
    from backend.storage.run_history import run_history

    analytics = run_history.get_analytics(days=days)

    top_tickets = [
        TopTicket(
            ticket_id=t.get("ticket_id", ""),
            runs=t.get("runs", 0),
            passes=t.get("passes", 0),
        )
        for t in analytics.get("top_tickets", [])
    ]

    return RunAnalyticsResponse(
        period_days=analytics.get("period_days", days),
        total_runs=analytics.get("total_runs", 0),
        passed=analytics.get("passed", 0),
        failed=analytics.get("failed", 0),
        pass_rate=analytics.get("pass_rate", 0.0),
        total_cost_usd=analytics.get("total_cost_usd", 0.0),
        avg_cost_usd=analytics.get("avg_cost_usd", 0.0),
        avg_duration_ms=analytics.get("avg_duration_ms", 0),
        total_ac_steps=analytics.get("total_ac_steps", 0),
        total_ac_passed=analytics.get("total_ac_passed", 0),
        top_tickets=top_tickets,
    )


# Global in-memory checkpointer for LangGraph state persistence
_memory_checkpointer = MemorySaver()

# Per-run pause events. When present, the graph loop blocks.
# Logic: Event is set (True) by default. Clear it to pause.
_pause_events: dict[str, asyncio.Event] = {}

# Per-run resume data (e.g. injected steps)
_resume_data: dict[str, dict] = {}

# In-memory set of cancelled run IDs — checked by astream loop each step
_cancelled_runs: set[str] = set()

# FEAT-114: Per-run compiled graph registry for HITL interrupt_before resume.
# When enable_hitl_before_executor=True, the compiled graph is stored here so
# that POST /run/{run_id}/resume-executor can call graph.ainvoke(None, config).
# Entries are cleaned up when the run terminates (success, error, or cancel).
_hitl_graphs: dict[str, object] = {}

# ---------------------------------------------------------------------------
# FAIR Guardrail (TASK-096) — re-export from ac_parser for external access
# ---------------------------------------------------------------------------
# The guardrail events dict and broadcast helper live in ac_parser.py to avoid
# circular imports (routes → ac_parser → routes).  We re-export them here so
# callers can reference routes._pre_parse_events and
# routes._broadcast_pre_parse_guidance_required via the routes module.
from backend.engine.ac_parser import (  # noqa: E402, PLC0415
    _pre_parse_events,
)


@router.post("/run/{run_id}/cancel", summary="Cancel a running test")
async def cancel_run(run_id: str):
    """
    Signal a running test to stop after the current step and generate
    a partial report with whatever steps have completed so far.
    """
    if run_id not in _run_states:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Run '{run_id}' not found"},
        )
    status = _run_states[run_id].get("status", "")
    if status not in ("running", "pending"):
        return JSONResponse(
            status_code=400,
            content={"detail": f"Run '{run_id}' is not running (status: {status})"},
        )
    _cancelled_runs.add(run_id)
    logger.info("[%s] Cancel requested — will stop after current step", run_id)
    return {"run_id": run_id, "status": "cancelling"}


@router.post("/run/{run_id}/pause", summary="Pause a running test")
async def pause_run(run_id: str):
    """
    Signal a running test to pause after the current node completes.
    Execution is suspended until /resume is called.
    """
    if run_id not in _pause_events:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or not pausable")

    logger.info("[%s] Pause requested", run_id)
    _pause_events[run_id].clear()  # Clearing the event causes .wait() to block
    return {"ok": True, "status": "pausing"}


@router.post("/run/{run_id}/resume", summary="Resume a paused test")
async def resume_run(run_id: str, req: Optional[ResumeRequest] = None):
    """
    Signal a paused test to resume execution.
    Optionally allows injecting updated AC steps.

    Also handles the FAIR-quality guardrail (TASK-096):
    - If the run is blocked on ``_pre_parse_events`` (awaiting pre-parse guidance),
      the event is set to unblock ``ac_parser_node``.
    - ``pre_parse_guidance`` and ``pre_parse_guidance_approved`` from the request
      body are stored in ``_resume_data`` for ``ac_parser_node`` to consume.
    - Falls through to the normal pause/resume logic for running-state pauses.
    """
    # ── FAIR Guardrail unblock ──────────────────────────────────────────────
    # Check _pre_parse_events first: if the run is blocked waiting for
    # pre-parse guidance, we set the event and store guidance/approval.

    _is_pre_parse_pause = run_id in _pre_parse_events

    if req:
        # Always store pre_parse_guidance / approved in _resume_data so both
        # the pre-parse guardrail AND the normal resume path can consume it.
        _pre_parse_payload: dict = {}
        if req.pre_parse_guidance is not None:
            _pre_parse_payload["pre_parse_guidance"] = req.pre_parse_guidance
        if req.pre_parse_guidance_approved is not None:
            _pre_parse_payload["pre_parse_guidance_approved"] = req.pre_parse_guidance_approved
        if _pre_parse_payload:
            # Merge with any existing resume data (don't stomp override_steps)
            existing = _resume_data.get(run_id, {})
            existing.update(_pre_parse_payload)
            _resume_data[run_id] = existing

    if _is_pre_parse_pause:
        logger.info("[%s] Resume (pre-parse guardrail): setting _pre_parse_events event", run_id)
        _pre_parse_events[run_id].set()
        return {"ok": True, "status": "resuming"}

    # ── Normal pause/resume path ────────────────────────────────────────────
    if run_id not in _pause_events:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found or not pausable")

    logger.info("[%s] Resume requested", run_id)

    # Store override_steps updates to be applied by the execution loop
    if req and req.override_steps:
        existing = _resume_data.get(run_id, {})
        existing["override_steps"] = req.override_steps
        _resume_data[run_id] = existing

    _pause_events[run_id].set()  # Setting the event unblocks .wait()
    return {"ok": True, "status": "resuming"}


@router.post(
    "/run/{run_id}/resume-executor",
    summary="Resume executor after HITL interrupt (FEAT-114)",
    description=(
        "Resume a graph that is paused at an ``interrupt_before=['executor']`` breakpoint. "
        "Only valid when ``ENABLE_HITL_BEFORE_EXECUTOR=True`` (configured in settings). "
        "Calling this endpoint signals human approval of the pending executor action and "
        "resumes graph execution for one executor step.  The graph will pause again before "
        "the next executor invocation until all steps are complete."
    ),
)
async def resume_executor(run_id: str):
    """
    Resume a run paused at ``interrupt_before=['executor']``.

    FEAT-114: When ``settings.enable_hitl_before_executor`` is True, the graph
    compiles with ``interrupt_before=['executor']`` and will pause before every
    executor_node call.  This endpoint allows the frontend to signal human
    approval and resume execution for one step.

    The compiled graph must be registered in ``_hitl_graphs[run_id]`` — this
    happens automatically in ``_execute_run`` when HITL mode is active.

    Parameters
    ----------
    run_id : str
        The run identifier returned by ``POST /execute``.

    Returns
    -------
    dict
        ``{"ok": True, "status": "resumed"}`` on success.
        ``{"ok": False, "reason": "..." }`` if HITL mode is inactive or run not found.
    """
    if not settings.enable_hitl_before_executor:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "reason": "HITL before executor is not enabled (ENABLE_HITL_BEFORE_EXECUTOR=False)"},
        )

    if run_id not in _hitl_graphs:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": f"No HITL graph registered for run '{run_id}'. Run may have completed or not started in HITL mode."},
        )

    graph = _hitl_graphs[run_id]
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": 3000,
    }

    logger.info("[%s] HITL resume-executor: resuming graph from executor interrupt", run_id)

    # Resume the graph by invoking with None (LangGraph resumes from the interrupt
    # checkpoint when the input is None and a checkpointer is present).
    try:
        await graph.ainvoke(None, config=config)
        logger.info("[%s] HITL resume-executor: graph step completed", run_id)
    except Exception as exc:
        logger.error("[%s] HITL resume-executor: graph error: %s", run_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Graph execution failed during HITL resume. See server logs for details.",
        ) from exc

    return {"ok": True, "status": "resumed"}



# ---------------------------------------------------------------------------
# Test Persistence & Smart Replay (TASK-031 / FEAT-043)
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/accept",
    summary="Accept a completed test run",
    description=(
        "Marks a completed test run as 'accepted' by serializing its action sequence "
        "to the accepted test store. Future runs for the same Jira ticket with identical "
        "AC will replay this accepted sequence deterministically, bypassing the LLM planner. "
        "Returns 404 if the run is not found, 400 if it has not completed yet."
    ),
)
async def accept_run(run_id: str):
    """
    Accept a completed test run and store it for future Smart Replay.

    The operator calls this endpoint after reviewing a successful run to
    approve its action sequence as the canonical path for this ticket.

    Args
    ----
    run_id : str
        The run identifier (from POST /execute).

    Returns
    -------
    dict
        Confirmation with ticket_id, ac_hash, and step_count.

    Raises
    ------
    HTTPException 404
        If the run_id is not found.
    HTTPException 400
        If the run has not completed yet (still running or failed).
    HTTPException 422
        If the run state lacks required fields (no AC steps or execution log).
    """
    from fastapi import HTTPException

    from backend.storage.accepted_test_store import get_accepted_test_store

    if run_id not in _run_states:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    run = _run_states[run_id]
    status = run.get("status", "")

    if status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Run '{run_id}' has not completed (status: {status}). Only completed runs can be accepted.",
        )

    state = run.get("state", {})
    ticket = state.get("jira_ticket", {})
    ticket_id = ticket.get("ticket_id", "")
    ac_steps = ticket.get("acceptance_criteria_steps", [])
    execution_log = state.get("detailed_execution_log", [])

    if not ticket_id:
        raise HTTPException(status_code=422, detail="Run state missing ticket_id")
    if not ac_steps:
        raise HTTPException(status_code=422, detail="Run state has no acceptance_criteria_steps")
    if not execution_log:
        raise HTTPException(status_code=422, detail="Run state has no detailed_execution_log")

    store = get_accepted_test_store()
    try:
        record_path = store.save(
            ticket_id=ticket_id,
            ac_steps=ac_steps,
            execution_log=execution_log,
            run_id=run_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from backend.storage.spec_serializer import compute_ac_hash

    ac_hash = compute_ac_hash(ac_steps)

    logger.info(
        "POST /runs/%s/accept — accepted, ticket=%s, ac_hash=%s, stored at %s",
        run_id,
        ticket_id,
        ac_hash,
        record_path,
    )

    return {
        "accepted": True,
        "run_id": run_id,
        "ticket_id": ticket_id,
        "ac_hash": ac_hash,
        "step_count": len([s for s in execution_log if s.get("success")]),
        "record_path": str(record_path),
    }


@router.get(
    "/accepted-tests",
    summary="List all accepted test records",
    description=(
        "Returns all accepted test records stored on disk. "
        "Each record represents an approved action sequence for a Jira ticket+AC pair. "
        "Sorted by accepted_at descending (newest first)."
    ),
)
async def list_accepted_tests():
    """
    List all accepted test records in the store.

    Returns
    -------
    dict
        ``{total: int, records: [{ticket_id, ac_hash, accepted_at, step_count, run_id}]}``
    """
    from backend.storage.accepted_test_store import get_accepted_test_store

    store = get_accepted_test_store()
    records = store.list_all()
    return {"total": len(records), "records": records}


@router.delete(
    "/accepted-tests/{ticket_id}",
    summary="Delete an accepted test record",
    description=(
        "Removes the accepted test record for a specific ticket. "
        "The next run for this ticket will use full AI-driven execution. "
        "Requires the ac_hash query parameter to identify the specific record."
    ),
)
async def delete_accepted_test(ticket_id: str, ac_hash: str):
    """
    Delete an accepted test record by ticket_id + ac_hash.

    Args
    ----
    ticket_id : str
        Jira ticket ID.
    ac_hash : str
        The 12-char AC hash identifying the specific record to delete.

    Returns
    -------
    dict
        Confirmation of deletion or 404 if not found.
    """
    from fastapi import HTTPException

    from backend.storage.accepted_test_store import get_accepted_test_store

    store = get_accepted_test_store()
    # We have the ac_hash directly — use it to construct the path
    try:
        store._validate_ticket_id(ticket_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    file_name = store._record_filename(ticket_id, ac_hash)
    file_path = store._safe_path(file_name)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No accepted test found for ticket={ticket_id}, ac_hash={ac_hash}",
        )

    file_path.unlink()
    with store._lock:
        store._remove_from_index(ticket_id, ac_hash)

    logger.info("DELETE /accepted-tests/%s — deleted record (ac_hash=%s)", ticket_id, ac_hash)
    return {"deleted": True, "ticket_id": ticket_id, "ac_hash": ac_hash}


@router.get(
    "/batch-status/{batch_id}",
    response_model=BatchStatusResponse,
    summary="Get batch status",
)
async def get_batch_status(batch_id: str) -> BatchStatusResponse:
    """
    Get the aggregate status of a batch execution.

    Args
    ----
    batch_id : str
        The batch identifier returned by /execute-batch.

    Returns
    -------
    BatchStatusResponse
        Aggregate status with per-run details.
    """
    if batch_id not in _batch_registry:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Batch '{batch_id}' not found"},
        )

    run_ids = _batch_registry[batch_id]
    runs: list[StatusResponse] = []
    completed_count = 0
    failed_count = 0

    for rid in run_ids:
        status_resp = await get_status(rid)
        if isinstance(status_resp, StatusResponse):
            runs.append(status_resp)
            if status_resp.status == "completed":
                completed_count += 1
            elif status_resp.status == "failed":
                failed_count += 1

    # Determine aggregate status
    total = len(run_ids)
    if completed_count + failed_count == total:
        agg_status = "completed" if failed_count == 0 else "failed"
    else:
        agg_status = "running"

    return BatchStatusResponse(
        batch_id=batch_id,
        status=agg_status,
        total_tickets=total,
        completed_tickets=completed_count,
        failed_tickets=failed_count,
        runs=runs,
    )


# ---------------------------------------------------------------------------
# Test Suite endpoints (Phase 7)
# ---------------------------------------------------------------------------


@router.post(
    "/suites",
    response_model=SuiteResponse,
    summary="Create test suite",
    description="Create a reusable test suite grouping multiple Jira tickets.",
)
async def create_suite(body: SuiteCreate) -> SuiteResponse:
    """Create a new test suite."""
    from backend.storage.test_suites import suite_store

    tickets = [t.model_dump() for t in body.tickets]
    try:
        suite_id = suite_store.create_suite(
            name=body.name,
            description=body.description,
            tickets=tickets,
            schedule_cron=body.schedule_cron,
        )
    except ValueError as e:
        return JSONResponse(status_code=409, content={"detail": str(e)})

    suite = suite_store.get_suite(suite_id)
    return _suite_to_response(suite)


@router.get(
    "/suites",
    response_model=SuiteListResponse,
    summary="List test suites",
)
async def list_suites() -> SuiteListResponse:
    """Get all test suites."""
    from backend.storage.test_suites import suite_store

    suites = suite_store.list_suites()
    return SuiteListResponse(
        total=len(suites),
        suites=[_suite_to_response(s) for s in suites],
    )


@router.get(
    "/suites/{suite_id}",
    response_model=SuiteResponse,
    summary="Get test suite",
)
async def get_suite(suite_id: str) -> SuiteResponse:
    """Get a single test suite by ID."""
    from backend.storage.test_suites import suite_store

    suite = suite_store.get_suite(suite_id)
    if not suite:
        return JSONResponse(status_code=404, content={"detail": f"Suite '{suite_id}' not found"})
    return _suite_to_response(suite)


@router.put(
    "/suites/{suite_id}",
    response_model=SuiteResponse,
    summary="Update test suite",
)
async def update_suite(suite_id: str, body: SuiteUpdate) -> SuiteResponse:
    """Update an existing test suite."""
    from backend.storage.test_suites import suite_store

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.tickets is not None:
        updates["tickets"] = [t.model_dump() for t in body.tickets]
    if body.schedule_cron is not None:
        updates["schedule_cron"] = body.schedule_cron
    if body.enabled is not None:
        updates["enabled"] = body.enabled

    ok = suite_store.update_suite(suite_id, **updates)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": f"Suite '{suite_id}' not found"})

    suite = suite_store.get_suite(suite_id)
    return _suite_to_response(suite)


@router.delete("/suites/{suite_id}", summary="Delete test suite")
async def delete_suite(suite_id: str):
    """Delete a test suite."""
    from backend.storage.test_suites import suite_store

    ok = suite_store.delete_suite(suite_id)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": f"Suite '{suite_id}' not found"})
    return {"deleted": True, "suite_id": suite_id}


@router.post("/suites/{suite_id}/run", summary="Run a test suite")
async def run_suite(suite_id: str):
    """
    Execute all tickets in a test suite as a batch.

    Returns the batch_id for status polling.
    """
    from backend.storage.test_suites import suite_store

    suite = suite_store.get_suite(suite_id)
    if not suite:
        return JSONResponse(status_code=404, content={"detail": f"Suite '{suite_id}' not found"})

    tickets = suite.get("tickets", [])
    if not tickets:
        return JSONResponse(status_code=400, content={"detail": "Suite has no tickets"})

    # Build batch request using existing batch execution logic
    batch_id = f"suite-{suite_id}-{uuid.uuid4().hex[:6]}"
    _batch_registry[batch_id] = []

    for ticket_config in tickets:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        _batch_registry[batch_id].append(run_id)

        # Create run state
        _run_states[run_id] = {"status": "pending", "state": {}}

        # Build execute request
        req = ExecuteRequest(
            jira_ticket_id=ticket_config.get("jira_ticket_id", ""),
            role=ticket_config.get("role", "account_executive"),
            target_url=settings.target_url,
            mode=settings.vqa_mode,
        )

        # Launch as background task
        asyncio.create_task(_execute_run(run_id, req))

    # Record suite run
    suite_store.record_run(suite_id, batch_id, "running")

    logger.info(
        "Suite '%s' (%s) triggered — batch_id=%s, %d tickets",
        suite["name"],
        suite_id,
        batch_id,
        len(tickets),
    )

    return {
        "suite_id": suite_id,
        "batch_id": batch_id,
        "ticket_count": len(tickets),
        "status": "running",
    }


def _suite_to_response(suite: dict) -> SuiteResponse:
    """Convert a raw suite dict to a SuiteResponse."""
    tickets_raw = suite.get("tickets", [])
    tickets = [
        SuiteTicketItem(
            jira_ticket_id=t.get("jira_ticket_id", ""),
            role=t.get("role", "account_executive"),
        )
        for t in tickets_raw
    ]
    return SuiteResponse(
        id=suite.get("id", ""),
        name=suite.get("name", ""),
        description=suite.get("description", ""),
        tickets=tickets,
        schedule_cron=suite.get("schedule_cron", ""),
        enabled=bool(suite.get("enabled", True)),
        last_run_id=suite.get("last_run_id", ""),
        last_run_at=suite.get("last_run_at", ""),
        last_status=suite.get("last_status", ""),
        ticket_count=len(tickets_raw),
        created_at=suite.get("created_at", ""),
        updated_at=suite.get("updated_at", ""),
    )


@router.get(
    "/health",
    response_model=HealthCheck,
    summary="Liveness probe",
    description=(
        "Lightweight liveness probe — always returns 200 if the process is alive. "
        "Used by Docker HEALTHCHECK and container orchestrators. "
        "For deep connectivity checks, use ``/health/ready``."
    ),
)
async def health_liveness() -> HealthCheck:
    """
    Liveness probe: confirms the process is responsive.

    Does NOT call external services. Returns uptime, active run
    count, and total completed runs.
    """
    active = sum(1 for r in _run_states.values() if isinstance(r, dict) and r.get("status") == "running")
    return HealthCheck(
        status="ok",
        mode=settings.vqa_mode,
        version="1.0.0",
        build_number=settings.vqa_build_number,
        checks={"jira": "not_checked", "s3": "not_checked", "bedrock": "not_checked"},
        uptime_seconds=round(_time.monotonic() - _BOOT_TIME, 1),
        active_runs=active,
        total_runs_completed=_total_runs_completed,
    )


@router.get(
    "/health/ready",
    response_model=HealthCheck,
    summary="Readiness probe",
    description=(
        "Deep readiness probe — verifies Jira, S3, and Bedrock connectivity. "
        "Used by load balancers to determine if the instance can accept new runs."
    ),
)
async def health_readiness() -> HealthCheck:
    """
    Readiness probe: checks Jira, S3, and Bedrock connectivity.

    Returns
    -------
    HealthCheck
        Status and sub-check results with uptime counters.
    """
    from backend.jira.client import validate_jira_connectivity
    from backend.storage.s3 import validate_s3_connectivity

    # Run checks concurrently
    jira_ok, s3_ok = await asyncio.gather(
        validate_jira_connectivity(),
        validate_s3_connectivity(),
    )

    checks = {
        "jira": "connected" if jira_ok else "error",
        "s3": "connected" if s3_ok else "error",
        "bedrock": "configured",  # No cheap ping for Bedrock
    }

    overall = "ok" if all(v != "error" for v in checks.values()) else "degraded"
    active = sum(1 for r in _run_states.values() if isinstance(r, dict) and r.get("status") == "running")

    return HealthCheck(
        status=overall,
        mode=settings.vqa_mode,
        version="1.0.0",
        build_number=settings.vqa_build_number,
        checks=checks,
        uptime_seconds=round(_time.monotonic() - _BOOT_TIME, 1),
        active_runs=active,
        total_runs_completed=_total_runs_completed,
    )


# ---------------------------------------------------------------------------
# Playwright Test Library (Phase 1 — legacy endpoints kept for compat)
# ---------------------------------------------------------------------------
# The canonical Playwright API is now in backend/api/playwright_routes.py.
# These endpoints are kept for backward compatibility with existing integrations.


@router.get("/playwright/tests")
async def list_playwright_tests(product: str | None = None):
    """
    Returns a list of all static Playwright tests from the canonical index.

    Re-pointed to playwright/playwright_index.json (PLAYWRIGHT_INDEX_FILE env var).
    AC-BACK-1: registry reads from canonical index, not backend/playwright_tests/.

    When ``product`` is provided, only tests for that product's directory are returned.

    Delegates to playwright_routes._get_registry() so the canonical route and this
    compat endpoint share the same registry instance (and the same mock in tests).
    """
    from backend.api.playwright_routes import _get_registry as _pw_get_registry
    from backend.config.product_registry import load_product_registry
    registry = _pw_get_registry()
    if product is None:
        return registry.list_tests()
    try:
        reg = load_product_registry()
        product_ctx = reg.get(product)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown product slug '{product}'.")
    except Exception as exc:
        logger.error("Product registry unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Product registry unavailable.")
    return registry.list_tests_for_product(product_ctx.playwright_tests_dir)


@router.post("/playwright/refresh")
async def refresh_playwright_tests():
    """
    Manually refreshes the registry from the canonical index file.
    """
    tests_dir = os.getenv("PLAYWRIGHT_TESTS_DIR", "playwright/tests")
    registry_file = os.getenv("PLAYWRIGHT_INDEX_FILE", "playwright/playwright_index.json")
    registry = PlaywrightRegistry(tests_dir, registry_file)
    registry.refresh()
    return {"status": "ok", "test_count": len(registry.list_tests())}


# ---------------------------------------------------------------------------
# Product registry endpoint (TASK-124, Phase 2)
# ---------------------------------------------------------------------------


@router.get(
    "/products",
    summary="List all registered products",
    description=(
        "Return the public metadata for all products in the vQA product registry. "
        "Results are sorted by the product ``order`` field (ascending). "
        "Filesystem paths (playwright_tests_dir, personas_dir) are excluded "
        "from the response — only public, non-sensitive metadata is returned."
    ),
)
async def list_products():
    """
    Return all products from the product registry as ``ProductPublic`` objects.

    Returns
    -------
    list[dict]
        Sorted by ``order`` (ascending). Fields: slug, display_name, description,
        order, environments, default_environment, jira_board_ids, roles.
    """
    from backend.config.product_registry import load_product_registry, ProductPublic

    registry = load_product_registry()
    return [ProductPublic.from_context(p).model_dump() for p in registry.list()]


# ---------------------------------------------------------------------------
# Jira ticket list endpoint
# ---------------------------------------------------------------------------

# Simple in-process cache: (tickets, fetched_at)
_ticket_cache: dict[str, tuple[list, float]] = {}
_TICKET_CACHE_TTL = 300  # 5 minutes


@router.get("/tickets")
async def list_tickets(project: str | None = None, product: str | None = None):
    """
    Return all open tickets from the configured Jira Software boards.

    Results are cached for 5 minutes to avoid hammering the Jira API on
    every page load.  The frontend uses this to populate the ticket
    selector dropdown.

    Query Parameters
    ----------------
    project : str, optional
        Jira project key (e.g. "QA", "VC2"). If omitted, fetches active
        tickets from all projects on the configured boards.
    product : str, optional
        Product slug (e.g. "vpromedia", "vtrade"). When provided, the
        product's ``jira_board_ids`` from the product registry are used
        instead of the global ``settings.jira_board_ids``. Unknown slugs
        result in a 400 error. Products with an empty ``jira_board_ids``
        list return an empty result immediately (no Jira call).

    Returns
    -------
    list[dict]
        ``[{"id": "QA-280", "summary": "...", "status": "...",
            "priority": "...", "issue_type": "..."}]``
    """
    import time

    from backend.config.product_registry import load_product_registry

    # Resolve product-scoped board IDs when ?product= is supplied
    board_ids: list[int] | None = None  # None = use global settings fallback
    title_filter: str = ""
    if product is not None:
        try:
            registry = load_product_registry()
            product_ctx = registry.get(product)
            board_ids = product_ctx.jira_board_ids
            title_filter = product_ctx.ticket_title_filter
            # Product exists but has no boards → return empty immediately
            if not board_ids:
                return []
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown product slug '{product}'. "
                       f"Valid slugs: {load_product_registry().slugs()}",
            )

    # Cache key includes product slug so each product has its own cache entry
    cache_key = f"{product or 'all'}:{project or 'all'}"
    now = time.monotonic()
    cached = _ticket_cache.get(cache_key)
    if cached:
        tickets, fetched_at = cached
        if now - fetched_at < _TICKET_CACHE_TTL:
            if title_filter:
                filter_lower = title_filter.lower()
                tickets = [t for t in tickets if filter_lower in t.get("summary", "").lower()]
            return tickets

    try:
        tickets = await fetch_board_tickets(project=project, board_ids=board_ids)
        _ticket_cache[cache_key] = (tickets, now)
        # Apply title filter AFTER caching the full result set, so the cache
        # stays shared across products that use the same boards.
        if title_filter:
            filter_lower = title_filter.lower()
            tickets = [t for t in tickets if filter_lower in t.get("summary", "").lower()]
        return tickets
    except JiraClientError as e:
        logger.error("Failed to fetch Jira tickets: %s", str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch tickets from Jira: {e.detail}",
        )


# ---------------------------------------------------------------------------
# Previous reports list
# ---------------------------------------------------------------------------

_reports_cache: tuple[list, float] | None = None
_REPORTS_CACHE_TTL = 300  # 5 minutes


@router.get("/reports")
async def list_reports():
    """
    List past audit reports from S3, newest first.

    Parses the S3 filename pattern::

        audit-{ticket_id}-{role}-{timestamp}.html

    Returns
    -------
    list[dict]
        ``[{"run_id", "ticket_id", "role", "role_label", "timestamp",
           "label", "report_url", "video_url"}]``
    """
    import re as _re
    import time
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from backend.engine.roles import get_role_display_name as _role_name
    from backend.storage.s3 import _get_s3_client

    global _reports_cache
    now = time.monotonic()
    if _reports_cache:
        items, fetched_at = _reports_cache
        if now - fetched_at < _REPORTS_CACHE_TTL:
            return items

    try:
        client = _get_s3_client()
        prefix = f"{settings.s3_prefix}/reports/"
        resp = await asyncio.to_thread(
            client.list_objects_v2,
            Bucket=settings.s3_bucket,
            Prefix=prefix,
        )
        objects = resp.get("Contents", [])
    except Exception as exc:
        logger.error("Failed to list S3 reports: %s. Falling back to SQLite run history.", exc)
        try:
            from backend.storage.run_history import run_history as _rh
            # Get up to 100 recent runs from run history
            runs = _rh.get_runs(limit=100)
            items: list[dict] = []
            for r in runs:
                if not r.get("report_url"):
                    continue
                run_id = r.get("run_id", "")
                ticket_id = r.get("ticket_id", "")
                role = r.get("role", "")
                role_label = _role_name(role)

                # Format timestamp
                created_at = r.get("created_at", "")  # e.g. "2026-06-11 12:00:00"
                ts_iso = created_at
                ts_display = created_at
                try:
                    # SQLite stores it in UTC, let's parse and display nicely
                    dt = _dt.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc)
                    ts_display = dt.strftime("%-m/%-d/%y %-I:%M %p")
                    ts_iso = dt.isoformat()
                except ValueError:
                    pass

                label = f"{ticket_id} \u00b7 {role_label} \u00b7 {ts_display}"
                items.append(
                    {
                        "run_id": run_id,
                        "ticket_id": ticket_id,
                        "role": role,
                        "role_label": role_label,
                        "timestamp": ts_iso,
                        "timestamp_display": ts_display,
                        "label": label,
                        "report_url": r.get("report_url", ""),
                        "video_url": r.get("video_url", ""),
                    }
                )
            items.sort(key=lambda x: x["timestamp"], reverse=True)
            _reports_cache = (items, now)
            return items
        except Exception as db_exc:
            logger.error("Failed to fetch reports from SQLite run history fallback: %s", db_exc)
            return []

    # Pattern: audit-{ticket}-{role}-{timestamp}.html
    # Compile with _re.IGNORECASE to support lowercase ticket_id or roles safely
    PAT = _re.compile(r"audit-(?P<ticket>[a-zA-Z0-9\-]+?)-(?P<role>[a-z_]+)-(?P<ts>\d{8}T\d{6}Z)\.html$", _re.IGNORECASE)

    items: list[dict] = []
    for obj in objects:
        key: str = obj["Key"]
        fname = key.split("/")[-1]
        m = PAT.search(fname)
        if not m:
            continue

        ticket_id = m.group("ticket")
        role = m.group("role")
        ts_raw = m.group("ts")  # e.g. 20260402T194434Z
        run_id = key.split("/")[-2]  # parent folder = run_id

        # Parse timestamp
        try:
            dt = _dt.strptime(ts_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=_tz.utc)
            ts_display = dt.strftime("%-m/%-d/%y %-I:%M %p")
            ts_iso = dt.isoformat()
        except ValueError:
            ts_display = ts_raw
            ts_iso = ts_raw

        role_label = _role_name(role)
        label = f"{ticket_id} \u00b7 {role_label} \u00b7 {ts_display}"

        # Build public URLs
        base = f"https://{settings.s3_bucket}.s3.amazonaws.com"
        report_url = f"{base}/{key}"
        # Derive video URL from same run_id folder
        video_prefix = f"{settings.s3_prefix}/videos/{run_id}/"
        video_url = f"{base}/{video_prefix}"  # frontend will open folder listing

        items.append(
            {
                "run_id": run_id,
                "ticket_id": ticket_id,
                "role": role,
                "role_label": role_label,
                "timestamp": ts_iso,
                "timestamp_display": ts_display,
                "label": label,
                "report_url": report_url,
                "video_url": video_url,
            }
        )

    # Newest first
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    _reports_cache = (items, now)
    return items


# ---------------------------------------------------------------------------
# Human Takeover endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/interact",
    response_model=InteractResponse,
    summary="Inject a mouse/keyboard action into the live Playwright page",
    description=(
        "While a run is paused for human takeover, this endpoint injects a "
        "single browser action (click, type, key press, or scroll) directly "
        "into the Playwright page. Returns a fresh base64 screenshot so the "
        "frontend can update the interactive view immediately."
    ),
)
async def interact(run_id: str, req: InteractRequest) -> InteractResponse:
    """Inject a browser action into the live Playwright page (human takeover mode)."""
    if run_id not in _run_states:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    try:
        manager = get_manager(run_id)
    except KeyError:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=f"No active browser session for run '{run_id}'")

    page = manager.page
    if not page:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Browser page is not active")

    viewport = page.viewport_size or {"width": 1280, "height": 720}
    vw = viewport["width"]
    vh = viewport["height"]

    try:
        if req.action == "click":
            if req.x_pct is None or req.y_pct is None:
                from fastapi import HTTPException

                raise HTTPException(status_code=422, detail="x_pct and y_pct required for click")
            x = int(req.x_pct * vw)
            y = int(req.y_pct * vh)
            await page.mouse.click(x, y)
            await page.wait_for_timeout(400)  # Brief wait for page reaction

        elif req.action == "type":
            if not req.text:
                from fastapi import HTTPException

                raise HTTPException(status_code=422, detail="text required for type action")
            await page.keyboard.type(req.text, delay=50)

        elif req.action == "key":
            if not req.key:
                from fastapi import HTTPException

                raise HTTPException(status_code=422, detail="key required for key action")
            await page.keyboard.press(req.key)
            await page.wait_for_timeout(300)

        elif req.action == "scroll":
            delta = -400 if req.direction == "up" else 400
            await page.mouse.wheel(0, delta)
            await page.wait_for_timeout(200)

        # Return fresh screenshot
        screenshot_b64 = await capture_screenshot_b64(page)
        return InteractResponse(
            ok=True,
            screenshot_b64=screenshot_b64,
            viewport_width=vw,
            viewport_height=vh,
        )
    except Exception as e:
        logger.error("[%s] interact error: %s", run_id, e, exc_info=True)
        return InteractResponse(ok=False, error=str(e), viewport_width=vw, viewport_height=vh)


# ── Pause and Teach endpoint ────────────────────────────────────────────────
# TeachRequest, TeachResponse, CaptureClickRequest, CaptureClickResponse
# are all imported from backend.api.schemas (see top of file).


@router.post(
    "/runs/{run_id}/teach/capture-click",
    response_model=CaptureClickResponse,
    summary="Auto-capture element selector from a screenshot click",
    description=(
        "Click-to-Teach: the user clicks on the TakeoverPanel screenshot and "
        "the backend identifies the DOM element at those coordinates, "
        "generates the best CSS selector, injects a green highlight, "
        "and returns the selector + annotated screenshot. No manual CSS typing required."
    ),
)
async def capture_click(run_id: str, req: CaptureClickRequest) -> CaptureClickResponse:
    """
    Identify the DOM element at the clicked screenshot coordinates and return
    the auto-generated selector + a green-highlighted screenshot.
    """
    from fastapi import HTTPException

    from backend.browser.click_capture import build_element_label, highlight_and_screenshot

    if run_id not in _run_states:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    try:
        manager = get_manager(run_id)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"No active browser session for run '{run_id}'")

    page = manager.page
    if not page:
        raise HTTPException(status_code=409, detail="Browser page is not active")

    try:
        screenshot_b64, element_info = await highlight_and_screenshot(page, req.x_pct, req.y_pct)

        if not element_info:
            # Nothing found at those coordinates (e.g. user clicked background)
            return CaptureClickResponse(
                ok=False,
                screenshot_b64=screenshot_b64,
                error=(
                    "No interactive element found at those coordinates. "
                    "Try clicking directly on a button, column header, input, or link."
                ),
            )

        selector = element_info.get("selector", "")
        element_label = build_element_label(element_info)
        match_count = element_info.get("matchCount", 1)

        # Warn if selector isn't unique — frontend can show an amber badge
        if match_count > 1:
            logger.warning(
                "[%s] capture-click: selector '%s' matches %d elements — may be ambiguous",
                run_id,
                selector[:60],
                match_count,
            )

        logger.info(
            "[%s] capture-click: <%s> '%s' → '%s' (matches=%d)",
            run_id,
            element_info.get("tag", "?"),
            element_info.get("text", "")[:30],
            selector[:50],
            match_count,
        )

        return CaptureClickResponse(
            ok=True,
            selector=selector,
            element_label=element_label,
            screenshot_b64=screenshot_b64,
            tag=element_info.get("tag", ""),
            role=element_info.get("role", ""),
            text=element_info.get("text", ""),
            match_count=match_count,
        )

    except Exception as e:
        logger.error("[%s] capture-click error: %s", run_id, e, exc_info=True)
        return CaptureClickResponse(ok=False, error=str(e)[:200])


@router.post(
    "/runs/{run_id}/teach",
    response_model=TeachResponse,
    summary="Execute a human-verified action and teach it to the KB",
    description=(
        "While a run is paused for HITL, provides the EXACT selector and action to execute. "
        "The backend: (1) validates the selector exists in DOM, (2) executes the action, "
        "(3) writes the selector to selector_registry.json as HITL-confirmed, "
        "(4) appends a human_guidance.md entry for future RAG retrieval."
    ),
)
async def teach(run_id: str, req: TeachRequest) -> TeachResponse:
    """Execute a human-verified action and immediately persist it to KB."""

    from fastapi import HTTPException

    if run_id not in _run_states:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    try:
        manager = get_manager(run_id)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"No active browser session for run '{run_id}'")

    page = manager.page
    if not page:
        raise HTTPException(status_code=409, detail="Browser page is not active")

    selector = req.selector.strip()
    action = req.action.strip().lower()
    value = req.value.strip()
    description = req.description.strip()
    ac_step = req.ac_step.strip()

    if not selector:
        raise HTTPException(status_code=422, detail="'selector' field is required")
    if action not in ("click", "fill", "navigate"):
        raise HTTPException(status_code=422, detail="'action' must be 'click', 'fill', or 'navigate'")
    if not description:
        raise HTTPException(status_code=422, detail="'description' is required — teaches the KB")

    # ── 1. Validate selector exists in DOM (for CSS/XPath) ───────────
    screenshot_b64 = ""
    if action != "navigate":
        try:
            is_xpath = selector.startswith("/") or selector.startswith("(//")
            if is_xpath:
                count = await page.locator(f"xpath={selector}").count()
            else:
                count = await page.locator(selector).count()
            if count == 0:
                return TeachResponse(
                    ok=False,
                    error=f"Selector '{selector}' matched 0 elements. Check the CSS/XPath and try again.",
                )
            logger.info("[%s] Teach: selector '%s' matched %d element(s)", run_id, selector, count)
        except Exception as _val_err:
            return TeachResponse(
                ok=False,
                error=f"Selector validation error: {_val_err}",
            )

    # ── 2. Execute the action ────────────────────────────────────────
    try:
        if action == "click":
            is_xpath = selector.startswith("/") or selector.startswith("(//")
            loc = page.locator(f"xpath={selector}") if is_xpath else page.locator(selector)
            await loc.first.click(timeout=8000)
            await page.wait_for_timeout(600)

        elif action == "fill":
            if not value:
                return TeachResponse(ok=False, error="'value' is required for fill action")
            is_xpath = selector.startswith("/") or selector.startswith("(//")
            loc = page.locator(f"xpath={selector}") if is_xpath else page.locator(selector)
            await loc.first.fill(value, timeout=8000)

        elif action == "navigate":
            url = selector if selector.startswith("http") else value
            if not url:
                return TeachResponse(ok=False, error="'selector' or 'value' must be a full URL for navigate")
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)

        screenshot_b64 = await capture_screenshot_b64(page)
        logger.info("[%s] Teach: action '%s' on '%s' executed successfully", run_id, action, selector[:60])

    except Exception as _exec_err:
        logger.error("[%s] Teach execution error: %s", run_id, _exec_err)
        try:
            screenshot_b64 = await capture_screenshot_b64(page)
        except Exception:
            pass
        return TeachResponse(ok=False, screenshot_b64=screenshot_b64, error=str(_exec_err)[:200])

    # ── 3. Persist to selector_registry.json ────────────────────────
    kb_written = False
    try:
        from backend.kb.selector_registry import selector_registry

        trigger_text = ac_step or description
        selector_registry.record_hitl_selector(
            trigger_text=trigger_text,
            selector_value=selector,
            action_hint=action,
        )
        logger.info("[%s] Teach: selector '%s' written to registry", run_id, selector[:60])
        kb_written = True
    except Exception as _reg_err:
        logger.warning("[%s] Teach: registry write failed (non-fatal): %s", run_id, _reg_err)

    # ── 4. Append to human_guidance.md ───────────────────────────────
    _guidance_note = f"- Confirmed action: `{action}` on `{selector}`" + (f" with value `{value}`" if value else "")
    try:
        from pathlib import Path

        guidance_path = Path(__file__).parent.parent.parent / "knowledge" / "human_guidance.md"
        heading = ac_step or description[:60]
        entry = (
            f"\n\n## {heading}\n\n"
            f"**Selector:** `{selector}`  \n"
            f"**Action:** {action}" + (f" · value: `{value}`" if value else "") + "  \n"
            f"**When:** During HITL teach session for run `{run_id}`  \n"
            f"**Description:** {description}  \n"
        )
        with open(guidance_path, "a", encoding="utf-8") as _gf:
            _gf.write(entry)
        logger.info("[%s] Teach: guidance appended to human_guidance.md", run_id)
        kb_written = True
    except Exception as _guidance_err:
        logger.warning("[%s] Teach: guidance write failed (non-fatal): %s", run_id, _guidance_err)

    return TeachResponse(ok=True, screenshot_b64=screenshot_b64, kb_written=kb_written)


@router.post(
    "/runs/{run_id}/human-takeover/done",
    summary="Signal that human has completed the stuck step",
    description=(
        "Resumes the paused LangGraph run. If skip=true, the current AC step "
        "is marked SKIPPED and the agent advances to the next step."
    ),
)
async def human_takeover_done(run_id: str, req: HumanTakeoverDoneRequest) -> dict:
    """Resume the agent after human manual intervention."""
    if run_id not in _run_states:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    # ── FIX 2: Enforce non-empty explanation when no clicks were captured ──────
    # If the JS click-capture listener recorded zero actions, the explanation
    # field is the ONLY signal we have for the planner.  Accepting an empty
    # explanation produces a zero-information null intervention that teaches
    # the agent nothing and leaves the next retry with no guidance.
    #
    # Exception: if the frontend has already captured a click sequence via the
    # JS listener (stored in human_takeover._human_action_sequence), the
    # explanation is optional — the actions speak for themselves.
    if not req.skip and not req.explanation.strip():
        from backend.engine.human_takeover import _human_action_sequence

        captured = _human_action_sequence.get(run_id, [])
        if not captured:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": "explanation_required",
                    "detail": (
                        "No browser actions were captured by the click-capture listener. "
                        "Please describe what you did in the Explanation field before clicking Done. "
                        "This is how the agent learns from your intervention."
                    ),
                },
            )

    if req.skip:
        ok = skip_takeover(run_id)
    else:
        ok = complete_takeover(run_id, explanation=req.explanation)

    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=f"Run '{run_id}' is not waiting for human takeover")

    logger.info("[%s] Human takeover signal received (skip=%s)", run_id, req.skip)
    return {"ok": True, "skip": req.skip}


@router.post(
    "/runs/{run_id}/human-takeover/skip",
    summary="Skip the current stuck AC step (alias for done with skip=true)",
    description=(
        "Convenience alias for POST /runs/{run_id}/human-takeover/done with skip=true. "
        "Advances the run to the next AC step without requiring a human action."
    ),
)
async def human_takeover_skip(run_id: str) -> dict:
    """Skip the current HITL step and advance the agent to the next AC step."""
    if run_id not in _run_states:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    ok = skip_takeover(run_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=f"Run '{run_id}' is not waiting for human takeover")

    logger.info("[%s] Human takeover step SKIPPED (via /skip alias)", run_id)
    return {"ok": True, "skip": True}


@router.post(
    "/runs/{run_id}/human-takeover/dialog",
    summary="Respond to an intercepted browser dialog",
    description="Accepts or dismisses a native alert/confirm/prompt dialog captured during takeover.",
)
async def human_takeover_dialog(run_id: str, req: HitlDialogResponseRequest) -> dict:
    """Respond to an intercepted browser dialog."""
    from backend.engine.human_takeover import handle_dialog_response

    ok = await handle_dialog_response(run_id, accept=req.accept, prompt_text=req.prompt_text)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404, detail=f"No pending browser dialog found for run '{run_id}'"
        )

    return {"ok": True, "run_id": run_id}


@router.get(
    "/runs/{run_id}/human-takeover/status",
    summary="Check if a run is currently waiting for human takeover",
)
async def human_takeover_status(run_id: str) -> dict:
    """Returns waiting status and the current AC step text."""
    waiting = is_waiting(run_id)
    ac_step = get_takeover_step(run_id) if waiting else ""
    return {"run_id": run_id, "waiting": waiting, "ac_step": ac_step}


@router.post(
    "/runs/{run_id}/persona-credentials",
    response_model=PersonaCredentialsResponse,
    summary="Submit credentials for an unrecognised persona (HITL gate)",
    description=(
        "Called by the operator when the agent encounters an unknown persona during "
        "a PERSONA_SWITCH step and broadcasts HITL_PERSONA_CREDENTIALS_REQUIRED. "
        "Stores the credentials ephemerally (in-memory only) and unblocks the "
        "waiting persona_switch_node. Credentials are NEVER written to disk."
    ),
)
async def submit_persona_credentials(
    run_id: str,
    req: PersonaCredentialsRequest,
) -> PersonaCredentialsResponse:
    """
    Provide operator credentials for an unknown persona mid-test.

    Security
    --------
    - Credentials are stored in-memory only (_persona_creds dict in persona_switch_node)
    - They are purged when the run completes via clear_run_creds(run_id)
    - Password is NEVER echoed in the response body
    - Passwords are scrubbed from logs by the existing log-scrubber pattern
    """
    from fastapi import HTTPException

    if run_id not in _run_states:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found.",
        )

    set_persona_credentials(
        run_id,
        req.persona_name,
        req.email,
        req.password,
    )

    logger.info(
        "[%s] Persona credentials submitted for persona '%s' (email=%s...)",
        run_id,
        req.persona_name,
        req.email[:8] if req.email else "",
    )

    return PersonaCredentialsResponse(ok=True)


@router.post(
    "/runs/{run_id}/ghost-credentials",
    response_model=GhostCredentialsResponse,
    summary="Submit Admin credentials for Ghost Login (impersonation)",
    description=(
        "Called by the operator when the agent encounters a GHOST_LOGIN step "
        "or during pre-flight warning and broadcasts GHOST_CREDENTIALS_REQUIRED. "
        "Stores the credentials ephemerally and unblocks the waiting node."
    ),
)
async def submit_ghost_credentials(
    run_id: str,
    req: GhostCredentialsRequest,
) -> GhostCredentialsResponse:
    """Provide operator Admin credentials for Ghost Login impersonation."""
    from fastapi import HTTPException

    if run_id not in _run_states:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found.",
        )

    set_ghost_credentials(
        run_id,
        req.email,
        req.password,
        req.sso_token,
    )

    logger.info(
        "[%s] Admin credentials submitted for Ghost Login (email=%s...)",
        run_id,
        req.email[:8] if req.email else "",
    )

    return GhostCredentialsResponse(ok=True)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@ws_router.websocket("/ws/{run_id}")
async def websocket_log_stream(websocket: WebSocket, run_id: str) -> None:
    """
    WebSocket endpoint for real-time execution log streaming.

    The React dashboard connects here to receive per-action updates
    as the agent executes.  Messages are ``WSStepMessage`` JSON objects
    for each action, and a ``WSTerminalMessage`` when the run completes.

    Args
    ----
    websocket : WebSocket
        The incoming WebSocket connection.
    run_id : str
        The run to subscribe to.
    """
    # ------------------------------------------------------------------
    # Phase 2: Session-based cross-user protection (AC-ERROR-3)
    # If the run has a session_id, the caller's vqa_session cookie MUST
    # match.  Anonymous access (no cookie) to session-gated runs is also
    # rejected.  Runs without a session_id (pre-refactor) are unaffected.
    # ------------------------------------------------------------------
    import inspect as _inspect
    import os as _os
    _cookie_name = _os.environ.get("SESSION_COOKIE_NAME", "vqa_session")
    _caller_session_id = websocket.cookies.get(_cookie_name)
    try:
        _get_result = _run_states.get(run_id)
        _run_meta = await _get_result if _inspect.isawaitable(_get_result) else _get_result
    except Exception:
        _run_meta = None
    if _run_meta and isinstance(_run_meta, dict) and _run_meta.get("session_id"):
        _expected_session_id = _run_meta["session_id"]
        if _caller_session_id != _expected_session_id:
            await websocket.accept()
            logger.warning(
                '{"event": "ws.cross_user_rejected", "run_id": "%s", '
                '"owning_session": "%s", "attempted_by_session": "%s"}',
                run_id, _expected_session_id, _caller_session_id or "(none)",
            )
            await websocket.close(code=4401, reason="cross_user_attach_rejected")
            return

    await websocket.accept()
    logger.info("[WS] Client connected for run '%s'", run_id)

    # Register connection
    if run_id not in _ws_connections:
        _ws_connections[run_id] = []
    _ws_connections[run_id].append(websocket)

    # ---------------------------------------------------------------------------
    # Playwright pre-connect buffer flush
    # ---------------------------------------------------------------------------
    # If a Playwright subprocess started and finished (or sent output) BEFORE
    # this WebSocket connected, the messages were buffered in
    # playwright_routes._playwright_msg_buffer.  Flush them now so nothing
    # is silently dropped due to the HTTP-response → WS-connect race.
    try:
        from backend.api.playwright_routes import flush_playwright_buffer  # noqa: PLC0415

        buffered = flush_playwright_buffer(run_id)
        if buffered:
            logger.info("[WS] Flushing %d buffered Playwright message(s) for run '%s'", len(buffered), run_id)
            for entry in buffered:
                if entry.get("_terminal"):
                    # Final completed/failed message — send and close
                    await websocket.send_text(entry["_msg_json"])
                    await websocket.close()
                    _ws_connections.pop(run_id, None)
                    return
                else:
                    # terminal_log line — strip internal _ts key before sending
                    payload = {k: v for k, v in entry.items() if not k.startswith("_")}
                    await websocket.send_text(json.dumps(payload))
    except Exception as _buf_err:
        logger.warning("[WS] Buffer flush failed for run '%s': %s", run_id, _buf_err)

    # If the run already reached a terminal state, send final state immediately.
    # LangGraph runs land on "completed"/"failed". CU runs land on the raw
    # terminal_status ("done"→"completed", plus stuck/cap/timeout/cost_cap/
    # cancelled/help/error) — treat anything that isn't "running" as terminal
    # so the report URL always reaches a reconnecting client.
    if run_id in _run_states and _run_states[run_id]["status"] != "running":
        run = _run_states[run_id]
        state = run.get("state", {}) or {}
        engine = run.get("engine")

        if engine == "computer_use":
            # CU runs record per-step status in result.step_state — derive
            # pass counts from there rather than the LangGraph shape.
            result = run.get("result", {}) or {}
            step_state_list = result.get("step_state") or []
            ac_passed_ct = sum(1 for s in step_state_list if s.get("status") == "passed")
            ac_total_ct = len(step_state_list)
            terminal_type = "completed" if result.get("terminal_status") == "done" else "failed"
            await websocket.send_text(
                WSTerminalMessage(
                    type=terminal_type,
                    run_id=run_id,
                    report_url=state.get("s3_report_url", ""),
                    video_url=state.get("s3_video_url", ""),
                    error=run.get("error") or "",
                    ac_steps_passed=ac_passed_ct,
                    ac_steps_total=ac_total_ct,
                ).model_dump_json()
            )
        elif run["status"] == "completed":
            ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
            ac_passed = state.get("ac_steps_completed", [])
            bugs = state.get("bug_log", [])
            _ws_passed_set = set(ac_passed)
            all_passed = len(ac_steps) > 0 and all(i in _ws_passed_set for i in range(len(ac_steps))) and len(bugs) == 0
            _unique_ac_passed = sum(1 for i in range(len(ac_steps)) if i in _ws_passed_set)
            await websocket.send_text(
                WSTerminalMessage(
                    type="completed" if all_passed else "failed",
                    run_id=run_id,
                    report_url=state.get("s3_report_url", ""),
                    video_url=state.get("s3_video_url", ""),
                    ac_steps_passed=_unique_ac_passed,
                    ac_steps_total=len(ac_steps),
                    bugs_found=len(bugs),
                ).model_dump_json()
            )
        else:
            await websocket.send_text(
                WSTerminalMessage(
                    type="failed",
                    run_id=run_id,
                    error=run.get("error", ""),
                ).model_dump_json()
            )

        await websocket.close()
        return

    # Keep connection alive until the run completes or client disconnects
    try:
        while True:
            # Wait for client messages
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
                if msg_data.get("type") == "verifier_correction":
                    # TASK-083: Human correction loop
                    # Inject the correction into the LangGraph state
                    ac_idx = msg_data.get("ac_step_index")
                    reason = msg_data.get("reason", "User marked as satisfied")

                    logger.info("[%s] WS: Received verifier_correction for AC step %d", run_id, ac_idx + 1)

                    # Use aupdate_state to inject the correction into the graph's memory
                    graph = build_graph(checkpointer=_memory_checkpointer)
                    config = {"configurable": {"thread_id": run_id}}
                    await graph.aupdate_state(
                        config,
                        {"verifier_correction": {"ac_step_index": ac_idx, "reason": reason}}
                    )
            except json.JSONDecodeError:
                pass # Ignore malformed pings
            except Exception as e:
                logger.error("[%s] WS message handler error: %s", run_id, e)
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected for run '%s'", run_id)
        # Clean up connection
        connections = _ws_connections.get(run_id, [])
        if websocket in connections:
            connections.remove(websocket)


# ---------------------------------------------------------------------------
# Codegen Demo Recording endpoints
# ---------------------------------------------------------------------------


@router.post("/codegen/start")
async def codegen_start(
    body: CodegenStartRequest,
    request: Request,
):
    from backend.engine.codegen_session import (
        _sessions,
        cancel_session,
        start_session,
        monitor_session,
    )

    # Kill any stale sessions so only one playwright codegen is running at a time.
    for stale_id in list(_sessions.keys()):
        logger.info("[codegen] Cancelling stale session %s", stale_id)
        await cancel_session(stale_id)

    session_id = f"codegen-{uuid.uuid4().hex[:12]}"

    await start_session(
        session_id=session_id,
        ticket_id=body.ticket_id,
        ticket_summary=body.ticket_summary,
        target_url=body.target_url,
    )

    # Launch the monitor as a background task; it broadcasts "recording_done"
    # (or "error") over the WebSocket when the user closes the browser.
    asyncio.create_task(monitor_session(session_id))

    host = request.headers.get("host", "localhost").split(":")[0]
    proto_ws = "wss" if request.url.scheme == "https" else "ws"
    stream_url = f"{proto_ws}://{host}:{settings.api_port}/ws/codegen/{session_id}"

    return CodegenStartResponse(
        session_id=session_id,
        stream_url=stream_url,
        novnc_url=vnc_builder.build_url(request, "interactive"),
    )


@router.post("/codegen/{session_id}/cancel")
async def codegen_cancel(session_id: str):
    from backend.engine.codegen_session import cancel_session

    await cancel_session(session_id)
    return {"ok": True}


@router.post("/codegen/{session_id}/finish")
async def codegen_finish(session_id: str):
    from backend.engine.codegen_session import finish_session

    return await finish_session(session_id)


@router.post("/codegen/{session_id}/confirm-pr")
async def codegen_confirm_pr(session_id: str):
    from backend.engine.codegen_session import confirm_pr as _confirm_pr

    return await _confirm_pr(session_id)


@router.post("/codegen/{session_id}/skip-pr")
async def codegen_skip_pr(session_id: str):
    from backend.engine.codegen_session import skip_pr as _skip_pr

    return await _skip_pr(session_id)


@ws_router.websocket("/ws/codegen/{codegen_id}")
async def codegen_ws(websocket: WebSocket, codegen_id: str):
    # Phase 2: path variable renamed from session_id → codegen_id to
    # disambiguate from the vqa_session cookie (AC-ERROR-4 avoidance).
    session_id = codegen_id  # internal alias for codegen_session compatibility
    from backend.engine.codegen_session import _sessions, _ws_clients

    await websocket.accept()
    clients = _ws_clients.setdefault(session_id, set())
    clients.add(websocket)
    try:
        await websocket.send_json({"type": "connected", "session_id": session_id})

        # If the monitor already finished before the WS connected, replay the result.
        state = _sessions.get(session_id)
        if state and state.status in ("done", "error") and state.result is not None:
            event = {"type": "recording_done", **state.result}
            await websocket.send_json(event)

        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        clients.discard(websocket)


# ---------------------------------------------------------------------------
# Computer-Use loop (feature/computer-use-loop, additive — separate from /execute)
# ---------------------------------------------------------------------------
#
# POST /execute-cu runs a minimal screenshot→LLM→tool loop against the browser,
# reusing Jira fetch, browser lifecycle, ghost login, and HITL takeover but
# bypassing the entire LangGraph pipeline (planner/executor/verifier/critic/
# reflex/recovery_router/kb/ac_parser). See backend/engine/computer_use/.

from pydantic import BaseModel as _CUBaseModel, Field as _CUField


class ExecuteCURequest(_CUBaseModel):
    """Request payload for POST /execute-cu."""

    jira_ticket_id: str = _CUField(..., description="Jira ticket key, e.g. QA-359")
    target_url: str = _CUField(..., description="Product URL to drive")
    admin_email: str = _CUField(
        default="",
        description=(
            "Login email. When empty, the backend resolves credentials from "
            "`user_role` via the role registry (KB → env fallback). Explicit "
            "values here take precedence — e.g. Ghost Login admin creds or "
            "user-supplied Custom Credentials."
        ),
    )
    admin_password: str = _CUField(
        default="",
        description="Login password. Paired with `admin_email` — see that field.",
    )
    user_role: Optional[str] = _CUField(
        None,
        description=(
            "Test-As role key (e.g. 'account_executive'). Used to look up "
            "credentials from the role registry when `admin_email` is empty."
        ),
    )
    product: Optional[str] = _CUField(None, description="Product slug (vpromotions, vpromedia, ...)")
    # Iteration + wall-clock caps are safety nets against runaway loops.
    # Enterprise SPAs (see QA-359) legitimately need 100+ iterations for
    # full form-filling, so defaults + upper bounds are generous.
    # Runtime env overrides live on the runner:
    # VQA_CU_MAX_ITERATIONS, VQA_CU_MAX_WALL_SECONDS.
    max_iterations: int = _CUField(300, ge=1, le=1000)
    max_wall_seconds: int = _CUField(3600, ge=60, le=14400)
    override_steps: list[str] = _CUField(
        default_factory=list,
        description=(
            "Numbered AC steps from /preview-steps. Passed to the runner so "
            "it can emit ac_progress WebSocket updates that line up with the "
            "step rows the frontend renders. Empty list = no step progress "
            "broadcasts."
        ),
    )


class ExecuteCUResponse(_CUBaseModel):
    run_id: str
    status: str
    stream_url: str
    novnc_url: str | None = None


async def _upload_cu_artifacts(
    run_id: str,
    ticket_id: str,
    result: dict,
) -> tuple[dict[int, str], str, str]:
    """
    After a CU run ends, hoist artifacts from the on-disk transcript dir
    to S3 so the HTML report can reference CDN URLs (small, cacheable,
    shareable) instead of embedded base64 (~5-6 MB per report).

    Uploads:
      1. Each ``{iter:03d}_screenshot.png`` in the transcript dir → PNG
         under ``/screenshots/{run_id}/``. Map iter_idx → S3 URL.
      2. The session ``.webm`` video, if the runner reported a video_path,
         via the existing ``upload_video`` helper (same key layout as
         LangGraph). Video path is deleted after successful upload.

    Every upload is best-effort — a per-artifact exception logs at WARN
    and skips that artifact. A hard S3 outage falls back to base64-embed
    at render time (screenshot_urls={}, video_url="").

    Returns
    -------
    (screenshot_urls, video_url, error_summary)
        screenshot_urls : dict[int, str] — iter_idx → S3 URL (may be empty)
        video_url       : str            — S3 URL of the session video ("" on failure/absent)
        error_summary   : str            — non-empty when uploads failed and the caller
                                           should note it in the report metadata
    """
    from pathlib import Path

    from backend.engine.computer_use.runner import _transcript_dir as _cu_dir
    from backend.storage.s3 import upload_cu_screenshot, upload_video

    screenshot_urls: dict[int, str] = {}
    video_url = ""
    errors: list[str] = []

    # Video first — one upload, biggest artifact, most useful even if the
    # screenshot walk fails halfway.
    video_path_raw = result.get("video_path")
    if video_path_raw:
        try:
            vp = Path(video_path_raw)
            if vp.exists():
                video_url = await upload_video(video_path=vp, run_id=run_id, ticket_id=ticket_id)
        except Exception as e:
            errors.append(f"video: {e}")
            logger.warning("[%s] CU video upload failed: %s", run_id, e)

    # Screenshots — walk the transcript dir. Missing dir (early crash) is fine.
    try:
        d = _cu_dir(run_id)
        if d and d.is_dir():
            import re as _re
            pat = _re.compile(r"^(\d{3})_screenshot\.png$")
            files = sorted(p for p in d.iterdir() if pat.match(p.name))
            for p in files:
                m = pat.match(p.name)
                if not m:
                    continue
                idx = int(m.group(1))
                try:
                    png_bytes = p.read_bytes()
                    url = await upload_cu_screenshot(png_bytes, run_id, idx)
                    screenshot_urls[idx] = url
                except Exception as e:
                    errors.append(f"iter {idx}: {e}")
                    logger.warning("[%s] CU screenshot upload failed at iter %d: %s", run_id, idx, e)
            logger.info(
                "[%s] CU uploaded %d/%d screenshots to S3",
                run_id, len(screenshot_urls), len(files),
            )
    except Exception as e:
        errors.append(f"screenshot walk: {e}")
        logger.warning("[%s] CU screenshot upload sweep failed: %s", run_id, e)

    err_summary = "; ".join(errors) if errors else ""
    return screenshot_urls, video_url, err_summary


def _emergency_cu_report(
    *,
    run_id: str,
    ticket_id: str,
    product: str,
    result: dict | None,
    render_exc: BaseException | None = None,
    outer_exc: BaseException | None = None,
) -> str:
    """
    Absolute-minimum HTML for when `render_cu_report` itself throws.

    Depends only on stdlib string ops + html.escape — no import of the
    report module, no template engine, no CSS assumptions. If this
    function raises, the run is truly unrecoverable and there's nothing
    we can serve; that has never been observed and would indicate a
    Python-runtime-level issue.

    Called by `_safe_render_cu_report` after the primary renderer fails.
    Serves as the guarantee that "every CU run leaves a report on S3
    and at /runs/{run_id}/report" holds even when the report module is
    broken.
    """
    import html as _html_mod

    result = result or {}
    terminal = str(result.get("terminal_status") or "error")
    err = str(result.get("error") or "")
    summary = str(result.get("final_summary") or "")
    stuck_reason = str(result.get("stuck_reason") or "")

    def esc(s: object) -> str:
        return _html_mod.escape(str(s) if s is not None else "")

    body_bits: list[str] = [
        f"<h1>vQA CU Run — {esc(ticket_id or run_id)}</h1>",
        f"<p>run <code>{esc(run_id)}</code> · product <strong>{esc(product or '—')}</strong></p>",
        f"<p><strong>Terminal status:</strong> {esc(terminal.upper())}</p>",
    ]
    if summary:
        body_bits.append(f"<p><strong>Summary:</strong> {esc(summary)}</p>")
    if stuck_reason:
        body_bits.append(f"<p><strong>Reason:</strong> {esc(stuck_reason)}</p>")
    if err:
        body_bits.append(f"<p><strong>Error:</strong> {esc(err)}</p>")
    if render_exc is not None:
        body_bits.append(
            "<p><em>Note: the full audit report could not be generated. "
            f"The renderer raised: <code>{esc(repr(render_exc))}</code>. "
            f"See <code>.logs/computer_use/{esc(run_id)}/</code> on the "
            "backend host for the raw transcript.</em></p>"
        )
    if outer_exc is not None:
        body_bits.append(
            "<p><em>Note: the run task itself crashed before completing. "
            f"Exception: <code>{esc(repr(outer_exc))}</code>.</em></p>"
        )

    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>vQA CU Run — {esc(ticket_id or run_id)}</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;"
        "padding:2rem;max-width:800px;color:#111;line-height:1.55}"
        "code{background:#f3f4f6;padding:0.05rem 0.35rem;border-radius:3px;font-size:0.9em}"
        "p{margin:0.5rem 0}</style></head><body>"
        + "".join(body_bits)
        + "</body></html>"
    )


def _safe_render_cu_report(
    *,
    result: dict,
    screenshot_urls: dict[int, str] | None,
    video_url: str,
    run_id: str,
    ticket_id: str,
    product: str,
    outer_exc: BaseException | None = None,
) -> str:
    """
    Wrapper around `render_cu_report` that GUARANTEES a non-empty HTML
    string. On any renderer exception, falls back to `_emergency_cu_report`
    which uses only string concat + html.escape.

    This is the load-bearing guarantee behind "every CU run produces a
    report and uploads it to S3, even on failure." Without this wrapper,
    a bug in the report module (or an unexpected result-dict shape) would
    silently leave state.final_html_report="" and 404 the report endpoint.
    """
    from backend.engine.computer_use.report import render_cu_report

    try:
        html = render_cu_report(
            result,
            screenshot_urls=screenshot_urls or None,
            video_url=video_url,
        )
        if html:
            return html
        # Renderer returned empty — treat as failure and fall through.
        logger.warning("[%s] execute-cu renderer returned empty HTML — using emergency fallback", run_id)
    except Exception as render_err:
        logger.warning(
            "[%s] execute-cu report render failed (%s) — using emergency fallback",
            run_id, render_err,
        )
        return _emergency_cu_report(
            run_id=run_id, ticket_id=ticket_id, product=product,
            result=result, render_exc=render_err, outer_exc=outer_exc,
        )
    # Fallback for the "returned empty string" branch above.
    return _emergency_cu_report(
        run_id=run_id, ticket_id=ticket_id, product=product,
        result=result, outer_exc=outer_exc,
    )


async def _upload_cu_report_safe(
    *, html_report: str, run_id: str, ticket_id: str,
) -> str:
    """
    Best-effort HTML → S3 upload. Never raises. Returns "" on any failure.

    Split out from the two `_execute_cu_run` branches so both branches
    hit the exact same upload path — the success case and the outer-
    exception case cannot diverge in what they persist to S3.
    """
    from backend.storage.s3 import upload_cu_report

    if not html_report:
        return ""
    try:
        return await upload_cu_report(
            html_content=html_report,
            run_id=run_id,
            ticket_id=ticket_id,
        )
    except Exception as e:
        logger.warning("[%s] execute-cu report S3 upload failed: %s", run_id, e)
        return ""


async def _execute_cu_run(run_id: str, request: ExecuteCURequest) -> None:
    """
    Background task — invoke the Computer-Use runner and record the result.

    Invariants (parity with the LangGraph reporter_node):
      1. Every code path ends with a non-empty ``state.final_html_report``.
         The `/runs/{run_id}/report` endpoint MUST never 404 for a CU run
         that made it into `_run_states`.
      2. Every code path attempts to upload the HTML report to S3 via
         `upload_cu_report`. On S3 failure, `state.s3_report_url` is ""
         but `state.final_html_report` still serves the in-memory copy.
      3. Session video and per-turn screenshots are uploaded when
         available; a missing video / partial screenshot walk never
         blocks the HTML report from being produced.

    The invariants hold across all terminal statuses (done / cap / timeout
    / stuck / cost_cap / cancelled / help / error) AND across
    render-side bugs (renderer raising, renderer returning empty). The
    emergency fallback in `_safe_render_cu_report` is the last line of
    defense.
    """
    from backend.engine.computer_use import run_computer_use

    _run_states[run_id] = {
        "status": "running",
        "jira_ticket_id": request.jira_ticket_id,
        "engine": "computer_use",
        "product": request.product,
        "target_url": request.target_url,
        "state": None,
        "error": None,
    }

    result: dict = {}
    outer_exc: BaseException | None = None
    screenshot_urls: dict[int, str] = {}
    video_url: str = ""
    upload_errs: str = ""

    # ── Phase 1: Run the CU loop ────────────────────────────────────
    try:
        result = await run_computer_use(
            ticket_id=request.jira_ticket_id,
            target_url=request.target_url,
            admin_email=request.admin_email,
            admin_password=request.admin_password,
            product=request.product,
            run_id=run_id,
            max_iterations=request.max_iterations,
            max_wall_seconds=request.max_wall_seconds,
            steps=request.override_steps or None,
            user_role=request.user_role,
        )
    except Exception as e:
        # The runner has its own try/except and normally returns
        # result={terminal_status: "error", ...} instead of raising.
        # This path only fires on a truly pathological failure (import
        # error, pre-init crash, event-loop cancellation).
        logger.exception("[%s] execute-cu: run_computer_use raised: %s", run_id, e)
        outer_exc = e
        result = {
            "run_id": run_id,
            "ticket_id": request.jira_ticket_id,
            "product": request.product,
            "terminal_status": "error",
            "error": str(e),
            "step_state": [],
        }

    # ── Phase 2: Upload screenshots + video to S3 (best-effort) ─────
    try:
        screenshot_urls, video_url, upload_errs = await _upload_cu_artifacts(
            run_id, request.jira_ticket_id, result,
        )
    except Exception as e:
        # _upload_cu_artifacts is already best-effort internally; this
        # catches the pathological case where its own bookkeeping throws.
        logger.warning("[%s] execute-cu artifact-upload sweep raised: %s", run_id, e)
        upload_errs = f"artifact sweep raised: {e}"

    # ── Phase 3: Render HTML report (guaranteed non-empty) ──────────
    html_report = _safe_render_cu_report(
        result=result,
        screenshot_urls=screenshot_urls,
        video_url=video_url,
        run_id=run_id,
        ticket_id=request.jira_ticket_id,
        product=request.product,
        outer_exc=outer_exc,
    )

    # ── Phase 4: Upload HTML to S3 (best-effort) ────────────────────
    report_url = await _upload_cu_report_safe(
        html_report=html_report,
        run_id=run_id,
        ticket_id=request.jira_ticket_id,
    )

    # ── Phase 5: Publish final state ────────────────────────────────
    if outer_exc is not None:
        run_status = "error"
        error_payload = str(outer_exc)
    else:
        terminal = result.get("terminal_status")
        run_status = "completed" if terminal == "done" else (terminal or "error")
        error_payload = result.get("error")

    _run_states[run_id] = {
        "status": run_status,
        "jira_ticket_id": request.jira_ticket_id,
        "engine": "computer_use",
        "product": request.product,
        "target_url": request.target_url,
        "result": result,
        "state": {
            "final_html_report": html_report,
            "s3_report_url": report_url,
            "s3_video_url": video_url,
            "s3_screenshot_urls": screenshot_urls,
            "s3_upload_errors": upload_errs,
        },
        "error": error_payload,
    }
    logger.info(
        "[%s] execute-cu finished: status=%s terminal=%s report_url=%s video_url=%s screenshots=%d",
        run_id, run_status, result.get("terminal_status"),
        report_url or "(none)", video_url or "(none)", len(screenshot_urls),
    )

    # Broadcast the terminal message so any WebSocket that stayed connected
    # through the run gets the report URL + video URL and closes cleanly.
    # Without this the frontend sits on "running" until the user reloads —
    # even though the report is already uploaded and _run_states is set.
    # `type` maps done → "completed"; every other terminal status
    # (stuck, cap, timeout, cost_cap, cancelled, help, error) → "failed"
    # so the UI still shows the report card, just under the failure banner.
    step_state_list = result.get("step_state") or []
    ac_passed = sum(1 for s in step_state_list if s.get("status") == "passed")
    ac_total = len(step_state_list)
    terminal_type = "completed" if result.get("terminal_status") == "done" else "failed"
    await _broadcast_terminal(
        run_id,
        WSTerminalMessage(
            type=terminal_type,
            run_id=run_id,
            report_url=report_url or "",
            video_url=video_url or "",
            error=error_payload or "",
            ac_steps_passed=ac_passed,
            ac_steps_total=ac_total,
        ),
    )


@router.post(
    "/execute-cu",
    response_model=ExecuteCUResponse,
    summary="Start a Computer-Use loop run (feature/computer-use-loop)",
    description=(
        "Runs a minimal screenshot→Claude→tool loop against the target URL. "
        "Bypasses the full LangGraph pipeline. Reuses Jira fetch, browser "
        "lifecycle (with video recording), ghost login primitives, and HITL "
        "takeover for fallback."
    ),
)
async def execute_cu(request: ExecuteCURequest, http_request: Request) -> ExecuteCUResponse:
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Login-path selection:
    #   • If `admin_email` is set (Ghost Login admin creds or user-supplied
    #     Custom Credentials), the runner uses those directly via the manual
    #     form-fill in _do_ghost_login.
    #   • Otherwise, if `user_role` is set, the runner delegates to
    #     `ensure_role_authenticated(role)` — the same helper web_surfer and
    #     switch_actor use — which pulls credentials from the role registry
    #     (KB → env → profile fallback) and opens the browser with a valid
    #     Playwright storage state (no manual form fill).
    # This lets the "Test As" dropdown drive login without requiring the user
    # to enable Ghost Login or Custom Credentials first.
    if not request.admin_email and not request.user_role:
        raise HTTPException(
            status_code=400,
            detail=(
                "No login path available. Provide 'user_role' (from the 'Test As' "
                "dropdown) or 'admin_email'/'admin_password' (Ghost Login or "
                "Custom Credentials)."
            ),
        )
    logger.info(
        "[%s] execute-cu: login path = %s",
        run_id,
        "explicit-admin-creds" if request.admin_email else f"role[{request.user_role}]",
    )

    logger.info(
        "POST /execute-cu — ticket=%s product=%s → run_id=%s",
        request.jira_ticket_id, request.product, run_id,
    )

    asyncio.create_task(_execute_cu_run(run_id, request))

    host = http_request.headers.get("host", "localhost").split(":")[0]
    proto_ws = "wss" if http_request.url.scheme == "https" else "ws"
    stream_url = f"{proto_ws}://{host}:{settings.api_port}/ws/{run_id}"
    novnc_url = vnc_builder.build_url(http_request, "interactive")

    return ExecuteCUResponse(
        run_id=run_id,
        status="running",
        stream_url=stream_url,
        novnc_url=novnc_url,
    )


# ---------------------------------------------------------------------------
# Save-as-Playwright-test — turns a successful CU run into a .spec.ts file.
# Only allowed on terminal_status == "done" runs. Emits .spec.ts (WIP per
# the playwright/CLAUDE.md convention) so the file is ignored by the
# default runner until a human reviews and promotes it to .test.ts.
# ---------------------------------------------------------------------------


class SaveRunAsTestRequest(_CUBaseModel):
    """Request payload for POST /run/{run_id}/save-as-test."""

    name: str = _CUField(
        ...,
        min_length=1,
        max_length=200,
        description="Human-provided test name; sanitized via slugify before use as a filename.",
    )
    product: Optional[str] = _CUField(
        None,
        description=(
            "Product slug (vpromotions, vpromedia, ...) — used as the "
            "subdirectory under playwright/tests/. Falls back to the "
            "product stored on the run when omitted."
        ),
    )
    user_role: str = _CUField(
        "Admin",
        description="Playwright test.use({ user }) role — defaults to Admin.",
    )


class SaveRunAsTestResponse(_CUBaseModel):
    slug: str
    file_path: str
    click_at_count: int
    tool_call_count: int
    # Populated when the saved test is auto-committed and a PR is opened.
    # `pr_error` is set when PR creation was attempted but failed (e.g.,
    # missing GITHUB_TOKEN) — the file is still saved to disk in that case.
    pr_url: str | None = None
    branch: str | None = None
    commit_hash: str | None = None
    pr_error: str | None = None


@router.post(
    "/run/{run_id}/save-as-test",
    response_model=SaveRunAsTestResponse,
    summary="Persist a completed Computer-Use run as a Playwright .spec.ts",
)
async def save_run_as_test(run_id: str, request: SaveRunAsTestRequest) -> SaveRunAsTestResponse:
    from datetime import datetime, timezone
    from pathlib import Path

    from backend.engine.computer_use.test_codegen import (
        generate_playwright_test,
        resolve_test_path,
        slugify,
    )

    run_state = _run_states.get_sync(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail=f"Unknown run_id {run_id!r}")

    result = run_state.get("result") or {}
    terminal_status = result.get("terminal_status")
    if terminal_status != "done":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run {run_id!r} did not complete successfully "
                f"(terminal_status={terminal_status!r}). Only successful "
                f"runs can be saved as tests."
            ),
        )

    product = (request.product or run_state.get("product") or "misc").strip() or "misc"
    ticket_id = run_state.get("jira_ticket_id") or run_id
    target_url = run_state.get("target_url") or ""

    slug = slugify(request.name)

    # Resolve the on-disk path BEFORE running the (potentially expensive)
    # LLM-backed codegen — this way a bad product / permissions failure
    # fails fast without burning Bedrock spend. Repo root = three levels
    # up from this module (backend/api/routes.py → repo root).
    repo_root = Path(__file__).resolve().parent.parent.parent
    playwright_tests_root = repo_root / "playwright" / "tests"
    playwright_utils_root = repo_root / "playwright" / "utils"
    try:
        target_path = resolve_test_path(playwright_tests_root, product, slug)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute the relative path from the generated test file back to utils/setup.
    # e.g. playwright/tests/vppo/qa-363-foo.test.ts -> ../../utils/setup
    try:
        setup_ts = playwright_utils_root / "setup.ts"
        rel = target_path.parent.relative_to(playwright_tests_root)
        depth = len(rel.parts)  # 1 for tests/vppo, 0 for tests/
        setup_import_path = "../" * depth + "../utils/setup"
    except ValueError:
        setup_import_path = "../../utils/setup"  # safe fallback

    # Look up playwright_base_url from products.yaml for cross-domain products.
    # These are products (like vPPO) whose app lives on a different domain from
    # the Angular SSO gateway. When present, we emit the named constant instead
    # of the raw SSO URL so tests navigate to the actual application.
    playwright_base_url = ""
    product_url_constant = ""
    try:
        from backend.config.product_registry import load_product_registry
        registry = load_product_registry()
        prod_cfg = registry.products.get(product)
        if prod_cfg:
            pb_map = getattr(prod_cfg, "playwright_base_url", None) or {}
            # Use the environment that matches the run's target_url, or default
            env_key = (run_state.get("environment") or prod_cfg.default_environment or "")
            playwright_base_url = pb_map.get(env_key) or next(iter(pb_map.values()), "")
            if playwright_base_url:
                # Derive a TS constant name: vppo -> VPPO_BASE_URL
                product_url_constant = f"{product.upper()}_BASE_URL"
                logger.info(
                    "[%s] save-as-test: cross-domain product %r — using playwright_base_url=%r (constant %s)",
                    run_id, product, playwright_base_url, product_url_constant,
                )
    except Exception as e:
        logger.warning("[%s] save-as-test: could not load playwright_base_url from registry: %s", run_id, e)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    logger.info(
        "[%s] save-as-test: name=%r → slug=%r product=%r path=%s",
        run_id, request.name, slug, product, target_path,
    )

    try:
        source = await generate_playwright_test(
            run_id=run_id,
            ticket_id=ticket_id,
            ac_summary=request.name,
            target_url=target_url,
            generated_at_iso=generated_at,
            user_role=request.user_role,
            playwright_base_url=playwright_base_url,
            product_url_constant=product_url_constant,
            setup_import_path=setup_import_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[%s] save-as-test: codegen failed: %s", run_id, e)
        raise HTTPException(status_code=500, detail=f"Codegen failed: {e}")

    target_path.write_text(source, encoding="utf-8")

    # Automatically sync index so new test is immediately visible in Playwright UI dropdown
    try:
        from scripts.sync_playwright_index import sync_playwright_index
        sync_playwright_index()
    except Exception as e:
        logger.warning("[%s] save-as-test: sync_playwright_index failed (%s)", run_id, e)

    # Repost some quick stats so the frontend can show a summary
    # ("28 tool calls translated, 6 click_at pixel clicks replaced with
    # selectors") without needing a second round-trip.
    click_at_count = source.count("// was click_at(")
    tool_call_count = source.count("await page.")

    # Auto-open a PR for the saved test — same shape as the record-demo flow.
    # PR failure does NOT fail the save: the file is on disk, and the user
    # can commit manually. We surface the error string in `pr_error` so the
    # UI can display it inline.
    pr_url: str | None = None
    branch: str | None = None
    commit_hash: str | None = None
    pr_error: str | None = None
    try:
        from backend.engine.github_pr import commit_files_and_open_pr, read_file_for_commit

        pr_title = f"test(cu): {ticket_id} — {request.name}"[:120]
        pr_body = (
            f"## Computer-Use Saved Test\n\n"
            f"**Ticket:** [{ticket_id}](https://vcreative.atlassian.net/browse/{ticket_id})\n"
            f"**Run:** `{run_id}`\n"
            f"**Product:** `{product}`\n\n"
            f"This test was generated from a successful Computer-Use run. It captures the "
            f"actual interactions the agent performed and translates them into Playwright "
            f"calls (with LLM-inferred selectors for pixel-based `click_at` calls).\n\n"
            f"### Review Checklist\n"
            f"- [ ] Verify any `TODO(codegen)` comments and replace pixel clicks ({click_at_count} inferred selectors)\n"
            f"- [ ] Run once locally against `TEST_ENV=test` to confirm correctness\n"
            f"- [ ] Any hardcoded entity names/IDs replaced with test data\n"
        )
        commit_msg = (
            f"test(cu): add saved CU run for {ticket_id}\n\n"
            f"{request.name}\n\n"
            f"Run: {run_id}"
        )
        commit_result = await commit_files_and_open_pr(
            files=[read_file_for_commit(target_path, repo_root)],
            branch_prefix="cu-save",
            branch_key=ticket_id,
            commit_message=commit_msg,
            pr_title=pr_title,
            pr_body=pr_body,
        )
        pr_url = commit_result["pr_url"]
        branch = commit_result["branch"]
        commit_hash = commit_result["commit_hash"]
        logger.info(
            "[%s] save-as-test: PR opened %s (branch=%s)", run_id, pr_url, branch,
        )
    except Exception as e:
        # Non-fatal: file is already on disk.
        logger.warning("[%s] save-as-test: PR creation failed (%s)", run_id, e)
        pr_error = str(e)

    return SaveRunAsTestResponse(
        slug=slug,
        file_path=str(target_path.relative_to(repo_root)),
        click_at_count=click_at_count,
        tool_call_count=tool_call_count,
        pr_url=pr_url,
        branch=branch,
        commit_hash=commit_hash,
        pr_error=pr_error,
    )
