"""
backend/api/playwright_routes.py
=================================
Playwright Standard Library API endpoints (FEAT-052 / TASK-060).

Endpoints
---------
  GET  /playwright/tests              — List all 40+ tests from canonical index
  POST /playwright/run                — Launch a test subprocess + stream via WebSocket
  GET  /playwright/storage/status     — 13×4 matrix of session file validity
  POST /playwright/storage/generate   — Trigger generateStorageStates.mjs

Safety Features
---------------
  - Allow-list validation: test_id must exist in playwright_index.json
  - Enum validation: env ∈ {prod,test,smoke,qa}; browser ∈ {chromium,firefox,webkit}
  - Shell injection guard: reject test_id containing [;&|`$(){}\\n\\r]
  - Log scrubber: masks SHARED_TEST_PASSWORD, ADMIN_TEST_PASSWORD, session tokens
  - Concurrency semaphore: max 2 concurrent Playwright runs (HTTP 429 if saturated)
  - Storage throttle: asyncio.Lock prevents concurrent generateStorageStates.mjs calls
  - PID tracking: _playwright_pids dict for SIGTERM cleanup on server shutdown
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import (
    FailureDigestEntry,
    NightlyRunResponse,
    PlaywrightGroupRunRequest,
    PlaywrightHealPromptRequest,
    PlaywrightHealPromptResponse,
    PlaywrightMatchResponse,
    PlaywrightRunRequest,
    PlaywrightRunResponse,
    PlaywrightStorageGenerateRequest,
    PlaywrightSuiteReportResponse,
    PlaywrightSuiteRunRequest,
    PlaywrightSuiteRunResponse,
)
from backend.config import settings
from backend.config.product_registry import load_product_registry
from backend.storage.playwright_registry import PlaywrightRegistry
from backend.storage.playwright_suite_runs import playwright_suite_run_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sub-router (mounted by main.py at app level — no auth dependency here;
# auth is handled by the parent router in routes.py via Depends(verify_api_key))
# ---------------------------------------------------------------------------

playwright_router = APIRouter(prefix="/playwright", tags=["playwright"])

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Concurrency gate: max 2 simultaneous Playwright test runs
_playwright_semaphore: asyncio.Semaphore | None = None
MAX_CONCURRENT_PLAYWRIGHT_RUNS = 2

# Storage generation throttle: only 1 concurrent generateStorageStates.mjs
_storage_generate_lock: asyncio.Lock | None = None
_storage_generate_in_progress: bool = False

# Storage generation progress tracking (for frontend polling)
# Shape: {"status": "idle"|"running"|"done"|"error",
#          "envs_requested": [...], "envs_completed": [...],
#          "envs_failed": [...], "error": str|None,
#          "started_at": float|None, "finished_at": float|None}
_storage_generate_progress: Dict[str, Any] = {
    "status": "idle",
    "envs_requested": [],
    "envs_completed": [],
    "envs_failed": [],
    "error": None,
    "started_at": None,
    "finished_at": None,
}

# PID tracking: run_id → subprocess PID (for SIGTERM on shutdown)
_playwright_pids: Dict[str, int] = {}

# Tracks runs whose semaphore slot was released early by the stop handler.
# The background task checks this to avoid a double-release.
_playwright_force_released: set[str] = set()

# Maps suite_run_id → last polled epoch timestamp (for inactivity fallback)
_suite_run_last_poll: Dict[str, float] = {}

# ---------------------------------------------------------------------------
# Pre-connect message buffer
# ---------------------------------------------------------------------------
# Stores messages broadcast BEFORE a WebSocket client connects.
# Keyed by run_id; each entry is a list of serialised JSON strings.
# The buffer is flushed (and deleted) as soon as the first WS client
# registers via websocket_log_stream in routes.py.
#
# Buffer lifetime cap: messages older than _BUFFER_TTL_SECONDS are
# purged on next access to prevent memory leaks on abandoned runs.
_playwright_msg_buffer: Dict[str, List[Dict[str, Any]]] = {}
_BUFFER_TTL_SECONDS: float = 60.0  # 60s: plenty for any network round-trip


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-initialize the semaphore (must run inside an event loop)."""
    global _playwright_semaphore
    if _playwright_semaphore is None:
        _playwright_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PLAYWRIGHT_RUNS)
    return _playwright_semaphore


@contextlib.asynccontextmanager
async def _semaphore_for_run(run_id: str):
    """
    Acquire the concurrency semaphore for a single-test run.

    On exit, skips the release if the stop handler already released it early
    (tracked in _playwright_force_released) to prevent a double-release that
    would inflate the semaphore above MAX_CONCURRENT_PLAYWRIGHT_RUNS.
    """
    semaphore = _get_semaphore()
    await semaphore.acquire()
    try:
        yield
    finally:
        if run_id in _playwright_force_released:
            _playwright_force_released.discard(run_id)
            logger.debug("[%s] Semaphore already released by stop handler — skipping double-release", run_id)
        else:
            semaphore.release()


def _get_storage_lock() -> asyncio.Lock:
    """Lazy-initialize the storage generation lock."""
    global _storage_generate_lock
    if _storage_generate_lock is None:
        _storage_generate_lock = asyncio.Lock()
    return _storage_generate_lock


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ENVS = {"prod", "test", "smoke", "qa"}
VALID_BROWSERS = {"chromium", "firefox", "webkit"}

# Shell metacharacters that must never appear in test_id (injection guard)
_SHELL_INJECTION_RE = re.compile(r"[;&|`$(){}\n\r]")

# Users loaded once from fixtures at module level
_USERS_FILE = Path("playwright/fixtures/users/users.json")
_VALID_USERS: List[str] = []


def _load_users() -> List[str]:
    """Load valid usernames from the users fixture."""
    global _VALID_USERS
    if _VALID_USERS:
        return _VALID_USERS
    try:
        with open(_USERS_FILE, "r") as f:
            data = json.load(f)
        _VALID_USERS = [u["username"] for u in data if "username" in u]
        logger.info("Loaded %d Playwright users from %s", len(_VALID_USERS), _USERS_FILE)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Could not load Playwright users from %s: %s", _USERS_FILE, e)
        _VALID_USERS = []
    return _VALID_USERS


def _get_registry() -> PlaywrightRegistry:
    """Build a PlaywrightRegistry from environment-configured paths."""
    tests_dir = os.getenv("PLAYWRIGHT_TESTS_DIR", "playwright/tests")
    registry_file = os.getenv("PLAYWRIGHT_INDEX_FILE", "playwright/playwright_index.json")
    return PlaywrightRegistry(tests_dir, registry_file)


# ---------------------------------------------------------------------------
# Log scrubber
# ---------------------------------------------------------------------------

def _scrub_line(line: str) -> str:
    """
    Mask sensitive values in a Playwright subprocess log line.

    Patterns masked:
      - SHARED_TEST_PASSWORD value
      - ADMIN_TEST_PASSWORD value
      - password= / token= / storageState= values
      - JWT-shaped strings (xxxxx.yyyyy.zzzzz ≥ 20 chars)
    """
    # Mask environment variable values (SHARED_TEST_PASSWORD, ADMIN_TEST_PASSWORD)
    shared_pw = os.getenv("SHARED_TEST_PASSWORD", "")
    admin_pw = os.getenv("ADMIN_TEST_PASSWORD", "")
    if shared_pw and shared_pw in line:
        line = line.replace(shared_pw, "[REDACTED]")
    if admin_pw and admin_pw in line:
        line = line.replace(admin_pw, "[REDACTED]")

    # Mask password/token/storageState key=value patterns
    line = re.sub(
        r'(password|token|storageState)["\s:=]+\S+',
        r"\1=[REDACTED]",
        line,
        flags=re.IGNORECASE,
    )

    # Mask JWT-shaped strings (header.payload.signature, ≥20 total chars)
    line = re.sub(
        r"[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
        "[REDACTED_JWT]",
        line,
    )

    return line


# ---------------------------------------------------------------------------
# WebSocket broadcast (imported lazily to avoid circular import)
# ---------------------------------------------------------------------------

async def _broadcast(run_id: str, line: str, stream: str = "stdout") -> None:
    """
    Broadcast a terminal log line via the existing WebSocket infrastructure.

    If no WebSocket client has connected yet for this run_id, the message is
    stored in _playwright_msg_buffer so it can be flushed the moment the
    client connects (see flush_playwright_buffer in routes.py).

    Imports _broadcast_terminal_log from routes.py at call time to avoid
    circular import (routes.py imports playwright_routes.py).
    """
    from backend.api.routes import _broadcast_terminal_log, _ws_connections  # noqa: PLC0415

    scrubbed = _scrub_line(line)

    if not _ws_connections.get(run_id):
        # No client yet — buffer the message for late-connecting clients
        _playwright_msg_buffer.setdefault(run_id, []).append(
            {
                "type": "terminal_log",
                "run_id": run_id,
                "line": scrubbed,
                "stream": stream,
                "_ts": time.monotonic(),
            }
        )
        return

    await _broadcast_terminal_log(run_id, scrubbed, stream)


