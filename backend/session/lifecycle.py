"""
vQA — Session Lifecycle Teardown
==================================
Module: backend/session/lifecycle.py

Implements the 7-step session termination sequence described in the
per-user-session-isolation architecture design:

  Step 1: Transition session → TERMINATING (via SessionManager).
  Step 2: Kill all active Playwright browser contexts (active_run_ids).
  Step 3: Close the SessionBrowserManager for this session.
  Step 4: Stop the Xvfb/x11vnc/websockify triplet via DisplayAllocator.release().
  Step 5: Remove the session from the nginx map (nginx_map.remove()).
  Step 6: Emit session.terminated structured JSON log.
  Step 7: Remove the session from the SessionManager registry.

Phases
------
Phase 1 (this file): scaffolds the terminate() function with the full
  7-step skeleton; Steps 2-3 (Playwright teardown) are no-ops until
  Phase 4 wires the run/execute path through session.

Phase 4+ adds: kill active run_ids, close SessionBrowserManager per
  session_id, send session_terminated WS event to the frontend.
"""

from __future__ import annotations

import logging

from backend.session.models import Session, SessionState

logger = logging.getLogger(__name__)


async def terminate(
    session: Session,
    *,
    reason: str = "explicit",
    manager=None,
) -> None:
    """
    Execute the 7-step session termination sequence.

    Parameters
    ----------
    session
        The Session dataclass to terminate.
    reason
        Human-readable termination reason (e.g., "jwt_expired",
        "heartbeat_timeout", "container_drain", "explicit").
    manager
        Optional SessionManager reference for registry removal.
        If None, the module-level singleton is used.
    """
    session_id = session.session_id

    # --- Step 1: Transition to TERMINATING ---
    if session.state not in (SessionState.TERMINATING, SessionState.TERMINATED):
        session.state = SessionState.TERMINATING
        logger.info(
            '{"event": "session.terminating", "session_id": "%s", "reason": "%s"}',
            session_id, reason,
        )

    # --- Step 2 & 3: Kill Playwright (Phase 4+) ---
    # In Phase 1, active_run_ids is always empty (no run→session wiring yet).
    for run_id in list(session.active_run_ids):
        try:
            _terminate_run(run_id, session_id)
        except Exception as exc:
            logger.error(
                "lifecycle.terminate: error killing run %s for session %s: %s",
                run_id, session_id, exc,
            )

    # --- Step 4: Release display slot ---
    try:
        from backend.session.allocator import get_allocator
        get_allocator().release(session.display_num)
    except Exception as exc:
        logger.error(
            "lifecycle.terminate: error releasing display :%d for session %s: %s",
            session.display_num, session_id, exc,
        )

    # --- Step 5: Remove from nginx map ---
    try:
        from backend.session.nginx_map import get_nginx_map
        get_nginx_map().remove(session_id)
    except Exception as exc:
        logger.error(
            "lifecycle.terminate: error removing nginx map entry for session %s: %s",
            session_id, exc,
        )

    # --- Step 6: Emit session.terminated log ---
    session.state = SessionState.TERMINATED
    logger.info(
        '{"event": "session.terminated", "session_id": "%s", '
        '"user_email": "%s", "reason": "%s"}',
        session_id, session.user_email, reason,
    )

    # --- Step 7: Remove from SessionManager registry ---
    if manager is None:
        try:
            from backend.session.manager import get_session_manager
            manager = get_session_manager()
        except Exception:
            pass
    if manager is not None:
        manager.remove_session(session_id)


def _terminate_run(run_id: str, session_id: str) -> None:
    """
    Mark a run as FAILED with reason session_terminated.

    Phase 1 stub — full implementation in Phase 4 when the run→session
    wiring exists.  Logs an informational message only.
    """
    logger.info(
        '{"event": "run.session_terminated", "run_id": "%s", "session_id": "%s"}',
        run_id, session_id,
    )
