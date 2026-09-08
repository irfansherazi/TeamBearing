"""
vQA — Session Subsystem
========================
Package: backend/session/

Per-user session isolation subsystem (per-user-session-isolation, Phase 1+).

Public API
----------
  SessionManager    — in-memory registry + state-machine engine
  get_session_manager() — singleton accessor
  Session           — Session dataclass
  SessionState      — State enum (REQUESTED → … → TERMINATED)
  DisplayAllocator  — lazy display pool (supervisorctl-backed)
  get_allocator()   — singleton accessor
  terminate()       — 7-step teardown sequence (lifecycle.py)

Usage
-----
    from backend.session import SessionManager, get_session_manager, Session, SessionState

    mgr = get_session_manager()
    session = mgr.get_session(session_id)
"""

from backend.session.models import Session, SessionState
from backend.session.manager import SessionManager, get_session_manager
from backend.session.allocator import DisplayAllocator, get_allocator, CapacityReachedResult

__all__ = [
    "Session",
    "SessionState",
    "SessionManager",
    "get_session_manager",
    "DisplayAllocator",
    "get_allocator",
    "CapacityReachedResult",
]