async def _broadcast_terminal_msg(run_id: str, msg: Any) -> None:
    """
    Broadcast a WSTerminalMessage (completed/failed) to connected clients.

    If no client is connected yet, the terminal message is buffered so the
    final run state is not lost to the race condition.
    """
    from backend.api.routes import _broadcast_terminal, _ws_connections  # noqa: PLC0415

    if not _ws_connections.get(run_id):
        # Buffer the terminal message — it will be replayed on WS connect
        _playwright_msg_buffer.setdefault(run_id, []).append(
            {
                "_terminal": True,
                "_ts": time.monotonic(),
                "_msg_json": msg.model_dump_json(),
            }
        )
        return

    await _broadcast_terminal(run_id, msg)


def flush_playwright_buffer(run_id: str) -> List[Dict[str, Any]]:
    """
    Pop and return all buffered messages for run_id.

    Called by websocket_log_stream in routes.py immediately after the
    WebSocket client registers.  Messages are discarded if they are older
    than _BUFFER_TTL_SECONDS to prevent replaying stale data.

    Returns a list of dicts in arrival order.  The caller is responsible
    for serialising and sending each message.
    """
    raw = _playwright_msg_buffer.pop(run_id, [])
    now = time.monotonic()
    return [m for m in raw if now - m["_ts"] < _BUFFER_TTL_SECONDS]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@playwright_router.get("/tests", summary="List all static Playwright tests")
async def list_playwright_tests(product: str | None = None) -> list[dict]:
    """
    Returns the full contents of playwright_index.json.

    Each entry includes id, file, jira_keys, description, steps_count, step_names.
    The registry is re-pointed to playwright/playwright_index.json (AC-BACK-1).

    When ``product`` is provided, only tests for that product's directory are returned.
    """
    registry = _get_registry()
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


@playwright_router.get(
    "/match/{ticket_id}",
    response_model=PlaywrightMatchResponse,
    summary="Match a Jira ticket to existing static Playwright tests",
)
async def match_playwright_test(ticket_id: str, product: str | None = None) -> PlaywrightMatchResponse:
    """
    Check if a Jira ticket has a mapped static Playwright test.

    When ``product`` is provided, only tests for that product's directory are searched.
    """
    registry = _get_registry()
    if product is None:
        matches = registry.get_tests_by_jira_key(ticket_id)
    else:
        try:
            reg = load_product_registry()
            product_ctx = reg.get(product)
        except KeyError:
            raise HTTPException(status_code=422, detail=f"Unknown product slug '{product}'.")
        except Exception as exc:
            logger.error("Product registry unavailable: %s", exc)
            raise HTTPException(status_code=503, detail="Product registry unavailable.")
        product_tests = registry.list_tests_for_product(product_ctx.playwright_tests_dir)
        matches = [t for t in product_tests if any(
            ticket_id.strip().upper() == k.strip().upper()
            for k in t.get("jira_keys", [])
        )]
    return PlaywrightMatchResponse(
        matched=len(matches) > 0,
        tests=matches
    )


@playwright_router.post(
    "/run",
    response_model=PlaywrightRunResponse,
    summary="Launch a Playwright test run",
)
async def run_playwright_test(request: PlaywrightRunRequest, http_request: Request) -> PlaywrightRunResponse:
    """
    Validate and launch a static Playwright test as a subprocess.

    Validation order (fail-fast):
      1. Shell injection guard on test_id
      2. Allow-list check: test_id must be in playwright_index.json
      3. Enum: env ∈ {prod, test, smoke, qa}
      4. Enum: browser ∈ {chromium, firefox, webkit}
      5. Concurrency semaphore: max 2 concurrent runs (HTTP 429 if exceeded)

    On success:
      - Spawns npx playwright test subprocess
      - Streams stdout/stderr via _broadcast_terminal_log WebSocket channel
      - Returns {run_id, websocket_url} immediately
      - Completion: WSTerminalMessage sent when subprocess exits
    """
    # 1. Shell injection guard
    if _SHELL_INJECTION_RE.search(request.test_id):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown test_id: {request.test_id}",
        )

    # 2. Allow-list check
    registry = _get_registry()
    test_meta = registry.get_test(request.test_id)
    if test_meta is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown test_id: {request.test_id}",
        )

    # 3. Env validation (Pydantic already validates via Literal, but belt+suspenders)
    if request.env not in VALID_ENVS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid env '{request.env}'. Must be one of: {sorted(VALID_ENVS)}",
        )

    # 4. Browser validation
    if request.browser not in VALID_BROWSERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid browser '{request.browser}'. Must be one of: {sorted(VALID_BROWSERS)}",
        )

    # 5. User validation against allow-list
    valid_users = _load_users()
    if valid_users and request.user not in valid_users:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown user '{request.user}'. Must be one of the 13 known users.",
        )

    # 6. Concurrency semaphore (non-blocking)
    semaphore = _get_semaphore()
    if semaphore._value <= 0:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent Playwright runs. Max: {MAX_CONCURRENT_PLAYWRIGHT_RUNS}",
        )

    # Generate run_id
    run_id = f"pw-{uuid.uuid4().hex[:8]}"

    # Build the WebSocket URL (relative — frontend constructs full URL)
    ws_url = f"/ws/{run_id}"

    # Build noVNC URL for live browser viewing
    from backend.browser.vnc_builder import vnc_builder
    novnc_url = vnc_builder.build_url(http_request, "interactive")

    # Launch background task
    asyncio.create_task(
        _run_playwright_subprocess(run_id, request, test_meta)
    )

    logger.info(
        "[%s] Playwright test started: %s (env=%s, user=%s, browser=%s)",
        run_id,
        request.test_id,
        request.env,
        request.user,
        request.browser,
    )

    return PlaywrightRunResponse(run_id=run_id, websocket_url=ws_url, novnc_url=novnc_url)


@playwright_router.post(
    "/run/{run_id}/stop",
    summary="Stop a running single Playwright test subprocess",
)
async def stop_playwright_run(run_id: str) -> dict:
    """
    Terminate an active single-test Playwright subprocess by sending SIGTERM to its PID.
    Returns 404 if no active run is found for the given run_id.
    """
    pid = _playwright_pids.get(run_id)
    if pid is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active run found for run_id='{run_id}'",
        )

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("[%s] SIGTERM sent to PID %d by user stop request", run_id, pid)
    except ProcessLookupError:
        logger.debug("[%s] PID %d already exited when stop was requested", run_id, pid)
    except Exception as e:
        logger.warning("[%s] Could not SIGTERM PID %d: %s", run_id, pid, e)

    # Release the semaphore immediately so a new run can start without waiting
    # for the background task to finish all its cleanup (report reading, WS broadcast).
    # Mark the run so the background task skips its own release and avoids a
    # double-release that would inflate the semaphore above MAX.
    semaphore = _get_semaphore()
    _playwright_force_released.add(run_id)
    semaphore.release()
    logger.info("[%s] Semaphore released early by stop handler", run_id)

    return {"status": "stopped", "run_id": run_id}


