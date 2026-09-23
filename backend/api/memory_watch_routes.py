"""
backend/api/memory_watch_routes.py
==================================
Run vReview ``npm run memory:test`` from the dashboard.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.api.schemas import (
    MemoryWatchHistoryDetail,
    MemoryWatchHistoryItem,
    MemoryWatchRunRequest,
    MemoryWatchRunResponse,
    WSTerminalMessage,
)
from backend.engine.ai_review_runner import parse_review_table_row, upsert_review_row
from backend.engine.memory_watch_runner import (
    MemoryWatchConfigError,
    MemoryWatchValidationError,
    build_memory_watch_argv,
    is_memory_watch_run_id,
    kill_memory_watch_pid,
    parse_memory_report_line,
    parse_memory_sample_line,
    parse_memory_verdict_line,
    resolve_memory_watch_cwd,
    validate_cycles,
    validate_env,
    validate_flow,
)
from backend.storage.memory_watch_runs import memory_watch_run_store

logger = logging.getLogger(__name__)

memory_watch_router = APIRouter(prefix="/memory-watch", tags=["memory-watch"])

MAX_CONCURRENT_MEMORY_WATCH = 1
_memory_watch_semaphore: asyncio.Semaphore | None = None
_memory_watch_pids: Dict[str, int] = {}
_memory_watch_force_released: set[str] = set()
_memory_watch_stopped: set[str] = set()


def _get_semaphore() -> asyncio.Semaphore:
    """
    Return the process-wide one-run-at-a-time semaphore.

    @returns Shared asyncio semaphore
    """
    global _memory_watch_semaphore
    if _memory_watch_semaphore is None:
        _memory_watch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_MEMORY_WATCH)
    return _memory_watch_semaphore


@contextlib.asynccontextmanager
async def _semaphore_for_run(run_id: str):
    """
    Hold the Memory Watch semaphore for the life of one subprocess.

    @param run_id: Dashboard run id
    """
    semaphore = _get_semaphore()
    await semaphore.acquire()
    try:
        yield
    finally:
        if run_id in _memory_watch_force_released:
            _memory_watch_force_released.discard(run_id)
        else:
            semaphore.release()


def _validate_request(request: MemoryWatchRunRequest) -> tuple[str, str, int]:
    """
    Validate flow, env, and cycles from the run request.

    @param request: POST body
    @returns (flow, env, cycles)
    """
    flow = validate_flow(request.flow)
    env = validate_env(request.env)
    cycles = validate_cycles(request.cycles)
    return flow, env, cycles


def _require_run_id(run_id: str) -> str:
    """
    Accept only dashboard Memory Watch ids (mw- + 8 hex chars).

    @param run_id: Path parameter
    @returns The same id when valid
    """
    if not is_memory_watch_run_id(run_id):
        raise HTTPException(status_code=422, detail="Invalid memory watch id")
    return run_id


@memory_watch_router.post(
    "/run",
    response_model=MemoryWatchRunResponse,
    summary="Run vReview npm run memory:test",
)
async def run_memory_watch(request: MemoryWatchRunRequest) -> MemoryWatchRunResponse:
    """
    Validate flags, spawn npm run memory:test, and return a WebSocket URL.

    @param request: Flow, env, cycles
    @returns run_id and websocket_url
    """
    try:
        flow, env, cycles = _validate_request(request)
        cwd = resolve_memory_watch_cwd()
    except MemoryWatchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MemoryWatchConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    semaphore = _get_semaphore()
    if semaphore._value <= 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=429,
            detail="A Memory Watch run is already running. Wait for it to finish.",
        )

    run_id = f"mw-{uuid.uuid4().hex[:8]}"
    try:
        memory_watch_run_store.create_run(run_id, flow, env, cycles)
    except Exception:
        logger.exception("[%s] Could not create Memory Watch history row", run_id)
    cmd = build_memory_watch_argv(flow, env, cycles)
    asyncio.create_task(_run_memory_watch_subprocess(run_id, cmd, cwd))
    logger.info("[%s] Memory Watch started: %s (cwd=%s)", run_id, " ".join(cmd), cwd)
    return MemoryWatchRunResponse(run_id=run_id, websocket_url=f"/ws/{run_id}")


@memory_watch_router.post(
    "/run/{run_id}/stop",
    summary="Stop a running Memory Watch subprocess",
)
async def stop_memory_watch(run_id: str) -> dict:
    """
    Kill the tracked subprocess tree and mark the history row stopped.

    @param run_id: Active run id
    @returns status payload
    """
    safe_id = _require_run_id(run_id)
    item = memory_watch_run_store.get_run(safe_id)
    pid = _memory_watch_pids.get(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No active Memory Watch for run_id='{safe_id}'")
    if item.get("status") != "running" and pid is None:
        raise HTTPException(status_code=404, detail=f"No active Memory Watch for run_id='{safe_id}'")

    _memory_watch_stopped.add(safe_id)
    if pid is not None:
        try:
            kill_memory_watch_pid(pid)
            logger.info("[%s] Stop sent to PID %d", safe_id, pid)
        except ProcessLookupError:
            logger.debug("[%s] PID %d already exited", safe_id, pid)
        except Exception as exc:
            logger.warning("[%s] Could not stop PID %d: %s", safe_id, pid, exc)
        semaphore = _get_semaphore()
        _memory_watch_force_released.add(safe_id)
        semaphore.release()

    memory_watch_run_store.mark_stopped(safe_id)
    return {"status": "stopped", "run_id": safe_id}


@memory_watch_router.get(
    "/history",
    response_model=list[MemoryWatchHistoryItem],
    summary="List saved Memory Watch runs",
)
async def list_memory_watch_history() -> list[MemoryWatchHistoryItem]:
    """
    Return recent Memory Watch runs newest first (no logs).

    @returns History list items
    """
    return [
        MemoryWatchHistoryItem.model_validate(item)
        for item in memory_watch_run_store.list_runs()
    ]


@memory_watch_router.get(
    "/history/{run_id}",
    response_model=MemoryWatchHistoryDetail,
    summary="Get one saved Memory Watch run",
)
async def get_memory_watch_history(run_id: str) -> MemoryWatchHistoryDetail:
    """
    Return one saved run including heap samples, checklist, and log.

    @param run_id: Dashboard run id
    @returns Full history detail
    """
    safe_id = _require_run_id(run_id)
    item = memory_watch_run_store.get_run(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No saved Memory Watch for run_id='{safe_id}'")
    return MemoryWatchHistoryDetail.model_validate(item)


@memory_watch_router.get(
    "/history/{run_id}/video",
    summary="Stream the Memory Watch recording",
)
async def get_memory_watch_video(run_id: str) -> FileResponse:
    """
    Return recording.webm from the run's report directory.

    @param run_id: Dashboard run id
    @returns Video file
    """
    safe_id = _require_run_id(run_id)
    item = memory_watch_run_store.get_run(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No saved Memory Watch for run_id='{safe_id}'")
    report_dir = Path(str(item.get("report_dir") or ""))
    video_file = str(item.get("video_file") or "recording.webm")
    if not report_dir.is_dir():
        raise HTTPException(status_code=404, detail="No video for this run")
    video_path = (report_dir / Path(video_file).name).resolve()
    try:
        video_path.relative_to(report_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No video for this run") from exc
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="No video for this run")
    return FileResponse(path=str(video_path), media_type="video/webm", filename=video_path.name)


async def _run_memory_watch_subprocess(
    run_id: str, cmd: list[str], cwd: str | os.PathLike[str]
) -> None:
    """
    Execute npm run memory:test and stream stdout/stderr over the existing WS bus.

    @param run_id: Dashboard run id
    @param cmd: Argv from build_memory_watch_argv
    @param cwd: vReview root
    @returns None
    """
    from backend.api.playwright_routes import _broadcast, _broadcast_terminal_msg
    from backend.api.routes import _run_states

    _run_states[run_id] = {
        "status": "running",
        "state": {"final_html_report": ""},
        "error": None,
        "jira_ticket_id": "",
        "role": "",
    }

    rows: list[dict[str, str]] = []
    samples: list[dict[str, object]] = []
    log_lines: list[str] = []
    verdict: dict[str, object] | None = None
    report: dict[str, object] | None = None
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
                _memory_watch_pids[run_id] = process.pid

            start_line = f"Running: {' '.join(cmd)}"
            log_lines.append(start_line)
            await _broadcast(run_id, start_line, "stdout")

            verdict_box: list[dict[str, object]] = []
            report_box: list[dict[str, object]] = []

            async def _stream(stream, stream_name: str) -> None:
                if stream is None:
                    return
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").rstrip()
                    if not line:
                        continue
                    log_lines.append(line)
                    sample = parse_memory_sample_line(line)
                    if sample:
                        samples.append(sample)
                    next_verdict = parse_memory_verdict_line(line)
                    if next_verdict:
                        verdict_box.clear()
                        verdict_box.append(next_verdict)
                    next_report = parse_memory_report_line(line)
                    if next_report:
                        report_box.clear()
                        report_box.append(next_report)
                    parsed = parse_review_table_row(line)
                    if parsed:
                        rows[:] = upsert_review_row(rows, parsed)
                    await _broadcast(run_id, line, stream_name)

            await asyncio.gather(
                _stream(process.stdout, "stdout"),
                _stream(process.stderr, "stderr"),
            )
            exit_code = await process.wait()
            verdict = verdict_box[0] if verdict_box else None
            report = report_box[0] if report_box else None
        except Exception as exc:
            logger.error("[%s] Memory Watch subprocess error: %s", run_id, exc, exc_info=True)
            error_line = f"Error launching Memory Watch: {exc}"
            log_lines.append(error_line)
            await _broadcast(run_id, error_line, "stderr")
            exit_code = -1
        finally:
            _memory_watch_pids.pop(run_id, None)

        was_stopped = run_id in _memory_watch_stopped
        _memory_watch_stopped.discard(run_id)
        if was_stopped:
            status = "stopped"
            terminal_type = "failed"
        elif exit_code == 0:
            status = "completed"
            terminal_type = "completed"
        else:
            status = "failed"
            terminal_type = "failed"

        verdict_pass = None
        growth_mb = None
        if isinstance(verdict, dict):
            if "pass" in verdict:
                verdict_pass = bool(verdict.get("pass"))
            if "growthMb" in verdict:
                try:
                    growth_mb = float(verdict.get("growthMb"))
                except (TypeError, ValueError):
                    growth_mb = None
        if any(str(row.get("status", "")).upper() == "FAIL" for row in rows):
            verdict_pass = False
        report_dir = ""
        video_file = ""
        if isinstance(report, dict):
            report_dir = str(report.get("dir") or "")
            video_file = str(report.get("video") or "")

        try:
            memory_watch_run_store.finish_run(
                run_id=run_id,
                status=status,
                samples=samples,
                rows=rows,
                log_text="\n".join(log_lines),
                verdict_pass=verdict_pass,
                growth_mb=growth_mb,
                report_dir=report_dir,
                video_file=video_file,
            )
        except Exception:
            logger.exception("[%s] Could not save Memory Watch history row", run_id)

        done_line = f"Memory Watch {status} (exit {exit_code})"
        log_lines.append(done_line)
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


async def cleanup_memory_watch_processes() -> None:
    """
    SIGTERM tracked Memory Watch subprocesses on server shutdown.

    @returns None
    """
    if not _memory_watch_pids:
        return
    for run_id, pid in list(_memory_watch_pids.items()):
        try:
            kill_memory_watch_pid(pid)
        except (ProcessLookupError, OSError):
            pass
    _memory_watch_pids.clear()
    _memory_watch_stopped.clear()
