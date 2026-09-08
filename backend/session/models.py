"""
vQA — Session Models
=====================
Module: backend/session/models.py

Defines the Session dataclass and SessionState enum for the per-user
session isolation subsystem (per-user-session-isolation feature, Phase 1).

Session State Machine
---------------------

    REQUESTED ──► PROVISIONING ──► READY ──► ATTACHED
                                              │
                                              ├──(grace>0)──► DETACHED_GRACE ──► TERMINATING ──► TERMINATED
                                              │                                                   │
                                              └──(grace=0)──────────────────────► TERMINATING ──► TERMINATED
                                                                                   │
                                                                              FAILED (on error)

State descriptions:
  REQUESTED        — bootstrap initiated, DisplayAllocator.acquire() not yet called.
  PROVISIONING     — supervisorctl start in progress for the display/VNC triplet.
  READY            — display+VNC triplet up; session cookie issued; no WS yet attached.
  ATTACHED         — at least one /ws/session/{id} WebSocket is connected.
  DETACHED_GRACE   — all WS disconnected; waiting SESSION_RECONNECT_GRACE_SECONDS for reconnect.
                     Only entered when SESSION_RECONNECT_GRACE_SECONDS > 0.
  TERMINATING      — lifecycle.terminate() called; async teardown in progress.
  TERMINATED       — teardown complete; session is done.
  FAILED           — unrecoverable error (e.g., supervisorctl FATAL on acquire).

Architecture Notes (ADR-1, ADR-2)
----------------------------------
Each Session owns exactly ONE Xvfb display (:N), one x11vnc (rfbport 5900+N-1?),
and one websockify (port 6080+N).  The per-session noVNC URL follows the pattern:

    /vnc/<session_id>/vnc.html?path=websockify/<session_id>

The nginx sidecar routes this path prefix to the correct per-session websockify port
by reading /var/run/vqa/sessions.map (written by nginx_map.py).

The JWT expiry contract (ADR-12):
  jwt_valid_until = new_jwt.exp (updated on every successful rebind).
  Periodic tick terminates sessions where now >= jwt_valid_until + REBIND_GRACE_SECONDS.
  Worst-case linger ~ REBIND_GRACE_SECONDS + SESSION_TICK_INTERVAL_SECONDS = 90s.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionState(str, Enum):
    """
    States in the per-user Session lifecycle state machine.

    Using str as the mixin base makes the enum values JSON-serialisable
    and comparable to plain strings (useful in API response payloads and logs).
    """

    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    ATTACHED = "ATTACHED"
    DETACHED_GRACE = "DETACHED_GRACE"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


@dataclass
class Session:
    """
    A single authenticated user session.

    Owns one virtual display slot (display_num) and the corresponding
    websockify VNC port (vnc_port = 6080 + display_num).

    Lifecycle managed by SessionManager; resource allocation/teardown
    delegated to DisplayAllocator and lifecycle.terminate().

    Fields
    ------
    session_id       Opaque UUID string; issued as the vqa_session cookie value.
    user_email       JWT-authenticated email; stamped on all KB writes (recorded_by).
    user_id          JWT vc_id (int, cast to str for uniform handling).
    display_num      Xvfb display number (:1, :2, …, :N).
    vnc_port         websockify port = 6080 + display_num.
    jwt_valid_until  Unix timestamp of the most recent JWT exp. Updated on rebind.
    state            Current state in the lifecycle state machine.
    active_run_ids   Run IDs currently executing under this session.
    created_at       Unix timestamp of session creation.
    novnc_url        Pre-computed noVNC URL for this session.
    """

    session_id: str
    user_email: str
    user_id: str
    display_num: int
    vnc_port: int
    jwt_valid_until: float

    state: SessionState = field(default=SessionState.REQUESTED)
    active_run_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def novnc_url(self) -> str:
        """
        Session-scoped noVNC URL.

        Format: /vnc/<session_id>/vnc.html?path=websockify/<session_id>

        The nginx sidecar routes /vnc/<session_id>/* to the noVNC static
        files and /websockify/<session_id> to websockify port vnc_port.
        """
        sid = self.session_id
        return f"/vnc/{sid}/vnc.html?path=websockify/{sid}"

    def is_active(self) -> bool:
        """
        Return True if the session is in a non-terminal state that can serve traffic.
        """
        return self.state in (
            SessionState.REQUESTED,
            SessionState.PROVISIONING,
            SessionState.READY,
            SessionState.ATTACHED,
            SessionState.DETACHED_GRACE,
        )