async def _run_playwright_subprocess(
    run_id: str,
    request: PlaywrightRunRequest,
    test_meta: dict,
) -> None:
    """
    Execute the Playwright test as an asyncio subprocess.

    Runs inside an asyncio.Semaphore(2) gate.  Streams stdout/stderr
    via the existing WebSocket broadcast infrastructure.  Tracks the
    subprocess PID in _playwright_pids for SIGTERM cleanup on shutdown.

    On completion (exit 0): broadcasts WSTerminalMessage(type="completed")
    On failure (exit != 0): broadcasts WSTerminalMessage(type="failed")
    """
    from backend.api.routes import _broadcast_ac_progress, _run_states  # noqa: PLC0415
    from backend.api.schemas import WSTerminalMessage  # noqa: PLC0415

    # Register this pw run in _run_states so /runs/{run_id}/report can find it
    _run_states[run_id] = {
        "status": "running",
        "state": {"final_html_report": ""},
        "error": None,
        "jira_ticket_id": "",
        "role": "",
    }

    # Step Names initialization (to map real-time results back to frontend rows)
    step_names = test_meta.get("step_names", [])
    current_statuses = [
        {
            "index": i,
            "text": name,
            "status": "pending",
            "error": "",
            "human_selector": ""
        }
        for i, name in enumerate(step_names)
    ]

    # Initialize frontend with pending steps
    await _broadcast_ac_progress(run_id, current_statuses)

    async with _semaphore_for_run(run_id):
        # Build subprocess command
        test_file = test_meta.get("file", "").replace("\\", "/")
        tests_dir = os.getenv("PLAYWRIGHT_TESTS_DIR", "playwright/tests")

        # Set up Playwright JSON report path
        json_report_path = Path("playwright/test-results") / f"results-{run_id}.json"
        # Per-run HTML report directory to avoid collisions between concurrent runs
        # Use test-reports directory to avoid clashing with test-results (which is the outputDir)
        html_report_dir = Path("playwright/test-reports") / f"report-{run_id}"
        json_report_path.parent.mkdir(parents=True, exist_ok=True)

        # The test file path is relative to playwright/ directory
        # e.g., "tests/qa-170-search.test.ts"
        # On Windows, npx is a .cmd batch script — subprocess_exec can't find
        # .cmd files without shell=True, so use the explicit extension.
        npx_bin = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [
            npx_bin,
            "playwright",
            "test",
            test_file,
            "--project",
            request.browser,
            "--reporter=list,json,html",
        ]

        # Always run headed — in Docker, Xvfb + x11vnc + noVNC streams
        # the browser to users via the websockify bridge
        cmd.append("--headed")

        # Build environment
        env = dict(os.environ)
        env["TEST_ENV"] = request.env
        env["PLAYWRIGHT_USER"] = request.user
        env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(json_report_path.resolve())
        env["PLAYWRIGHT_HTML_REPORT"] = str(html_report_dir.resolve())

        from backend.browser.context import resolve_display
        resolve_display(env)

        # Point setup.ts at the correct storage directory for this env.
        # setup.ts builds its fallback path as path.resolve(__dirname, '..', 'storage', TEST_ENV)
        # which resolves to <root>/playwright/storage/<env>.
        # Override STORAGE_DIR so the fixture finds pre-authenticated sessions.
        # Always set it — globalSetup.ts creates the directory if it doesn't exist.
        storage_dir = str(Path("playwright/storage") / request.env)
        env["STORAGE_DIR"] = str(Path(storage_dir).resolve())

        # Also pass the specific user's storage state path (belt-and-suspenders)
        storage_state_path = (
            f"playwright/storage/{request.env}/storageState_{request.user}.json"
        )
        if Path(storage_state_path).exists():
            env["STORAGE_STATE_PATH"] = str(Path(storage_state_path).resolve())

        # Working directory: project root (where playwright.config.ts lives)
        cwd = str(Path(".").resolve())

        logger.info("[%s] Spawning: %s (cwd=%s)", run_id, " ".join(cmd), cwd)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            # Track PID for shutdown cleanup
            if process.pid:
                _playwright_pids[run_id] = process.pid
                logger.info("[%s] Subprocess PID: %d", run_id, process.pid)

            # Notify frontend that streaming has started
            await _broadcast(run_id, "Test started — streaming output below", "stdout")

            # Stream stdout and stderr concurrently
            async def _stream(stream, stream_name: str):
                if stream is None:
                    return
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").rstrip()
                    if line:
                        await _broadcast(run_id, line, stream_name)
                        if stream_name == "stdout":
                            await _parse_line_for_step_progress(run_id, line, step_names, current_statuses)

            await asyncio.gather(
                _stream(process.stdout, "stdout"),
                _stream(process.stderr, "stderr"),
            )

            exit_code = await process.wait()

            # Parse completed JSON report for exact steps status
            await _parse_playwright_json_report(run_id, json_report_path, step_names, current_statuses)

        except Exception as e:
            logger.error("[%s] Playwright subprocess error: %s", run_id, e, exc_info=True)
            await _broadcast(run_id, f"Error launching test: {e}", "stderr")
            exit_code = -1
            await _resolve_missing_steps(run_id, current_statuses)
        finally:
            # Remove PID from tracking
            _playwright_pids.pop(run_id, None)

        # Read and store the HTML report so /runs/{run_id}/report can serve it
        html_report_path = html_report_dir / "index.html"
        if html_report_path.exists():
            try:
                html_content = html_report_path.read_text(encoding="utf-8", errors="replace")
                if run_id in _run_states:
                    _run_states[run_id]["state"]["final_html_report"] = html_content
                logger.info("[%s] Stored HTML report (%d bytes)", run_id, len(html_content))
            except Exception as html_err:
                logger.warning("[%s] Could not read HTML report: %s", run_id, html_err)
            # Clean up the per-run report directory
            try:
                import shutil
                shutil.rmtree(html_report_dir, ignore_errors=True)
            except Exception:
                pass
        else:
            # Fallback: check the default playwright-report/ location
            fallback_path = Path("playwright-report/index.html")
            if fallback_path.exists():
                try:
                    html_content = fallback_path.read_text(encoding="utf-8", errors="replace")
                    if run_id in _run_states:
                        _run_states[run_id]["state"]["final_html_report"] = html_content
                    logger.info("[%s] Stored HTML report from fallback (%d bytes)", run_id, len(html_content))
                except Exception as html_err:
                    logger.warning("[%s] Could not read fallback HTML report: %s", run_id, html_err)

        # Update run status
        if run_id in _run_states:
            _run_states[run_id]["status"] = "completed" if exit_code == 0 else "failed"

        # Build terminal message
        terminal_type = "completed" if exit_code == 0 else "failed"

        ac_steps_passed = sum(1 for s in current_statuses if s["status"] == "passed")
        ac_steps_total = len(current_statuses)
        bugs_found = sum(1 for s in current_statuses if s["status"] == "failed")

        msg = WSTerminalMessage(
            type=terminal_type,
            run_id=run_id,
            error="" if exit_code == 0 else f"exit code {exit_code}",
            ac_steps_passed=ac_steps_passed,
            ac_steps_total=ac_steps_total,
            bugs_found=bugs_found,
        )

        logger.info(
            "[%s] Playwright test %s (exit=%d, passed=%d/%d, bugs=%d)",
            run_id,
            terminal_type,
            exit_code,
            ac_steps_passed,
            ac_steps_total,
            bugs_found,
        )

        await _broadcast_terminal_msg(run_id, msg)


async def _parse_line_for_step_progress(
    run_id: str,
    line: str,
    step_names: List[str],
    current_statuses: List[dict],
) -> None:
    """
    Parse a Playwright stdout line in real-time to update and broadcast step statuses.
    """
    from backend.api.routes import _broadcast_ac_progress  # noqa: PLC0415

    updated = False
    for i, name in enumerate(step_names):
        if name.lower() in line.lower():
            if "✓" in line or "pass" in line.lower():
                if current_statuses[i]["status"] != "passed":
                    current_statuses[i]["status"] = "passed"
                    updated = True
            elif "✕" in line or "fail" in line.lower() or "error" in line.lower() or "1)" in line:
                if current_statuses[i]["status"] != "failed":
                    current_statuses[i]["status"] = "failed"
                    updated = True
            else:
                if current_statuses[i]["status"] == "pending":
                    current_statuses[i]["status"] = "in_progress"
                    updated = True

    if updated:
        await _broadcast_ac_progress(run_id, current_statuses)


async def _parse_playwright_json_report(
    run_id: str,
    json_report_path: Path,
    step_names: List[str],
    current_statuses: List[dict],
) -> None:
    """
    Parse the completed Playwright JSON report, map final results back to step_names,
    and broadcast the final status list.
    """
    from backend.api.routes import _broadcast_ac_progress  # noqa: PLC0415

    if not json_report_path.exists():
        logger.warning("[%s] Playwright JSON report not found at %s", run_id, json_report_path)
        await _resolve_missing_steps(run_id, current_statuses)
        return

    try:
        with open(json_report_path, "r") as f:
            report_data = json.load(f)

        parsed_steps = []

        def walk_suite(suite):
            if "suites" in suite:
                for s in suite["suites"]:
                    walk_suite(s)
            if "specs" in suite:
                for spec in suite["specs"]:
                    for test in spec.get("tests", []):
                        for result in test.get("results", []):
                            for step in result.get("steps", []):
                                if step.get("category") == "test.step":
                                    parsed_steps.append({
                                        "title": step.get("title"),
                                        "status": step.get("status"),
                                        "error": step.get("error", {}).get("message") if step.get("error") else ""
                                    })
                                walk_step(step)

        def walk_step(step):
            for substep in step.get("steps", []):
                if substep.get("category") == "test.step":
                    parsed_steps.append({
                        "title": substep.get("title"),
                        "status": substep.get("status"),
                        "error": substep.get("error", {}).get("message") if substep.get("error") else ""
                    })
                walk_step(substep)

        for suite in report_data.get("suites", []):
            walk_suite(suite)

        # If the test has no test.step() structure (e.g. a raw recorded demo),
        # fall back to the overall test result from the JSON report itself.
        if not parsed_steps:
            overall_ok = True
            def _check_suite_ok(suite: dict) -> None:
                nonlocal overall_ok
                for spec in suite.get("specs", []):
                    if not spec.get("ok", True):
                        overall_ok = False
                    for test in spec.get("tests", []):
                        for result in test.get("results", []):
                            if result.get("status") not in ("passed", "skipped"):
                                overall_ok = False
                for sub in suite.get("suites", []):
                    _check_suite_ok(sub)

            for suite in report_data.get("suites", []):
                _check_suite_ok(suite)

            fallback_status = "passed" if overall_ok else "failed"
            for s in current_statuses:
                s["status"] = fallback_status
            await _broadcast_ac_progress(run_id, current_statuses)
            return

        # Map parsed results back to original step_names
        for i, name in enumerate(step_names):
            matching_step = None
            for ps in parsed_steps:
                if ps["title"].strip().lower() == name.strip().lower():
                    matching_step = ps
                    break

            if matching_step:
                status = "passed" if matching_step["status"] == "passed" else "failed"
                error_msg = _clean_error_message(matching_step["error"])
                current_statuses[i]["status"] = status
                current_statuses[i]["error"] = error_msg
            else:
                # If a step is not in the JSON report, it was either skipped or not reached
                any_failed = any(s["status"] == "failed" for s in current_statuses[:i])
                current_statuses[i]["status"] = "skipped" if any_failed else "skipped"

        await _broadcast_ac_progress(run_id, current_statuses)

    except Exception as ex:
        logger.error("[%s] Error parsing Playwright JSON report: %s", run_id, ex, exc_info=True)
        await _resolve_missing_steps(run_id, current_statuses)
    finally:
        try:
            json_report_path.unlink(missing_ok=True)
        except Exception:
            pass


