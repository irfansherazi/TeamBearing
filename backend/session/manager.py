"""
vQA — Session Manager
======================
Module: backend/session/manager.py

The SessionManager is the central controller for the per-user session
isolation subsystem.  It owns the in-memory registry of all active Sessions
and orchestrates state transitions, periodic health checks, and lifecycle
teardown.

Architecture (per-user-session-isolation, Phase 1)
----------------------------------------------------
- One SessionManager singleton per uvicorn worker (--workers 1 enforced
  by supervisord.conf — Playwright is not fork-safe).
- Sessions dict is guarded by an asyncio.Lock to serialize state transitions.
- A background task (_tick) runs every SESSION_TICK_INTERVAL_SECONDS to:
    1. Terminate sessions past jwt_valid_until + REBIND_GRACE_SECONDS.
    2. Call DisplayAllocator.reconcile() to detect leaked display slots.
- drain_all() is called from the FastAPI lifespan shutdown to cleanly
  terminate all sessions before the container exits.

State Transitions
-----------------
See backend/session/models.py for the full state machine diagram.

Key transitions managed here:
  on_ws_connect(session_id)        → READY / DETACHED_GRACE → ATTACHED
  on_ws_disconnect(session_id)     → ATTACHED → TERMINATING (grace=0)
                                                → DETACHED_GRACE (grace>0)
  on_heartbeat_timeout(session_id) → * → TERMINATING
  terminate_session(session_id)    → * → TERMINATING → TERMINATED
  drain_all()                      → all sessions → TERMINATING → TERMINATED

JWT Expiry Contract (ADR-12)
-----------------------------
  jwt_valid_until = most recent JWT exp (updated on rebind).
  Periodic tick fires every 30s.
  Sessions are terminated when: now >= jwt_valid_until + REBIND_GRACE_SECONDS.
  Worst-case linger: REBIND_GRACE_SECONDS(60) + SESSION_TICK_INTERVAL_SECONDS(30) = 90s.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Optional

from backend.session.models import Session, SessionState

logger = logging.getLogger(__name__)


class SessionManager:
    """
    In-memory registry and state-machine engine for per-user Sessions.

    Attributes
    ----------
    sessions : dict[str, Session]
        Map of session_id → Session.  Guarded by self._lock.
    _lock : asyncio.Lock
        Serialises state transitions and session creation/removal.

    Usage
    -----
        mgr = get_session_manager()
        session = await mgr.start_session(user_id, user_email, jwt_exp)
        ...
        await mgr.terminate_session(session_id, reason="heartbeat_timeout")
    """

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._tick_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[Session]:
        """Return the Session for session_id, or None if not found."""
        return self.sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the registry (called after TERMINATED)."""
        self.sessions.pop(session_id, None)

    def add_active_run_id(self, session_id: str, run_id: str) -> None:
        """Append run_id to session.active_run_ids (AC-ENTRY-3)."""
        session = self.sessions.get(session_id)
        if session is None:
            logger.warning(
                '{"event": "session.add_run_missing", "session_id": "%s", "run_id": "%s"}',
                session_id, run_id,
            )
            return
        if run_id not in session.active_run_ids:
            session.active_run_ids.append(run_id)

    def remove_active_run_id(self, session_id: str, run_id: str) -> None:
        """Remove run_id from session.active_run_ids (called on run completion/failure)."""
        session = self.sessions.get(session_id)
        if session is None:
            return
        try:
            session.active_run_ids.remove(run_id)
        except ValueError:
            pass

    async def start_session(
        self,
        user_id: str,
        user_email: str,
        jwt_exp: float,
    ):
        """
        Create and register a new Session for the authenticated user.

        Acquires a display slot from DisplayAllocator.  Returns:
          - A ``Session`` in state READY on success.
          - A ``CapacityReachedResult`` when all slots are taken.

        Phase 2: integrates DisplayAllocator.acquire() and creates the Session
        dataclass.  The Session is added to self.sessions and transitioned to
        READY before returning.

        Parameters
        ----------
        user_id
            String form of the JWT vc_id (cast at the call site).
        user_email
            JWT-authenticated email; stored as session.user_email.
        jwt_exp
            Unix timestamp of the JWT exp claim; stored as jwt_valid_until.

        Returns
        -------
        Session
            New session in READY state.
        CapacityReachedResult
            When all display slots are occupied.
        """
        from backend.session.allocator import get_allocator, CapacityReachedResult
        import uuid as _uuid

        allocator = get_allocator()
        slot = allocator.acquire()

        if isinstance(slot, CapacityReachedResult):
            logger.info(
                '{"event": "session.capacity_reached", "user_email": "%s", '
                '"active_sessions": %d}',
                user_email, slot.active_sessions,
            )
            return slot

        if slot is None:
            logger.error(
                '{"event": "session.allocator_failed", "user_email": "%s"}',
                user_email,
            )
            from backend.session.allocator import CapacityReachedResult as _CRR
            return _CRR(active_sessions=len(self.sessions), retry_after_s=30)

        session_id = str(_uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_email=user_email,
            user_id=user_id,
            display_num=slot["display_num"],
            vnc_port=slot["vnc_port"],
            jwt_valid_until=jwt_exp,
            state=SessionState.REQUESTED,
        )

        async with self._lock:
            self.sessions[session_id] = session
            self._transition(session_id, SessionState.READY)

        logger.info(
            '{"event": "session.started", "session_id": "%s", "user_email": "%s", '
            '"display_num": %d}',
            session_id, user_email, slot["display_num"],
        )
        return session

    def rebind_session(self, session_id: str, new_jwt_exp: float) -> None:
        """
        Update jwt_valid_until for a session (called on successful rebind).

        Parameters
        ----------
        session_id
            The session to update.
        new_jwt_exp
            Unix timestamp of the new JWT exp claim.
        """
        session = self.sessions.get(session_id)
        if session is not None:
            session.jwt_valid_until = new_jwt_exp
            logger.info(
                '{"event": "session.rebound", "session_id": "%s", "new_exp": %f}',
                session_id, new_jwt_exp,
            )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition(self, session_id: str, new_state: SessionState) -> None:
        """
        Apply a state transition to a session.

        Logs the transition as a structured event.  Does NOT acquire the lock
        (caller is responsible for synchronisation).
        """
        session = self.sessions.get(session_id)
        if session is None:
            logger.warning("_transition: session %s not found", session_id)
            return
        old_state = session.state
        session.state = new_state
        logger.info(
            '{"event": "session.state_transition", "session_id": "%s", '
            '"from": "%s", "to": "%s"}',
            session_id, old_state.value, new_state.value,
        )

    def on_ws_connect(self, session_id: str) -> None:
        """
        Called when a /ws/session/{session_id} WebSocket connects.

        Transitions:
          READY → ATTACHED
          DETACHED_GRACE → ATTACHED (reconnect within grace window)
        """
        session = self.sessions.get(session_id)
        if session is None:
            return
        if session.state in (SessionState.READY, SessionState.DETACHED_GRACE):
            self._transition(session_id, SessionState.ATTACHED)

    def on_ws_disconnect(self, session_id: str) -> None:
        """
        Called when the last /ws/session/{session_id} WebSocket disconnects.

        Transitions depend on SESSION_RECONNECT_GRACE_SECONDS:
          grace=0 (default): ATTACHED → TERMINATING (strict tab-close semantics)
          grace>0:           ATTACHED → DETACHED_GRACE (await reconnect)

        ADR-13: default grace=0 per user Decision 2 (tab close = terminate).
        """
        session = self.sessions.get(session_id)
        if session is None:
            return
        if session.state != SessionState.ATTACHED:
            return

        grace = int(os.environ.get("SESSION_RECONNECT_GRACE_SECONDS", "0"))
        if grace == 0:
            self._transition(session_id, SessionState.TERMINATING)
        else:
            self._transition(session_id, SessionState.DETACHED_GRACE)

    async def on_heartbeat_timeout(self, session_id: str) -> None:
        """
        Called by the WebSocket handler when heartbeat pong is not received
        within WS_HEARTBEAT_TIMEOUT_SECONDS.

        ADR-10: heartbeat timeout is the authoritative teardown signal.
        beforeunload is best-effort only.
        """
        logger.info(
            '{"event": "session.ws_heartbeat_timeout", "session_id": "%s"}',
            session_id,
        )
        await self.terminate_session(session_id, reason="heartbeat_timeout")

    async def terminate_session(self, session_id: str, reason: str = "explicit") -> None:
        """
        Initiate session termination.

        Transitions the session to TERMINATING, logs the reason, then marks
        it TERMINATED.  Resource cleanup (Playwright, supervisorctl stop,
        nginx_map remove) is delegated to backend.session.lifecycle.terminate()
        in Phase 2+ when the full lifecycle module is wired.

        For Phase 1, this method manages the state machine only.
        """
        session = self.sessions.get(session_id)
        if session is None:
            return
        if session.state in (SessionState.TERMINATING, SessionState.TERMINATED):
            return  # already in teardown

        self._transition(session_id, SessionState.TERMINATING)
        logger.info(
            '{"event": "session.terminated", "session_id": "%s", "reason": "%s"}',
            session_id, reason,
        )
        self._transition(session_id, SessionState.TERMINATED)
        self.remove_session(session_id)

    # ------------------------------------------------------------------
    # Periodic tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """
        Single execution of the periodic health check.

        1. Terminate sessions past jwt_valid_until + REBIND_GRACE_SECONDS.
        2. Call allocator reconciliation to catch leaked display slots.
        """
        now = time.time()
        rebind_grace = int(os.environ.get("REBIND_GRACE_SECONDS", "60"))

        expired_ids = [
            sid
            for sid, s in list(self.sessions.items())
            if s.is_active() and now >= s.jwt_valid_until + rebind_grace
        ]

        for sid in expired_ids:
            logger.info(
                '{"event": "session.jwt_expired", "session_id": "%s"}', sid,
            )
            await self.terminate_session(sid, reason="jwt_expired")

        # Allocator leak reconciliation
        await self._reconcile_allocator_leaks()

    async def _reconcile_allocator_leaks(self) -> None:
        """
        Check each active session's display slot against supervisorctl status.

        Leaked slots (allocated in-use by session, but FATAL/STOPPED in
        supervisord) are logged as session.allocator_leak and their sessions
        are transitioned to TERMINATING.
        """
        try:
            from backend.session.allocator import get_allocator
            allocator = get_allocator()
            leaked = allocator.reconcile()
            for display_num in leaked:
                # Find the session(s) using this display
                leaked_sessions = [
                    sid for sid, s in self.sessions.items()
                    if s.display_num == display_num
                ]
                for sid in leaked_sessions:
                    session = self.sessions.get(sid)
                    logger.warning(
                        '{"event": "session.allocator_leak", "session_id": "%s", '
                        '"display_num": %d}',
                        sid, display_num,
                    )
                    if session:
                        session.state = SessionState.TERMINATING
                    await self.terminate_session(sid, reason="allocator_leak")
        except Exception as exc:
            logger.error("_reconcile_allocator_leaks failed: %s", exc)

    async def start_tick_loop(self) -> None:
        """
        Start the background tick task.  Called from FastAPI lifespan startup.
        """
        interval = int(os.environ.get("SESSION_TICK_INTERVAL_SECONDS", "30"))

        async def _loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._tick()
                except Exception as exc:
                    logger.error("SessionManager tick error: %s", exc)

        self._tick_task = asyncio.create_task(_loop())
        logger.info("SessionManager tick loop started (interval=%ds)", interval)

    async def drain_all(self) -> None:
        """
        Terminate all active sessions.  Called from FastAPI lifespan shutdown.

        Each session receives reason="container_drain".  The frontend
        /ws/session/{id} receives a session_terminated event before close.
        """
        if self._tick_task:
            self._tick_task.cancel()

        active_ids = list(self.sessions.keys())
        logger.info(
            '{"event": "session.drain_all_start", "count": %d}',
            len(active_ids),
        )
        for sid in active_ids:
            try:
                await self.terminate_session(sid, reason="container_drain")
            except Exception as exc:
                logger.error("drain_all: error terminating %s: %s", sid, exc)

        logger.info('{"event": "session.drain_all_complete"}')


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager_instance: Optional[SessionManager] = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """
    Return the module-level SessionManager singleton.

    Thread-safe initialisation via a threading.Lock.  After the first call,
    subsequent calls return the already-initialised instance without locking.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SessionManager()
    return _manager_instance
