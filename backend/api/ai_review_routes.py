"""
backend/api/ai_review_routes.py
================================
Run vReview ``npm run ai:review`` from the dashboard.

Endpoints
---------
  POST /ai-review/run                 — Spawn the command and stream via /ws/{run_id}
  POST /ai-review/run/{run_id}/stop   — SIGTERM the subprocess
  GET  /ai-review/rules               — Checklist codes (CQ-01, F-01, …) for one app
  POST /ai-review/rules/propose       — AI-gate a new rule idea (does not save)
  POST /ai-review/rules               — Save a picked wording from a proposal
  GET  /ai-review/history             — List saved reviews (newest first)
  GET  /ai-review/history/{review_id} — One saved review (table + log)

One review at a time. Engine and checklists live in vReview.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
import uuid
from typing import Dict

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    AiReviewHistoryDetail,
    AiReviewHistoryItem,
    AiReviewRunRequest,
    AiReviewRunResponse,
    ReviewRuleProposeRequest,
    ReviewRuleProposeResponse,
    ReviewRuleSaveRequest,
    ReviewRuleSaveResponse,
    ReviewRulesResponse,
    WSTerminalMessage,
)
from backend.engine.ai_review_runner import (
    AiReviewConfigError,
    AiReviewValidationError,
    build_ai_review_argv,
    parse_review_table_row,
    resolve_ai_review_cwd,
    upsert_review_row,
    validate_app,
    validate_commits,
    validate_git_ref,
)
from backend.engine.review_rule_additions import ReviewRuleIdeaError
from backend.engine.review_rule_proposer import propose_review_rule, save_approved_review_rule
from backend.engine.review_rules import ReviewRulesError, load_review_rules
from backend.storage.ai_review_runs import ai_review_run_store

logger = logging.getLogger(__name__)

ai_review_router = APIRouter(prefix="/ai-review", tags=["ai-review"])

MAX_CONCURRENT_AI_REVIEWS = 1
_REVIEW_ID_RE = re.compile(r"^ar-[a-f0-9]{8}$")
_PROPOSAL_ID_RE = re.compile(r"^rp-[a-f0-9]{8}$")
_ai_review_semaphore: asyncio.Semaphore | None = None
_ai_review_pids: Dict[str, int] = {}
_ai_review_force_released: set[str] = set()
_ai_review_stopped: set[str] = set()


def _get_semaphore() -> asyncio.Semaphore:
    """
    Return the process-wide one-review-at-a-time semaphore.

    @returns Shared asyncio semaphore
    """
    global _ai_review_semaphore
    if _ai_review_semaphore is None:
        _ai_review_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AI_REVIEWS)
    return _ai_review_semaphore


@contextlib.asynccontextmanager
async def _semaphore_for_run(run_id: str):
    """
    Hold the review semaphore for the life of one subprocess.

    @param run_id: Dashboard run id (used if Stop already released the slot)
    """
    semaphore = _get_semaphore()
    await semaphore.acquire()
    try:
        yield
    finally:
        if run_id in _ai_review_force_released:
            _ai_review_force_released.discard(run_id)
        else:
            semaphore.release()


def _validate_request(request: AiReviewRunRequest) -> tuple[str, str, str, str]:
    """
    Validate app, branch, base, and commits from the run request.

    @param request: POST body
    @returns Stripped (app, branch, base, commits)
    """
    app = validate_app(request.app)
    branch = validate_git_ref(request.branch, "Branch")
    default_base = "develop" if app == "vcapi" else "Develop"
    base = validate_git_ref(request.base or default_base, "Base branch")
    commits = validate_commits(request.commits or "")
    return app, branch, base, commits


def _require_review_id(review_id: str) -> str:
    """
    Accept only dashboard review ids (ar- + 8 hex chars).

    @param review_id: Path parameter
    @returns The same id when valid
    """
    if not _REVIEW_ID_RE.match(review_id):
        raise HTTPException(status_code=422, detail="Invalid review id")
    return review_id


def _persist_start(run_id: str, branch: str, base: str, commits: str, app: str) -> None:
    """
    Insert a history row for a newly started review.

    @param run_id: Dashboard run id
    @param branch: --branch value
    @param base: --base value
    @param commits: Optional --commits value
    @param app: platform or vcapi
    @returns None
    """
    try:
        ai_review_run_store.create_run(run_id, branch, base, commits, app)
    except Exception:
        logger.exception("[%s] Could not create AI review history row", run_id)


def _persist_finish(
    run_id: str,
    status: str,
    rows: list[dict[str, str]],
    log_lines: list[str],
) -> None:
    """
    Write checklist rows, log, and terminal status for a finished review.

    @param run_id: Dashboard run id
    @param status: completed, failed, or stopped
    @param rows: Parsed checklist rows
    @param log_lines: Captured log lines
    @returns None
    """
    try:
        ai_review_run_store.finish_run(
            review_id=run_id,
            status=status,
            rows=rows,
            log_text="\n".join(log_lines),
        )
    except Exception:
        logger.exception("[%s] Could not save AI review history row", run_id)


@ai_review_router.post(
    "/run",
    response_model=AiReviewRunResponse,
    summary="Run vReview npm run ai:review",
)
async def run_ai_review(request: AiReviewRunRequest) -> AiReviewRunResponse:
    """
    Validate flags, spawn npm run ai:review, and return a WebSocket URL.

    @param request: App, branch, optional commits, base branch
    @returns run_id and websocket_url
    """
    try:
        app, branch, base, commits = _validate_request(request)
        cwd = resolve_ai_review_cwd("")
    except AiReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AiReviewConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    semaphore = _get_semaphore()
    if semaphore._value <= 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=429,
            detail="An AI review is already running. Wait for it to finish.",
        )

    run_id = f"ar-{uuid.uuid4().hex[:8]}"
    _persist_start(run_id, branch, base, commits, app)
    cmd = build_ai_review_argv(branch, base, commits, app)
    asyncio.create_task(_run_ai_review_subprocess(run_id, cmd, cwd))
    logger.info("[%s] AI review started: %s (cwd=%s)", run_id, " ".join(cmd), cwd)
    return AiReviewRunResponse(run_id=run_id, websocket_url=f"/ws/{run_id}")


@ai_review_router.post(
    "/run/{run_id}/stop",
    summary="Stop a running AI review subprocess",
)
async def stop_ai_review(run_id: str) -> dict:
    """
    SIGTERM the tracked subprocess for this run_id.

    @param run_id: Active review id
    @returns status payload
    """
    pid = _ai_review_pids.get(run_id)
    if pid is None:
        raise HTTPException(status_code=404, detail=f"No active review for run_id='{run_id}'")

    _ai_review_stopped.add(run_id)
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("[%s] SIGTERM sent to PID %d", run_id, pid)
    except ProcessLookupError:
        logger.debug("[%s] PID %d already exited", run_id, pid)
    except Exception as exc:
        logger.warning("[%s] Could not SIGTERM PID %d: %s", run_id, pid, exc)

    semaphore = _get_semaphore()
    _ai_review_force_released.add(run_id)
    semaphore.release()
    return {"status": "stopped", "run_id": run_id}


@ai_review_router.get(
    "/rules",
    response_model=ReviewRulesResponse,
    summary="List AI Review checklist codes",
)
async def list_ai_review_rules(app: str = "platform") -> ReviewRulesResponse:
    """
    Return the PR checklist codes and plain-language explanations for one app.

    @param app: platform (vsuitePlatform) or vcapi
    @returns Grouped checklist rules
    """
    try:
        payload = load_review_rules(app)
    except AiReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReviewRulesError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ReviewRulesResponse.model_validate(payload)


@ai_review_router.post(
    "/rules/propose",
    response_model=ReviewRuleProposeResponse,
    summary="Check a new AI Review rule idea",
)
async def propose_ai_review_rule(body: ReviewRuleProposeRequest) -> ReviewRuleProposeResponse:
    """
    Hard-check then AI-gate a rule idea. Does not write the checklist.

    @param body: App, section, idea
    @returns Verdict plus optional wordings
    """
    try:
        payload = await propose_review_rule(
            body.app, body.section, body.other_section, body.idea
        )
    except ReviewRuleIdeaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AiReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReviewRuleProposeResponse.model_validate(payload)


@ai_review_router.post(
    "/rules",
    response_model=ReviewRuleSaveResponse,
    summary="Save a picked AI Review rule wording",
)
async def save_ai_review_rule(body: ReviewRuleSaveRequest) -> ReviewRuleSaveResponse:
    """
    Save one wording from an accepted proposal.

    @param body: Proposal id, wording index, and optional section switch
    @returns Saved rule
    """
    if not _PROPOSAL_ID_RE.match(body.proposal_id):
        raise HTTPException(status_code=422, detail="Invalid proposal id")
    try:
        saved = await save_approved_review_rule(
            body.proposal_id, body.choice, body.use_suggested_section
        )
    except ReviewRuleIdeaError as extra:
        raise HTTPException(status_code=400, detail=str(extra)) from extra
    return ReviewRuleSaveResponse.model_validate(saved)


@ai_review_router.get(
    "/history",
    response_model=list[AiReviewHistoryItem],
    summary="List saved AI reviews",
)
async def list_ai_review_history() -> list[AiReviewHistoryItem]:
    """
    Return recent AI Review runs newest first (no logs).

    @returns History list items
    """
    return [AiReviewHistoryItem.model_validate(item) for item in ai_review_run_store.list_runs()]


@ai_review_router.get(
    "/history/{review_id}",
    response_model=AiReviewHistoryDetail,
    summary="Get one saved AI review",
)
async def get_ai_review_history(review_id: str) -> AiReviewHistoryDetail:
    """
    Return one saved review including the checklist table and log.

    @param review_id: Dashboard run id
    @returns Full history detail
    """
    safe_id = _require_review_id(review_id)
    item = ai_review_run_store.get_run(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No saved review for review_id='{safe_id}'")
    return AiReviewHistoryDetail.model_validate(item)


async def _run_ai_review_subprocess(run_id: str, cmd: list[str], cwd: str | os.PathLike[str]) -> None:
    """
    Execute npm run ai:review and stream stdout/stderr over the existing WS bus.

    @param run_id: Dashboard run id
    @param cmd: Argv from build_ai_review_argv
    @param cwd: vsuitePlatform tool checkout
    @returns None
    """
    from backend.api.playwright_routes import _broadcast, _broadcast_terminal_msg  # noqa: PLC0415
    from backend.api.routes import _run_states  # noqa: PLC0415

    _run_states[run_id] = {
        "status": "running",
        "state": {"final_html_report": ""},
        "error": None,
        "jira_ticket_id": "",
        "role": "",
    }

    rows: list[dict[str, str]] = []
    log_lines: list[str] = []
    exit_code = -1

    async with _semaphore_for_run(run_id):
        logger.info("[%s] Spawning: %s (cwd=%s)", run_id, " ".join(cmd), cwd)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=dict(os.environ),
            )
            if process.pid:
                _ai_review_pids[run_id] = process.pid

            start_line = f"Running: {' '.join(cmd)}"
            log_lines.append(start_line)
            await _broadcast(run_id, start_line, "stdout")

            async def _stream(stream, stream_name: str) -> None:
                if stream is None:
                    return
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").rstrip()
                    if line:
                        log_lines.append(line)
                        parsed = parse_review_table_row(line)
                        if parsed:
                            rows[:] = upsert_review_row(rows, parsed)
                        await _broadcast(run_id, line, stream_name)

            await asyncio.gather(
                _stream(process.stdout, "stdout"),
                _stream(process.stderr, "stderr"),
            )
            exit_code = await process.wait()
        except Exception as exc:
            logger.error("[%s] AI review subprocess error: %s", run_id, exc, exc_info=True)
            error_line = f"Error launching review: {exc}"
            log_lines.append(error_line)
            await _broadcast(run_id, error_line, "stderr")
            exit_code = -1
        finally:
            _ai_review_pids.pop(run_id, None)

        was_stopped = run_id in _ai_review_stopped
        _ai_review_stopped.discard(run_id)
        if was_stopped:
            persist_status = "stopped"
            terminal_type = "failed"
        elif exit_code == 0:
            persist_status = "completed"
            terminal_type = "completed"
        else:
            persist_status = "failed"
            terminal_type = "failed"

        if run_id in _run_states:
            _run_states[run_id]["status"] = terminal_type
            _run_states[run_id]["error"] = "" if exit_code == 0 else f"exit code {exit_code}"

        done_line = f"Review {terminal_type} (exit {exit_code})"
        log_lines.append(done_line)
        _persist_finish(run_id, persist_status, rows, log_lines)
        await _broadcast(
            run_id,
            done_line,
            "stdout" if exit_code == 0 else "stderr",
        )
        await _broadcast_terminal_msg(
            run_id,
            WSTerminalMessage(
                type=terminal_type,
                run_id=run_id,
                error="" if exit_code == 0 else f"exit code {exit_code}",
            ),
        )


async def cleanup_ai_review_processes() -> None:
    """
    SIGTERM tracked AI review subprocesses on server shutdown.

    @returns None
    """
    if not _ai_review_pids:
        return
    for run_id, pid in list(_ai_review_pids.items()):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
    _ai_review_pids.clear()
    _ai_review_stopped.clear()