async def _resolve_missing_steps(run_id: str, current_statuses: List[dict]) -> None:
    """Ensure no steps are left as pending/in_progress after run completion."""
    from backend.api.routes import _broadcast_ac_progress  # noqa: PLC0415
    any_failed = False
    for s in current_statuses:
        if s["status"] == "failed":
            any_failed = True
        elif s["status"] in ("pending", "in_progress"):
            s["status"] = "skipped" if any_failed else "failed"
    await _broadcast_ac_progress(run_id, current_statuses)


def _clean_error_message(msg: str) -> str:
    """Remove ANSI escape codes and cleaner formatting for the error message."""
    if not msg:
        return ""
    # Regex to strip ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned = ansi_escape.sub('', msg)
    return cleaned.strip()


def _clean_error_to_summary(error_snippet: str | None) -> str:
    """
    Parses a raw Playwright error snippet into a clean, one-line condensed summary.
    Applies ANSI escape stripping, filters out Playwright headers and stack traces,
    finds the first assertion line, or falls back to the first non-header non-trace line,
    and truncates to 120 characters.
    """
    if not error_snippet:
        return "Unknown failure"

    # 1. Strip ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned_snippet = ansi_escape.sub('', error_snippet)

    # 2. Split into lines
    lines = [line.strip() for line in cleaned_snippet.splitlines() if line.strip()]

    def is_ignored_line(line: str) -> bool:
        # Playwright runner lines
        if re.search(r'^\d+\)\s*\[', line) or " › " in line or "›" in line:
            return True
        # Stack trace lines
        if line.startswith("at ") or "node_modules/" in line or "playwright/" in line:
            return True
        return False

    # Filter out header and trace lines
    filtered_lines = [line for line in lines if not is_ignored_line(line)]

    if not filtered_lines:
        return "Unknown failure"

    # 3. Find first matching primary assertion line
    assertion_line = None
    for line in filtered_lines:
        if "Error:" in line or "expect(" in line or "timeout" in line or "timeout" in line.lower():
            assertion_line = line
            break

    # 4. Fallback to the first non-header, non-trace line
    if not assertion_line:
        assertion_line = filtered_lines[0]

    # 5. Truncate to maximum of 120 characters with '...' if needed
    if len(assertion_line) > 120:
        assertion_line = assertion_line[:117] + "..."

    return assertion_line


@playwright_router.get(
    "/storage/status",
    summary="Get storage state session validity matrix",
)
async def get_storage_status():
    """
    Returns a 13×4 matrix of session file validity.

    Response shape:
    {
      "environments": {
        "prod": {"Admin": "valid"|"expired"|"missing", ...},
        "test": {...},
        "smoke": {...},
        "qa": {...}
      }
    }

    Status meanings:
      "valid"   — file exists and mtime < 24 hours ago
      "expired" — file exists but mtime >= 24 hours ago
      "missing" — storageState_{User}.json does not exist
    """
    users = _load_users()
    if not users:
        # Fall back to known list if fixture not loaded
        users = [
            "Admin", "DemoProdDirector", "DemoTrafficDirector", "DemoSalesExec",
            "DemoProdMan", "DemoProdWoman", "DemoDigitalDir", "DemoDigitalProd",
            "DemoVoicer", "DemoGM", "DemoGraphicArtist", "writer", "DemoTrafficAssnt",
        ]

    now = time.time()
    ttl_seconds = 24 * 3600  # 24 hours

    result: Dict[str, Dict[str, str]] = {}

    for env in ("prod", "test", "smoke", "qa"):
        env_status: Dict[str, str] = {}
        for username in users:
            path = Path(f"playwright/storage/{env}/storageState_{username}.json")
            if not path.exists():
                env_status[username] = "missing"
            elif now - path.stat().st_mtime >= ttl_seconds:
                env_status[username] = "expired"
            else:
                env_status[username] = "valid"
        result[env] = env_status

    return {"environments": result}


@playwright_router.post(
    "/storage/generate",
    summary="Regenerate storage states for one or all environments",
)
async def generate_storage_states(request: PlaywrightStorageGenerateRequest):
    """
    Trigger generateStorageStates.mjs for the requested environment(s).

    Returns 200 immediately and runs generation as a background task to avoid
    ALB idle-timeout (504) on long-running login flows (17 users × N envs).

    Throttled: only one concurrent generation allowed (asyncio.Lock).
    Returns HTTP 429 if a generation is already in progress.

    Frontend should poll GET /storage/generate/status to track progress.
    """
    global _storage_generate_in_progress, _storage_generate_progress

    lock = _get_storage_lock()

    if lock.locked():
        raise HTTPException(
            status_code=429,
            detail="Storage generation already in progress",
        )

    envs_to_generate = request.envs or ["prod", "test", "smoke", "qa"]

    # Reset progress tracker
    _storage_generate_progress = {
        "status": "running",
        "envs_requested": list(envs_to_generate),
        "envs_completed": [],
        "envs_failed": [],
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
    }

    async def _run_in_background() -> None:
        global _storage_generate_in_progress, _storage_generate_progress
        async with lock:
            _storage_generate_in_progress = True
            try:
                await _run_generate_storage(request)
                _storage_generate_progress["status"] = "done"
            except Exception as exc:
                logger.error("Background storage generation failed: %s", exc)
                _storage_generate_progress["status"] = "error"
                _storage_generate_progress["error"] = str(exc)
            finally:
                _storage_generate_in_progress = False
                _storage_generate_progress["finished_at"] = time.time()

    asyncio.create_task(_run_in_background())
    return {"status": "ok", "generated": 0}


@playwright_router.get(
    "/storage/generate/status",
    summary="Poll storage generation progress",
)
async def get_storage_generate_status():
    """
    Returns the current status of the background storage generation task.

    Response shape:
    {
      "status": "idle" | "running" | "done" | "error",
      "envs_requested": ["test", ...],
      "envs_completed": ["test", ...],
      "envs_failed": [],
      "error": null | "error message",
      "started_at": 1234567890.0 | null,
      "finished_at": 1234567890.0 | null
    }
    """
    return _storage_generate_progress


async def _run_generate_storage(request: PlaywrightStorageGenerateRequest) -> dict:
    """
    Run generateStorageStates.mjs as an asyncio subprocess.

    If request.envs is empty, generates for all 4 environments.
    """
    users = _load_users()
    total_users = len(users) if users else 13

    envs_to_generate = request.envs or ["prod", "test", "smoke", "qa"]

    mjs_path = Path("playwright/utils/generateStorageStates.mjs")
    if not mjs_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"generateStorageStates.mjs not found at {mjs_path}",
        )

    generated_count = 0

    for env in envs_to_generate:
        env_env = dict(os.environ)
        env_env["TEST_ENV"] = env

        logger.info("Generating storage states for env=%s (%d users)...", env, total_users)

        try:
            process = await asyncio.create_subprocess_exec(
                "node",
                str(mjs_path.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env_env,
                cwd=str(Path(".").resolve()),
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=900,  # 15 minutes max per env (supports 24+ users)
            )

            exit_code = process.returncode

            if exit_code != 0:
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                logger.error(
                    "generateStorageStates.mjs failed for env=%s (exit=%d): %s",
                    env,
                    exit_code,
                    stderr_text[:500],
                )
                _storage_generate_progress["envs_failed"].append(env)
                raise HTTPException(
                    status_code=500,
                    detail="Storage generation failed",
                    headers={"X-Stderr": stderr_text[:1000]},
                )

            generated_count += total_users
            _storage_generate_progress["envs_completed"].append(env)
            logger.info("Storage generation complete for env=%s (%d users)", env, total_users)

        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=500,
                detail=f"Storage generation timed out for env={env} (300s limit)",
            )

    return {"status": "ok", "generated": generated_count}


