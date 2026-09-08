"""
vQA — FastAPI Application Entrypoint
======================================
Module: backend/main.py

This is the top-level module that creates and configures the FastAPI
application instance.  It:

  1. Creates the FastAPI app with metadata for OpenAPI docs
  2. Configures CORS (Cross-Origin Resource Sharing) for the React frontend
  3. Registers API route handlers from ``backend/api/routes.py``
  4. Sets up application lifespan events (startup/shutdown)
  5. Configures structured logging

Running Locally
---------------
    # From the project root:
    cd backend
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

    # Or via Docker:
    docker compose up --build

OpenAPI Documentation
---------------------
Once running, interactive API docs are available at:
  - Swagger UI:  http://localhost:8000/docs
  - ReDoc:       http://localhost:8000/redoc

Dependencies
------------
  - ``fastapi``
  - ``backend/api/routes.py`` — route handlers
  - ``backend/config.py``     — settings

See Also
--------
  - ``DEPLOYMENT.md``        — production deployment guide
  - ``docker/Dockerfile``    — container build
"""

# ── Phase 8: Python 3.13 Import Hardening ─────────────────────────
# Pre-import numpy/sklearn before pydantic (imported by config.py)
# partially initializes numpy. This resolves the randbits ImportError
# on Python 3.13 where changed import resolution paths can break the
# scipy.sparse -> scipy._lib._util chain.
try:
    import numpy as _np  # noqa: F401
    from sklearn.feature_extraction.text import TfidfVectorizer as _tv  # noqa: F401
except ImportError:
    pass  # Optional dependencies; KB retrieval will skip if absent

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.ai_review_routes import ai_review_router, cleanup_ai_review_processes
from backend.api.memory_watch_routes import (
    cleanup_memory_watch_processes,
    memory_watch_router,
)
from backend.api.playwright_routes import cleanup_playwright_processes, playwright_router
from backend.api.routes import router, ws_router
from backend.api.session_routes import session_router, session_ws_router  # Phase 2
from backend.config import settings

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """
    Configure structured logging for the application.

    Phase 7: delegates to backend.logging_config.configure_logging() which
    selects between JSON (production, LOG_FORMAT=json) and plain-text (dev,
    LOG_FORMAT=text) based on the LOG_FORMAT environment variable.
    The previous basicConfig call is replaced so CloudWatch Logs Insights can
    aggregate structured ``event`` fields via Metric Filters.
    """
    from backend.logging_config import configure_logging as _setup
    _setup()


# ---------------------------------------------------------------------------
# Browser lifecycle helpers
# ---------------------------------------------------------------------------