# ---------------------------------------------------------------------------
# Parallel Headless Suite Runner Orchestration & Routes (TASK-114)
# ---------------------------------------------------------------------------

def _extract_playwright_error(stdout_text: str, stderr_text: str) -> str:
    """
    Extracts a high-fidelity, readable error snippet from Playwright test runner outputs.
    Prioritises actual test assertion errors from stdout, filtering out noisy npm/system warnings.
    """
    stdout_lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
    stderr_lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]

    # 1. Search for actual test execution errors in stdout (Playwright writes test errors to stdout)
    for i, line in enumerate(stdout_lines):
        if any(term in line for term in ["Error:", "expect(", "TimeoutError:", "AssertionError:"]):
            # Grab this line and up to 4 subsequent lines for context
            snippet_lines = stdout_lines[i:i+5]
            return "\n".join(snippet_lines)

    # 2. If we found a general "1) [chromium]" test index line, grab the lines beneath it
    for i, line in enumerate(stdout_lines):
        if "›" in line and ("[" in line or "]" in line):
            snippet_lines = stdout_lines[i:i+6]
            return "\n".join(snippet_lines)

    # 3. Fallback to last 5 lines of stdout if there are non-empty lines
    if stdout_lines:
        clean_stdout = [l for l in stdout_lines if not any(term in l.lower() for term in ["passed", "failed", "pending", "executing"])]
        if clean_stdout:
            return "\n".join(clean_stdout[-5:])

    # 4. Fallback to stderr (filtering out npm warnings if possible)
    clean_stderr = [l for l in stderr_lines if "npm warn" not in l.lower() and "npm error" not in l.lower()]
    if clean_stderr:
        return "\n".join(clean_stderr[-5:])
    elif stderr_lines:
        return "\n".join(stderr_lines[-5:])

    return "Process exited with non-zero code"


async def _run_single_suite_test(
    suite_run_id: str,
    test_meta: Dict[str, Any],
    semaphore: asyncio.Semaphore,
    env_param: str,
    user_param: str,
    browser_param: str,
) -> Dict[str, Any]:
    """
    Executes a single Playwright test as part of a parallel suite.
    Ensures concurrency control via semaphore, tracks PID, respects timeouts,
    and returns a formatted result dict.
    """
    test_id = test_meta.get("id", "")
    test_name = test_meta.get("description", test_id)
    test_file = test_meta.get("file", "")

    start_time = time.time()
    status = "FAIL"
    error_snippet = None
    process = None

    cmd = [
        "npx",
        "playwright",
        "test",
        test_file,
        "--project",
        browser_param,
    ]

    # Build environment (force VQA_HEADLESS=1 for headless execution)
    env = dict(os.environ)
    env["TEST_ENV"] = env_param
    env["PLAYWRIGHT_USER"] = user_param
    env["VQA_HEADLESS"] = "1"

    from backend.browser.context import resolve_display
    resolve_display(env)

    storage_dir = str(Path("playwright/storage") / env_param)
    env["STORAGE_DIR"] = str(Path(storage_dir).resolve())

    storage_state_path = f"playwright/storage/{env_param}/storageState_{user_param}.json"
    if Path(storage_state_path).exists():
        env["STORAGE_STATE_PATH"] = str(Path(storage_state_path).resolve())

    cwd = str(Path(".").resolve())
    pid_key = f"{suite_run_id}-{test_id}"

    # Check if the suite run has already been stopped/cancelled before waiting on semaphore
    run_data = playwright_suite_run_store.get_run(suite_run_id)
    if run_data and run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user":
        logger.info("[%s] Test %s cancelled before semaphore acquisition", suite_run_id, test_id)
        return {
            "test_id": test_id,
            "name": test_name,
            "status": "FAIL",
            "duration_ms": 0.0,
            "error_snippet": "Suite run stopped by user.",
        }

    async with semaphore:
        # Check if the suite run was cancelled while waiting for semaphore
        run_data = playwright_suite_run_store.get_run(suite_run_id)
        if run_data and run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user":
            logger.info("[%s] Test %s cancelled after semaphore acquisition", suite_run_id, test_id)
            return {
                "test_id": test_id,
                "name": test_name,
                "status": "FAIL",
                "duration_ms": 0.0,
                "error_snippet": "Suite run stopped by user.",
            }

        # Mark status as RUNNING in the SQLite results database
        playwright_suite_run_store.update_test_status(suite_run_id, test_id, "RUNNING")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            if process.pid:
                _playwright_pids[pid_key] = process.pid
                logger.info("[%s] Started test subprocess %s, PID %d", suite_run_id, test_id, process.pid)

            # Wait for completion with a per-file subprocess timeout of 720 seconds.
            # Individual tests cap themselves via test.setTimeout (max 340s + ~60s cleanup).
            # Serial multi-step suites (e.g. qa-196-Files.test.ts, 7 × 340s steps) need the
            # extra headroom; 720s covers the realistic combined runtime of ~400-600s.
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=720.0
            )

            exit_code = process.returncode
            if exit_code == 0:
                status = "PASS"
            else:
                status = "FAIL"
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                error_snippet = _extract_playwright_error(stdout_text, stderr_text)

        except asyncio.TimeoutError:
            status = "FAIL"
            error_snippet = "TimeoutError: Execution exceeded 720 seconds"
            if process:
                logger.warning("[%s] Test %s timed out, terminating PID %d", suite_run_id, test_id, process.pid)
                try:
                    process.terminate()
                    await process.wait()
                except Exception as e:
                    logger.error("[%s] Error terminating timed out process: %s", suite_run_id, e)
        except Exception as e:
            status = "FAIL"
            error_snippet = f"Unexpected error: {str(e)}"
            if process:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
        finally:
            if pid_key in _playwright_pids:
                del _playwright_pids[pid_key]

    duration_ms = (time.time() - start_time) * 1000.0

    result = {
        "test_id": test_id,
        "name": test_name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "error_snippet": error_snippet,
    }

    # Update final results inside the overall SQLite state store
    run_data = playwright_suite_run_store.get_run(suite_run_id)
    if run_data:
        # If the suite run was already stopped by user, do not overwrite the stopped status/snippet
        if run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user":
            pass
        else:
            playwright_suite_run_store.update_test_status(
                suite_run_id=suite_run_id,
                test_id=test_id,
                status=status,
                duration_ms=duration_ms,
                error_snippet=error_snippet,
            )

    return result


async def _run_suite_orchestrator(
    suite_run_id: str,
    tests: List[Dict[str, Any]],
    env: str,
    user: str,
    browser: str,
) -> None:
    """
    Schedules and executes all tests defined in playwright_index.json concurrently,
    limiting active workers with a Semaphore. Updates report state in real-time.
    """
    workers_limit = int(os.getenv("VQA_SUITE_WORKERS", "4"))
    semaphore = asyncio.Semaphore(workers_limit)

    # Initialize last poll timestamp
    _suite_run_last_poll[suite_run_id] = time.time()

    async def monitor_heartbeat():
        while True:
            await asyncio.sleep(2.0)
            run_data = playwright_suite_run_store.get_run(suite_run_id)
            if not run_data or run_data.get("status") != "running":
                break

            last_poll = _suite_run_last_poll.get(suite_run_id)
            if last_poll and (time.time() - last_poll) > 15.0:
                logger.warning("[%s] No poll requests received for >15s. Automatically stopping suite run.", suite_run_id)
                try:
                    await stop_suite_run(suite_run_id)
                except Exception as e:
                    logger.error("[%s] Error during auto-stop from heartbeat: %s", suite_run_id, e)
                break

    heartbeat_task = asyncio.create_task(monitor_heartbeat())

    tasks = [
        asyncio.create_task(_run_single_suite_test(suite_run_id, test, semaphore, env, user, browser))
        for test in tests
    ]

    try:
        # Process each task as it completes to update results in real-time
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                # Check if the suite run was cancelled/stopped midway
                run_data = playwright_suite_run_store.get_run(suite_run_id)
                if not run_data:
                    continue
                if run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user":
                    # Do not increment passed/failed if already cancelled
                    continue
                if result["status"] == "PASS":
                    playwright_suite_run_store.update_suite_totals_and_status(suite_run_id, passed_delta=1)
                else:
                    playwright_suite_run_store.update_suite_totals_and_status(suite_run_id, failed_delta=1)
            except Exception as e:
                logger.error("[%s] Error running suite test task: %s", suite_run_id, e)

        # Do not overwrite the user stopped state if already set
        run_data = playwright_suite_run_store.get_run(suite_run_id)
        if run_data and (run_data.get("status") != "failed" or run_data.get("fail_reason") != "Suite run stopped by user"):
            completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            # Calculate overall suite outcome and fail reason
            if run_data.get("failed", 0) > 0:
                outcome = "FAIL"
                failed_test_ids = [
                    r["test_id"]
                    for r in run_data.get("results", [])
                    if r.get("status") == "FAIL"
                ]
                summary_ids = failed_test_ids[:5]
                suffix = "..." if len(failed_test_ids) > 5 else ""
                fail_reason = f"Failed tests: {', '.join(summary_ids)}{suffix} (see results below for full error outputs)"
            else:
                outcome = "PASS"
                fail_reason = None

            playwright_suite_run_store.update_suite_totals_and_status(
                suite_run_id=suite_run_id,
                status="completed",
                outcome=outcome,
                fail_reason=fail_reason,
                completed_at=completed_at,
            )

    except Exception as e:
        logger.error("[%s] Parallel suite orchestrator crashed: %s", suite_run_id, e)
        completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        playwright_suite_run_store.update_suite_totals_and_status(
            suite_run_id=suite_run_id,
            status="failed",
            outcome="FAIL",
            fail_reason=f"Parallel suite orchestrator crashed: {str(e)}",
            completed_at=completed_at,
        )
    finally:
        # Cancel heartbeat task and clean up last poll entry
        heartbeat_task.cancel()
        _suite_run_last_poll.pop(suite_run_id, None)


@playwright_router.post(
    "/run-all",
    response_model=PlaywrightSuiteRunResponse,
    summary="Launch all static Playwright tests in parallel",
)
async def run_all_playwright_tests(request: PlaywrightSuiteRunRequest) -> PlaywrightSuiteRunResponse:
    # Clear any run that hasn't been updated in 2 hours before checking
    playwright_suite_run_store.abort_stale_runs(max_age_minutes=120)

    active_run_id = playwright_suite_run_store.get_active_run_id()
    if active_run_id is not None:
        raise HTTPException(
            status_code=429,
            detail="Suite run already in progress",
        )

    # Validate env, browser, user
    if request.env not in VALID_ENVS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid env '{request.env}'. Must be one of: {sorted(VALID_ENVS)}",
        )

    if request.browser not in VALID_BROWSERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid browser '{request.browser}'. Must be one of: {sorted(VALID_BROWSERS)}",
        )

    valid_users = _load_users()
    if valid_users and request.user not in valid_users:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown user '{request.user}'. Must be one of the 13 known users.",
        )

    registry = _get_registry()
    all_tests = registry.list_tests()
    # Only run files that end with .test.ts to avoid running helpers like filePreWashUtility
    tests = [t for t in all_tests if t.get("file", "").endswith(".test.ts")]

    if not tests:
        raise HTTPException(
            status_code=400,
            detail="No tests found in the registry",
        )

    suite_run_id = f"suite-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    run_data = {
        "suite_run_id": suite_run_id,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "total": len(tests),
        "passed": 0,
        "failed": 0,
        "results": [
            {
                "test_id": t["id"],
                "name": t.get("description", t["id"]),
                "status": "PENDING",
                "duration_ms": 0.0,
                "error_snippet": None,
            }
            for t in tests
        ],
        "outcome": None,
        "fail_reason": None,
    }
    playwright_suite_run_store.create_run(suite_run_id, run_data)

    # Launch execution as sequential background task (one test at a time)
    asyncio.create_task(
        _run_group_orchestrator(suite_run_id, tests, request.env, request.user, request.browser)
    )

    return PlaywrightSuiteRunResponse(
        suite_run_id=suite_run_id,
        status="running",
        started_at=started_at,
    )


async def _run_group_orchestrator(
    suite_run_id: str,
    tests: List[Dict[str, Any]],
    env: str,
    user: str,
    browser: str,
) -> None:
    """
    Executes a list of Playwright tests sequentially (one at a time).
    Uses a Semaphore(1) to guarantee no test starts until the previous finishes.
    """
    single_semaphore = asyncio.Semaphore(1)

    try:
        for test in tests:
            # Check for user cancellation between each test
            run_data = playwright_suite_run_store.get_run(suite_run_id)
            if run_data and run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user":
                logger.info("[%s] Group run cancelled before test %s", suite_run_id, test.get("id"))
                break

            result = await _run_single_suite_test(suite_run_id, test, single_semaphore, env, user, browser)

            run_data = playwright_suite_run_store.get_run(suite_run_id)
            if not run_data or (run_data.get("status") == "failed" and run_data.get("fail_reason") == "Suite run stopped by user"):
                break

            if result["status"] == "PASS":
                playwright_suite_run_store.update_suite_totals_and_status(suite_run_id, passed_delta=1)
            else:
                playwright_suite_run_store.update_suite_totals_and_status(suite_run_id, failed_delta=1)

        run_data = playwright_suite_run_store.get_run(suite_run_id)
        if run_data and (run_data.get("status") != "failed" or run_data.get("fail_reason") != "Suite run stopped by user"):
            completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if run_data.get("failed", 0) > 0:
                outcome = "FAIL"
                failed_test_ids = [r["test_id"] for r in run_data.get("results", []) if r.get("status") == "FAIL"]
                summary_ids = failed_test_ids[:5]
                suffix = "..." if len(failed_test_ids) > 5 else ""
                fail_reason = f"Failed tests: {', '.join(summary_ids)}{suffix} (see results below for full error outputs)"
            else:
                outcome = "PASS"
                fail_reason = None

            playwright_suite_run_store.update_suite_totals_and_status(
                suite_run_id=suite_run_id,
                status="completed",
                outcome=outcome,
                fail_reason=fail_reason,
                completed_at=completed_at,
            )

    except Exception as e:
        logger.error("[%s] Group run orchestrator crashed: %s", suite_run_id, e)
        completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        playwright_suite_run_store.update_suite_totals_and_status(
            suite_run_id=suite_run_id,
            status="failed",
            outcome="FAIL",
            fail_reason=f"Group run orchestrator crashed: {str(e)}",
            completed_at=completed_at,
        )


@playwright_router.post(
    "/run-group",
    response_model=PlaywrightSuiteRunResponse,
    summary="Run a selected group of Playwright tests sequentially",
)
async def run_playwright_group(request: PlaywrightGroupRunRequest) -> PlaywrightSuiteRunResponse:
    """
    Validates and launches a user-selected subset of tests one at a time.

    Validation:
      1. Shell injection guard on each test_id
      2. Allow-list check: every test_id must exist in playwright_index.json
      3. Enum: env ∈ {prod, test, smoke, qa}; browser ∈ {chromium, firefox, webkit}
      4. User allow-list check

    On success:
      - Creates a suite run record (same store as /run-all)
      - Runs tests sequentially (Semaphore(1)) — no parallelism
      - Returns {suite_run_id, status, started_at}
      - Poll GET /playwright/run-all/{suite_run_id}/report for results
    """
    if request.env not in VALID_ENVS:
        raise HTTPException(status_code=422, detail=f"Invalid env '{request.env}'")
    if request.browser not in VALID_BROWSERS:
        raise HTTPException(status_code=422, detail=f"Invalid browser '{request.browser}'")

    valid_users = _load_users()
    if valid_users and request.user not in valid_users:
        raise HTTPException(status_code=422, detail=f"Unknown user '{request.user}'")

    # Clear any run that hasn't been updated in 2 hours before checking
    playwright_suite_run_store.abort_stale_runs(max_age_minutes=120)

    active_run_id = playwright_suite_run_store.get_active_run_id()
    if active_run_id is not None:
        raise HTTPException(status_code=429, detail="Suite run already in progress")

    registry = _get_registry()
    tests = []
    for test_id in request.test_ids:
        if _SHELL_INJECTION_RE.search(test_id):
            raise HTTPException(status_code=422, detail=f"Invalid test_id: {test_id}")
        test_meta = registry.get_test(test_id)
        if test_meta is None:
            raise HTTPException(status_code=422, detail=f"Unknown test_id: {test_id}")
        tests.append(test_meta)

    suite_run_id = f"grp-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    run_data = {
        "suite_run_id": suite_run_id,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "total": len(tests),
        "passed": 0,
        "failed": 0,
        "results": [
            {
                "test_id": t["id"],
                "name": t.get("description", t["id"]),
                "status": "PENDING",
                "duration_ms": 0.0,
                "error_snippet": None,
            }
            for t in tests
        ],
        "outcome": None,
        "fail_reason": None,
    }
    playwright_suite_run_store.create_run(suite_run_id, run_data)

    asyncio.create_task(
        _run_group_orchestrator(suite_run_id, tests, request.env, request.user, request.browser)
    )

    logger.info("[%s] Group run started: %d tests (env=%s, user=%s, browser=%s)", suite_run_id, len(tests), request.env, request.user, request.browser)

    return PlaywrightSuiteRunResponse(suite_run_id=suite_run_id, status="running", started_at=started_at)