async def _drain_all_managers(timeout_per_manager: float = 5.0) -> None:
    """
    Close all active ``BrowserManager`` instances during server shutdown.

    Called from the FastAPI lifespan teardown (after ``yield``) so that
    uvicorn's own SIGINT/SIGTERM handling triggers clean browser teardown
    without leaving zombie Chromium processes.

    Each manager is closed with an individual timeout to prevent a stuck
    browser from blocking the entire shutdown sequence.

    Parameters
    ----------
    timeout_per_manager : float
        Seconds to wait for each ``manager.close()`` before giving up.
        Default: 5 seconds.
    """
    from backend.browser.context import get_all_managers

    _drain_logger = logging.getLogger(__name__)
    managers = get_all_managers()
    if not managers:
        return

    _drain_logger.info("Draining %d active BrowserManager(s) on shutdown...", len(managers))
    for run_id, manager in managers.items():
        try:
            await asyncio.wait_for(manager.close(), timeout=timeout_per_manager)
            _drain_logger.info("[%s] BrowserManager closed cleanly.", run_id)
        except asyncio.TimeoutError:
            _drain_logger.warning(
                "[%s] BrowserManager.close() timed out after %.0fs — Chromium process may linger.",
                run_id,
                timeout_per_manager,
            )
        except Exception as exc:
            _drain_logger.warning("[%s] BrowserManager.close() raised: %s", run_id, exc)
    _drain_logger.info("Browser drain complete.")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup and shutdown events.

    Startup:
      - Configures logging
      - Logs the application configuration summary
      - Validates connectivity to external services (optional)

    Shutdown:
      - Logs shutdown message
      - Could clean up active browser sessions if needed

    Args
    ----
    app : FastAPI
        The FastAPI application instance.
    """
    # ── Startup ───────────────────────────────────────────────────────
    _configure_logging()

    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("🔬 vQA — Autonomous Web Agent")
    logger.info("=" * 60)
    logger.info("Mode:       %s", settings.vqa_mode)
    logger.info("Target URL: %s", settings.target_url)
    logger.info("Jira:       %s", settings.jira_domain)
    logger.info("LLM:        %s (%s)", settings.bedrock_model_id, settings.aws_bedrock_region)
    logger.info("S3 Bucket:  %s/%s", settings.s3_bucket, settings.s3_prefix)
    logger.info("API Port:   %d", settings.api_port)
    logger.info("Log Level:  %s", settings.log_level)
    logger.info("=" * 60)

    # ── Register human takeover WS broadcaster ────────────────────────
    # human_takeover_node calls this directly (not via state) to send the
    # WS event BEFORE blocking on asyncio.Event.wait().
    from backend.api.routes import (
        _broadcast_human_takeover,
        _broadcast_hitl_action_recorded,
        _broadcast_hitl_screenshot,
        _broadcast_hitl_dialog,
    )
    from backend.engine.human_takeover import (
        set_hitl_action_broadcaster,
        set_hitl_screenshot_broadcaster,
        set_hitl_dialog_broadcaster,
        set_ws_broadcaster,
    )

    set_ws_broadcaster(_broadcast_human_takeover)
    set_hitl_screenshot_broadcaster(_broadcast_hitl_screenshot)
    set_hitl_action_broadcaster(_broadcast_hitl_action_recorded)
    set_hitl_dialog_broadcaster(_broadcast_hitl_dialog)
    logger.info("HumanTakeover: WS broadcasters registered (events, screencast, echo, dialogs)")

    # ── Prune expired pinned TestPlan files (Lock B TTL maintenance) ─────
    # Runs synchronously at startup so the store is clean before any request
    # is served. Errors are logged but never fatal — a slightly stale store
    # is safer than blocking startup.
    try:
        from backend.engine.pinned_plans import prune_expired as _prune_pinned
        _pruned_count = _prune_pinned()
        logger.info("PinnedPlans: startup prune complete — %d expired file(s) removed", _pruned_count)
    except Exception as _prune_err:
        logger.error("PinnedPlans: startup prune failed (non-fatal): %s", _prune_err)

    # ── Abort stale Playwright suite runs (ALB desync recovery) ────────
    try:
        from backend.storage.playwright_suite_runs import playwright_suite_run_store
        playwright_suite_run_store.abort_stale_runs()
        logger.info("PlaywrightSuiteRunStore: stale runs successfully aborted")
    except Exception as e:
        logger.error("Failed to abort stale Playwright suite runs on startup: %s", e)

    # ── Start suite scheduler (Phase 7C) ──────────────────────────────
    from backend.engine.scheduler import start_scheduler, stop_scheduler

    scheduler_task = await start_scheduler()

    # ── Start codegen session TTL cleanup ────────────────────────────
    from backend.engine.codegen_session import _cleanup_expired_sessions

    asyncio.create_task(_cleanup_expired_sessions())
    logger.info("Codegen: session TTL cleanup task started")

    # ── Phase 2: SessionManager startup (tick loop) ───────────────────
    # The SessionManager background tick handles JWT expiry + allocator
    # reconciliation.  drain_all() fires in the shutdown block below.
    from backend.session import get_session_manager as _get_session_mgr

    _session_mgr = _get_session_mgr()
    await _session_mgr.start_tick_loop()
    logger.info("SessionManager: background tick loop started (interval=%ds)",
                int(os.environ.get("SESSION_TICK_INTERVAL_SECONDS", "30")))

    # ── PlaywrightRAG staleness watcher ──────────────────────────────
    from backend.kb.playwright_rag import playwright_rag

    async def _playwright_rag_staleness_watcher() -> None:
        """Check PlaywrightRAG index freshness every 60s; reload if stale."""
        _rag_logger = logging.getLogger("backend.kb.playwright_rag")
        while True:
            await asyncio.sleep(60)
            try:
                if playwright_rag.is_stale():
                    playwright_rag.reload()
                    _rag_logger.info("PlaywrightRAG: reloaded (file changes detected)")
            except Exception as exc:
                _rag_logger.warning("PlaywrightRAG: staleness check failed: %s", exc)

    rag_watcher_task = asyncio.create_task(_playwright_rag_staleness_watcher())
    logger.info("PlaywrightRAG: staleness watcher started (60s interval)")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────
    # Uvicorn triggers this block on SIGINT (Ctrl+C) or SIGTERM (Docker stop).
    logger.info("vQA shutting down...")

    # Cancel PlaywrightRAG staleness watcher
    rag_watcher_task.cancel()

    # Stop scheduler first
    await stop_scheduler(scheduler_task)

    # Terminate any active Playwright test subprocesses (AC-BACK-11)
    logger.info("Terminating tracked Playwright subprocesses...")
    await cleanup_playwright_processes(timeout=5.0)
    await cleanup_ai_review_processes()
    await cleanup_memory_watch_processes()

    # Drain browser sessions
    logger.info("Draining active browser sessions...")
    await _drain_all_managers(timeout_per_manager=8.0)

    # Phase 2: drain all per-user sessions (AC-ASYNC-3)
    from backend.session import get_session_manager as _get_session_mgr_shutdown
    await _get_session_mgr_shutdown().drain_all()
    logger.info("SessionManager: all sessions drained.")

    logger.info("vQA shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="vQA — Autonomous Web Agent API",
    description=(
        "REST and WebSocket API for the vQA autonomous testing agent. "
        "Fetches Jira Acceptance Criteria, executes visual regression tests "
        "via Playwright, and produces granular HTML audit reports with "
        "embedded session recordings.\n\n"
        "**Execution modes:**\n"
        "- `interactive` — live browser streaming via noVNC + WebSocket logs\n"
        "- `headless` — API-only for CI/CD pipeline gating\n\n"
        "**Source:** Merged from pwtgen (Jira client) + vProMediaRegressionAgent (LangGraph engine)"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Custom exception handlers
# ---------------------------------------------------------------------------

_ROLE_PRODUCT_KEYWORDS = ("not available for product", "unknown product")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert role↔product mismatch validation errors to 400 (AC-ERROR-3).

    FastAPI converts Pydantic ValidationError to 422 by default. Per AC-ERROR-3,
    a mismatched role/product must return 400 so the frontend and callers can
    distinguish a semantic business-rule violation from a malformed request.
    """
    errors = exc.errors()
    for error in errors:
        msg = str(error.get("msg", "")).lower()
        if any(kw in msg for kw in _ROLE_PRODUCT_KEYWORDS):
            return JSONResponse(
                status_code=400,
                content={"detail": error.get("msg", "Role/product mismatch.")},
            )
    return JSONResponse(status_code=422, content={"detail": errors})


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
# Allow the React frontend (localhost:3000 in dev, or any origin in Docker)
# to make requests to the FastAPI backend.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React dev server
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8000",  # Self (Swagger UI)
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://vqa.vcreative.net",  # Production origin
    ],
    allow_credentials=True,
    # Phase 2: tightened from ["*"] to explicit lists (reduces CORS attack surface)
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "Authorization", "X-VQA-API-Key", "X-Request-Id"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Inject security headers into every response.
    Specifically allows the VNC iframe to be embedded by the same origin
    and hardens CSP (TD-032).
    """
    response = await call_next(request)

    # Allow framing from same origin (vQA dashboard embedding its own reports/VNC)
    # Note: 'frame-ancestors' in CSP takes precedence over X-Frame-Options
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    return response


# ---------------------------------------------------------------------------
# Register routes
# ---------------------------------------------------------------------------
# All REST endpoints are served under /api so the ALB routing rule
# (path-pattern='/api/*' → backend target group) correctly resolves routes.
# The playwright_router has its own prefix="/playwright" baked in; mounting
# it under /api gives: /api/playwright/tests, /api/playwright/run, etc.
# The ws_router handles WebSocket endpoints (/ws/{run_id}) without a prefix
# since the ALB has a separate rule for /ws/*.

app.include_router(router, prefix="/api")
app.include_router(ws_router)
app.include_router(playwright_router, prefix="/api")  # Playwright Standard Library API (FEAT-052)
app.include_router(ai_review_router, prefix="/api")
app.include_router(memory_watch_router, prefix="/api")
# Phase 2: session lifecycle endpoints + session-control WebSocket
app.include_router(session_router, prefix="/api")
app.include_router(session_ws_router)  # /ws/session/{id} — no /api prefix (matches ALB /ws/* rule)


# ---------------------------------------------------------------------------
# Bare /health passthrough (Docker HEALTHCHECK + ALB target-group probe)
# ---------------------------------------------------------------------------
# The ALB target-group health-check hits the backend directly at /health
# (not through the /api/* listener rule), so a bare endpoint is required.
# This delegates to the same logic as GET /api/health.


@app.get("/health", include_in_schema=False)
async def health_passthrough():
    """Bare /health alias — delegates to /api/health for container probes."""
    import time as _t

    from backend.store import get_state_store

    _rs = get_state_store()
    active = sum(1 for r in _rs.values() if isinstance(r, dict) and r.get("status") == "running")
    from backend.config import settings as _s

    return {
        "status": "ok",
        "mode": _s.vqa_mode,
        "version": "1.0.0",
        "build_number": _s.vqa_build_number,
        "uptime_seconds": round(_t.monotonic()),
        "active_runs": active,
    }


# ---------------------------------------------------------------------------
# Theme Preference (TASK-084)
# ---------------------------------------------------------------------------


@app.get("/api/theme")
async def get_theme():
    """Return the current VNC theme preference."""
    return {"theme": settings.vnc_theme}


@app.post("/api/theme")
async def set_theme(theme: Literal["light", "dark"]):
    """Update the current VNC theme preference."""
    # We update the settings singleton so all future takeovers use it.
    # Note: this is not persistent across restarts.
    object.__setattr__(settings, "vnc_theme", theme)
    logger.info("VNC Theme updated to: %s", theme)
    return {"theme": settings.vnc_theme}


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API docs."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/docs")