# ---------------------------------------------------------------------------
# Nightly Scheduled Playwright Suite — POST /api/playwright/nightly
# ---------------------------------------------------------------------------
# Called by AWS EventBridge Scheduler → API destination at 06:00 UTC daily.
# Dispatches a pinned two-test group run (same _run_group_orchestrator as
# /run-group), polls to terminal state in a background asyncio task, and
# posts a compact Slack Block Kit message with results.
# Auth: X-VQA-API-Key enforced by the parent router (routes.py).
# ---------------------------------------------------------------------------


async def _nightly_poll_and_notify(
    suite_run_id: str,
    slack_webhook_url: str,
    report_base_url: str,
) -> None:
    """
    Background asyncio task: poll playwright_suite_run_store until the nightly
    group run reaches a terminal state, then post a compact Slack notification.

    AC-ASYNC-1: polls every settings.nightly_poll_interval_seconds (default 5s),
    up to settings.nightly_poll_timeout_seconds (default 1800s = 30 min).
    AC-ERROR-1: on timeout or store exception, posts an error-shaped Slack message.
    AC-ERROR-2: Slack delivery failures are logged; they do NOT swallow the error.

    Parameters
    ----------
    suite_run_id : str
        The suite run ID returned by _run_group_orchestrator.
    slack_webhook_url : str
        Slack incoming webhook URL loaded from SSM at settings init.
    report_base_url : str
        Base URL (e.g. https://vqa.vcreative.net) for constructing the report link.
    """
    from backend.engine.webhooks import _build_nightly_slack_payload, post_nightly_slack

    report_url = f"{report_base_url}/playwright?suite_run_id={suite_run_id}"
    poll_interval = settings.nightly_poll_interval_seconds
    poll_timeout = settings.nightly_poll_timeout_seconds

    logger.info("[nightly] Polling suite_run_id=%s (timeout=%ds)", suite_run_id, poll_timeout)

    try:
        elapsed = 0.0
        run_data = None
        while elapsed <= poll_timeout:
            run_data = playwright_suite_run_store.get_run(suite_run_id)
            if run_data is not None:
                status = run_data.get("status", "")
                if status in ("completed", "failed"):
                    break
            if poll_interval > 0:
                await asyncio.sleep(poll_interval)
            elapsed += poll_interval if poll_interval > 0 else 1

        if run_data is None or run_data.get("status") not in ("completed", "failed"):
            # Poll timeout: post AC-ERROR-1 shaped error message
            logger.warning(
                "[nightly] Poll timeout after %ds for suite_run_id=%s — posting error Slack",
                poll_timeout,
                suite_run_id,
            )
            # Mark the run as failed so the store is consistent
            try:
                playwright_suite_run_store.update_suite_totals_and_status(
                    suite_run_id=suite_run_id,
                    status="failed",
                    outcome="FAIL",
                    fail_reason=f"Nightly poll timeout after {poll_timeout}s",
                    completed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                )
            except Exception as mark_exc:
                logger.error("[nightly] Could not mark run failed after timeout: %s", mark_exc)

            error_payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"❌ Nightly suite — poll timeout after {poll_timeout // 60} min",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Suite run `{suite_run_id}` did not complete within the polling window. "
                                    f"Check CloudWatch log group `/ecs/vqa-backend` for details.",
                        },
                    },
                ]
            }
            await post_nightly_slack(slack_webhook_url, error_payload)
            return

        # Run reached terminal state — build and post the compact payload
        passed = run_data.get("passed", 0)
        failed_count = run_data.get("failed", 0)
        logger.info(
            "[nightly] Terminal status=%s passed=%d failed=%d — posting Slack",
            run_data.get("status"),
            passed,
            failed_count,
        )
        payload = _build_nightly_slack_payload(
            suite_run_id=suite_run_id,
            run_data=run_data,
            report_url=report_url,
        )
        slack_ok = await post_nightly_slack(slack_webhook_url, payload)
        if not slack_ok:
            logger.error(
                "[nightly] Slack delivery failed for suite_run_id=%s — see logs above for HTTP status",
                suite_run_id,
            )

    except Exception as exc:
        # Orchestrator or store raised — post AC-ERROR-1 error Slack
        logger.error("[nightly] Unexpected error during poll/notify: %s", exc, exc_info=True)
        error_payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Nightly suite — internal error",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Suite run `{suite_run_id}` could not complete: `{str(exc)[:200]}`\n"
                                "Check CloudWatch log group `/ecs/vqa-backend` for the full stack trace.",
                    },
                },
            ]
        }
        try:
            await post_nightly_slack(slack_webhook_url, error_payload)
        except Exception as slack_exc:
            logger.error("[nightly] Could not send error Slack notification: %s", slack_exc)


@playwright_router.post(
    "/nightly",
    response_model=NightlyRunResponse,
    status_code=202,
    summary="Trigger the nightly scheduled Playwright regression suite",
    description=(
        "Called by AWS EventBridge Scheduler at 06:00 UTC daily. "
        "Dispatches the pinned two-test regression subset, polls to terminal "
        "state in a background task, and posts a compact Slack Block Kit "
        "notification with results. Returns 202 Accepted immediately. "
        "Auth: X-VQA-API-Key header required (same as all /playwright/* endpoints)."
    ),
)
async def run_nightly_playwright_suite(
    request: Request,
) -> NightlyRunResponse:
    """
    POST /api/playwright/nightly — Trigger the nightly regression suite.

    Does NOT accept a request body.  All parameters are pinned in Settings:
    - settings.nightly_mode      (default: pinned; 'all' expands to every registry test)
    - settings.nightly_test_ids  (default: qa-170-search.test, qa-172-production.test;
                                  only used when nightly_mode == 'pinned')
    - settings.nightly_env       (default: test)
    - settings.nightly_user      (default: DemoProdDirector)
    - settings.nightly_browser   (default: chromium)

    Returns 202 Accepted with {suite_run_id, status: "started"} immediately.
    Poll GET /playwright/run-all/{suite_run_id}/report for results.
    """
    # Clear stale runs (>2 hours old) before checking for an active run
    playwright_suite_run_store.abort_stale_runs(max_age_minutes=120)

    active_run_id = playwright_suite_run_store.get_active_run_id()
    if active_run_id is not None:
        raise HTTPException(
            status_code=429,
            detail="Suite run already in progress",
        )

    # Resolve tests based on nightly_mode
    #   'pinned' — validate each ID in settings.nightly_test_ids against the registry
    #   'all'    — expand to every .test.ts file in the registry (matches run-all)
    registry = _get_registry()
    tests: list[dict] = []
    if settings.nightly_mode == "all":
        all_tests = registry.list_tests()
        tests = [t for t in all_tests if t.get("file", "").endswith(".test.ts")]
        if not tests:
            logger.error("[nightly] mode='all' but registry returned no .test.ts entries")
            raise HTTPException(
                status_code=500,
                detail="Nightly mode='all' but no tests found in registry",
            )
    else:
        for test_id in settings.nightly_test_ids:
            meta = registry.get_test(test_id)
            if meta is None:
                logger.error(
                    "[nightly] Test ID %r not found in registry — aborting nightly run", test_id
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"Nightly test ID not found in registry: {test_id}",
                )
            tests.append(meta)

    # Create the suite run record
    suite_run_id = f"nightly-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_data: dict = {
        "suite_run_id": suite_run_id,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "total": len(tests),
        "passed": 0,
        "failed": 0,
        "results": [
            {
                "test_id": t["id"],
                "name": t.get("description", t["id"]),
                "status": "PENDING",
                "duration_ms": 0.0,
                "error_snippet": None,
            }
            for t in tests
        ],
        "outcome": None,
        "fail_reason": None,
    }
    playwright_suite_run_store.create_run(suite_run_id, run_data)

    # Derive the public base URL for the report link
    scheme = request.headers.get("X-Forwarded-Proto") or request.url.scheme
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or settings.external_host
    report_base_url = f"{scheme}://{host}"

    # Launch the group orchestrator + poll-and-notify as background tasks
    asyncio.create_task(
        _run_group_orchestrator(
            suite_run_id,
            tests,
            settings.nightly_env,
            settings.nightly_user,
            settings.nightly_browser,
        )
    )
    asyncio.create_task(
        _nightly_poll_and_notify(
            suite_run_id=suite_run_id,
            slack_webhook_url=settings.nightly_slack_webhook_url,
            report_base_url=report_base_url,
        )
    )

    logger.info(
        "[nightly] Suite dispatched: suite_run_id=%s mode=%s tests=%d env=%s user=%s browser=%s",
        suite_run_id,
        settings.nightly_mode,
        len(tests),
        settings.nightly_env,
        settings.nightly_user,
        settings.nightly_browser,
    )

    return NightlyRunResponse(suite_run_id=suite_run_id)


def scrub_secrets(text: str):
    """
    Mask any passwords, bearer tokens, or authorization signatures in the compiled prompt.
    Leverages the existing _scrub_line function on each line of the output text.
    """
    if not text:
        return ""
    lines = text.splitlines()
    scrubbed_lines = [_scrub_line(line) for line in lines]
    return "\n".join(scrubbed_lines)


def _extract_test_source_code(test_file: str) -> str:
    """
    Safely read and format local test file contents.
    Handles deterministic Head/Tail truncation if lines > 300.
    """
    if not test_file:
        return "// [Source code unavailable - empty file path]"

    # Resolve file path relative to 'playwright' directory
    full_path = Path("playwright") / test_file
    if not full_path.exists():
        # Try relative to project root directly (just in case)
        full_path = Path(test_file)

    if not full_path.exists() or not full_path.is_file():
        logger.warning("Test source file not found at %s", full_path)
        return f"// [Source code unavailable - file not found at {test_file}]"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning("Could not read test source file %s: %s", full_path, e)
        return f"// [Source code unavailable - failed to read file: {str(e)}]"

    lines = content.splitlines()
    if len(lines) <= 300:
        return content

    # Apply deterministic Head/Tail truncation (100 lines head, 150 lines tail)
    head_lines = lines[:100]
    tail_lines = lines[-150:]
    truncated_content = (
        "\n".join(head_lines) +
        "\n\n// ... [TRUNCATED FOR BREVITY - middle section omitted to respect token limits] ...\n\n" +
        "\n".join(tail_lines)
    )
    return truncated_content


@playwright_router.post(
    "/heal-prompt",
    response_model=PlaywrightHealPromptResponse,
    summary="Generate a consolidated AI test healing prompt for failed tests in a suite run",
)
async def generate_heal_prompt(request: PlaywrightHealPromptRequest) -> PlaywrightHealPromptResponse:
    """
    Validate and compile a highly structured, copy-ready AI-optimized prompt
    for correcting failed static tests inside a parallel suite run.
    """
    run_id = request.run_id
    run_data = playwright_suite_run_store.get_run(run_id)
    if run_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Suite run '{run_id}' not found",
        )

    if run_data.get("status") == "running":
        raise HTTPException(
            status_code=400,
            detail=f"Suite run '{run_id}' is still in progress",
        )

    # Filter out failed results
    failed_results = [res for res in run_data.get("results", []) if res.get("status") == "FAIL"]
    if not failed_results:
        raise HTTPException(
            status_code=400,
            detail=f"Suite run '{run_id}' has no failed tests to heal",
        )

    # Build prompt content
    registry = _get_registry()
    sections = []

    for res in failed_results:
        test_id = res.get("test_id", "")
        test_name = res.get("name", test_id)
        error_snippet = res.get("error_snippet", "Unknown failure")

        # Resolve source code
        test_meta = registry.get_test(test_id)
        if test_meta:
            test_file = test_meta.get("file", "")
            source_code = _extract_test_source_code(test_file)
            file_path_disp = test_file or "[Unknown Path]"
        else:
            source_code = "// [Source code unavailable - test ID not found in registry]"
            file_path_disp = "[Unknown Path]"

        section = f"""---

## Failed Test: {test_name}
- **File Path**: `{file_path_disp}`
- **Error Assertion**:
```text
{error_snippet}
```

- **Source Code**:
```typescript
{source_code}
```"""
        sections.append(section)

    compiled_prompt_raw = f"""# Playwright Test Healing Request

You are an expert Playwright automation engineer. Below is a set of failing test files from our test suite, along with their exact error stack traces and assertion messages.

## System Context
- **Testing Framework**: Playwright (TypeScript)
- **Application Stack**: React 19 / Angular SPA with PrimeNG UI components
- **Conventions**:
  - We use explicit, deterministic Playwright state assertions (e.g., `await expect(locator).toBeVisible()`).
  - Do NOT use visual delta or DOM-count diffing for success checks.
  - Handle PrimeNG-specific elements properly (dropdown overlays, animations, loading states).

## Instructions
1. For each failed file, analyze the error trace against the provided source code.
2. Provide a fully corrected, drop-in replacement for the test file inside a single standard markdown code block.
3. Keep all existing imports, session states, and test setup boilerplate intact unless they are directly causing the failure.
4. Explain the root cause of the failure and the specific correction you made in a brief bulleted list under each file block.

{"\n\n".join(sections)}

---
"""

    # Mask any sensitive secrets/tokens/credentials
    compiled_prompt = scrub_secrets(compiled_prompt_raw)

    logger.info(
        "Successfully generated compiled AI healing prompt for suite run %s containing %d failures.",
        run_id,
        len(failed_results),
    )

    return PlaywrightHealPromptResponse(prompt=compiled_prompt)


def _build_failure_digest(run_data: dict) -> list[FailureDigestEntry] | None:
    if run_data.get("status") in ("completed", "failed") and run_data.get("failed", 0) > 0:
        return [
            FailureDigestEntry(
                test_id=res["test_id"],
                name=res["name"],
                error_summary=_clean_error_to_summary(res.get("error_snippet")),
            )
            for res in run_data.get("results", [])
            if res.get("status") == "FAIL"
        ]
    return None


@playwright_router.get(
    "/run-all/{suite_run_id}/report",
    response_model=PlaywrightSuiteReportResponse,
    summary="Get the consolidated report for a suite run",
)
async def get_suite_run_report(suite_run_id: str) -> PlaywrightSuiteReportResponse:
    run_data = playwright_suite_run_store.get_run(suite_run_id)
    if run_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Suite run '{suite_run_id}' not found",
        )

    # Update last polled timestamp if the run is still active
    if run_data.get("status") == "running":
        _suite_run_last_poll[suite_run_id] = time.time()

    digest = _build_failure_digest(run_data)
    return PlaywrightSuiteReportResponse(**run_data, failure_digest=digest)


@playwright_router.post(
    "/run-all/{suite_run_id}/stop",
    response_model=PlaywrightSuiteReportResponse,
    summary="Stop/cancel a running parallel suite run",
)
async def stop_suite_run(suite_run_id: str) -> PlaywrightSuiteReportResponse:
    run_data = playwright_suite_run_store.get_run(suite_run_id)
    if run_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Suite run '{suite_run_id}' not found",
        )

    if run_data["status"] != "running":
        # If already finished, just return it
        return PlaywrightSuiteReportResponse(**run_data)

    # Mark as failed / stopped
    run_data["status"] = "failed"
    run_data["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_data["outcome"] = "FAIL"
    run_data["fail_reason"] = "Suite run stopped by user"

    # Mark any PENDING or RUNNING tests as FAIL
    for res in run_data["results"]:
        if res["status"] in ("PENDING", "RUNNING"):
            res["status"] = "FAIL"
            res["error_snippet"] = "Suite run stopped by user."
            run_data["failed"] += 1

    playwright_suite_run_store.update_run(suite_run_id, run_data)

    # Terminate any running subprocesses for this suite run
    for pid_key, pid in list(_playwright_pids.items()):
        if pid_key.startswith(f"{suite_run_id}-"):
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info("[%s] SIGTERM sent to PID %d", suite_run_id, pid)
            except ProcessLookupError:
                logger.debug("[%s] PID %d already exited", suite_run_id, pid)
            except Exception as e:
                logger.warning("[%s] Could not SIGTERM PID %d: %s", suite_run_id, pid, e)
            _playwright_pids.pop(pid_key, None)

    digest = _build_failure_digest(run_data)
    return PlaywrightSuiteReportResponse(**run_data, failure_digest=digest)


# ---------------------------------------------------------------------------
# Shutdown cleanup helper (called by main.py lifespan)
# ---------------------------------------------------------------------------


async def cleanup_playwright_processes(timeout: float = 5.0) -> None:
    """
    Send SIGTERM to all tracked Playwright subprocess PIDs on server shutdown.

    Called from backend/main.py lifespan teardown to prevent orphan processes.
    """
    if not _playwright_pids:
        return

    logger.info(
        "Sending SIGTERM to %d tracked Playwright process(es)...",
        len(_playwright_pids),
    )

    for run_id, pid in list(_playwright_pids.items()):
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[%s] SIGTERM sent to PID %d", run_id, pid)
        except ProcessLookupError:
            logger.debug("[%s] PID %d already exited", run_id, pid)
        except Exception as e:
            logger.warning("[%s] Could not SIGTERM PID %d: %s", run_id, pid, e)

    _playwright_pids.clear()
