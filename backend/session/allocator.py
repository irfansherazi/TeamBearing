"""
vQA — Display Allocator
========================
Module: backend/session/allocator.py

Manages the pool of Xvfb display slots (:1..:N) and their associated
websockify ports (6081..6080+N).  Allocation is lazy: each slot is started
on-demand via ``supervisorctl start xvfb_N x11vnc_N websockify_N`` and
released via ``supervisorctl stop xvfb_N x11vnc_N websockify_N``.

The container's supervisord.conf (template rendered by docker/entrypoint.sh)
pre-declares slots 1..MAX_CONCURRENT_SESSIONS with ``autostart=false``, so
supervisorctl can start/stop them without a config reload.

Architecture Notes (ADR-2 — lazy allocation):
- Pre-booting all N triplets wastes ~50-70 MB/slot at baseline.
- Lazy start means 0 MB display overhead until a session is created.
- supervisorctl is invoked as a subprocess (stdout capture, return code check).

Thread/coroutine safety:
- DisplayAllocator is used from the single uvicorn worker (--workers 1).
- A threading.Lock guards acquire/release so the SessionManager's async
  code can call from within an asyncio lock guard without reentrance issues.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: Base noVNC / websockify port.  Display :1 → port 6081, :2 → 6082, etc.
_VNC_PORT_BASE = 6080


@dataclass
class CapacityReachedResult:
    """
    Returned by DisplayAllocator.acquire() when all slots are in use.

    Fields
    ------
    active_sessions  Number of sessions currently using display slots.
    retry_after_s    Hint to the caller: retry after this many seconds.
    """

    active_sessions: int
    retry_after_s: int = 15


class DisplayAllocator:
    """
    Lazy, capacity-bounded pool of Xvfb display slots.

    A slot is represented by its display number N (integer >= 1).
    The corresponding websockify port is 6080 + N.

    Usage::

        alloc = DisplayAllocator(max_sessions=4)
        result = alloc.acquire()
        if isinstance(result, CapacityReachedResult):
            # capacity hit — return 409 to the client
            ...
        else:
            display_num = result["display_num"]
            vnc_port = result["vnc_port"]
            # use the slot ...
            alloc.release(display_num)

    The allocator is a singleton shared by the SessionManager.  Obtain it
    via ``get_allocator()`` rather than constructing directly.
    """

    def __init__(self, max_sessions: int = 4) -> None:
        self._max = max_sessions
        self._lock = threading.Lock()
        #: Display numbers available for allocation.
        self.free_pool: set[int] = set(range(1, max_sessions + 1))
        #: Display numbers currently allocated to a session.
        self.in_use: set[int] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> dict | CapacityReachedResult:
        """
        Allocate the next free display slot.

        Returns
        -------
        dict
            ``{"display_num": N, "vnc_port": 6080+N}`` on success.
        CapacityReachedResult
            When all slots are in use.
        None
            When supervisorctl start fails (slot not allocated).
        """
        with self._lock:
            if not self.free_pool:
                logger.warning(
                    "DisplayAllocator: capacity reached — %d/%d slots in use",
                    len(self.in_use), self._max,
                )
                return CapacityReachedResult(active_sessions=len(self.in_use))

            display_num = min(self.free_pool)  # deterministic: always lowest free slot

        # Start the supervisord triplet OUTSIDE the lock to avoid blocking
        # other coroutines during the subprocess call.
        ok = self._supervisorctl_start(display_num)
        if not ok:
            logger.error(
                "DisplayAllocator: supervisorctl start failed for display :%d — slot NOT allocated",
                display_num,
            )
            return None  # caller must handle this as an error

        with self._lock:
            # Re-check capacity in case another thread raced us
            if display_num not in self.free_pool:
                # Someone else grabbed it while we were starting — release and try again
                # (this is a very rare race; for simplicity, return capacity error)
                logger.warning(
                    "DisplayAllocator: display :%d was taken by concurrent acquire; returning capacity error",
                    display_num,
                )
                # Stop the processes we just started
                self._supervisorctl_stop(display_num)
                return CapacityReachedResult(active_sessions=len(self.in_use))

            self.free_pool.discard(display_num)
            self.in_use.add(display_num)

        vnc_port = _VNC_PORT_BASE + display_num
        logger.info(
            "DisplayAllocator: allocated display :%d (websockify port %d)",
            display_num, vnc_port,
        )
        return {"display_num": display_num, "vnc_port": vnc_port}

    def release(self, display_num: int) -> None:
        """
        Release a display slot back to the free pool.

        Calls ``supervisorctl stop xvfb_N x11vnc_N websockify_N``.
        The slot is returned to the pool regardless of whether the stop
        command succeeds (a leaked process is less harmful than a stuck pool).
        """
        ok = self._supervisorctl_stop(display_num)
        if not ok:
            logger.warning(
                "DisplayAllocator: supervisorctl stop for display :%d returned error — "
                "slot returned to pool anyway (possible orphaned process)",
                display_num,
            )

        with self._lock:
            self.in_use.discard(display_num)
            self.free_pool.add(display_num)

        logger.info("DisplayAllocator: released display :%d", display_num)

    def reconcile(self) -> list[int]:
        """
        Cross-check supervisorctl status against in_use set.

        Returns a list of display_nums where the slot is believed in-use by
        the allocator but supervisorctl reports a non-RUNNING state (FATAL,
        STOPPED, EXITED, etc.).  These are "leaked" slots.

        Called by the SessionManager periodic tick (_tick) to detect and
        clean up allocator leaks.
        """
        leaked: list[int] = []
        with self._lock:
            in_use_snapshot = set(self.in_use)

        for display_num in in_use_snapshot:
            status = self._supervisorctl_status(display_num)
            if status != "RUNNING":
                logger.warning(
                    "session.allocator_leak: display :%d believed in-use but supervisorctl reports %s",
                    display_num, status,
                )
                leaked.append(display_num)

        return leaked

    # ------------------------------------------------------------------
    # Internal helpers (overrideable in tests via patch.object)
    # ------------------------------------------------------------------

    def _supervisorctl_start(self, display_num: int) -> bool:
        """
        Call ``supervisorctl start xvfb_N x11vnc_N websockify_N``.

        Returns True on success (all three programs started), False otherwise.
        """
        programs = [
            f"xvfb_{display_num}",
            f"x11vnc_{display_num}",
            f"websockify_{display_num}",
        ]
        try:
            result = subprocess.run(
                ["supervisorctl", "start"] + programs,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(
                    "supervisorctl start %s failed (rc=%d): %s",
                    programs, result.returncode, result.stderr,
                )
                return False
            return True
        except Exception as exc:
            logger.error("supervisorctl start %s raised: %s", programs, exc)
            return False

    def _supervisorctl_stop(self, display_num: int) -> bool:
        """
        Call ``supervisorctl stop xvfb_N x11vnc_N websockify_N``.

        Returns True on success, False otherwise.
        """
        programs = [
            f"xvfb_{display_num}",
            f"x11vnc_{display_num}",
            f"websockify_{display_num}",
        ]
        try:
            result = subprocess.run(
                ["supervisorctl", "stop"] + programs,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "supervisorctl stop %s returned rc=%d: %s",
                    programs, result.returncode, result.stderr,
                )
                return False
            return True
        except Exception as exc:
            logger.error("supervisorctl stop %s raised: %s", programs, exc)
            return False

    def _supervisorctl_status(self, display_num: int) -> str:
        """
        Query ``supervisorctl status xvfb_N`` and return the state string.

        Returns one of: RUNNING, STOPPED, FATAL, EXITED, STARTING, UNKNOWN.
        Returns "UNKNOWN" if the command fails or output cannot be parsed.
        """
        program = f"xvfb_{display_num}"
        try:
            result = subprocess.run(
                ["supervisorctl", "status", program],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout.strip()
            # supervisorctl status output: "xvfb_1   RUNNING   pid 1234, uptime 0:01:00"
            parts = output.split()
            if len(parts) >= 2:
                return parts[1].upper()
            return "UNKNOWN"
        except Exception as exc:
            logger.error("supervisorctl status %s raised: %s", program, exc)
            return "UNKNOWN"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_allocator_instance: DisplayAllocator | None = None
_allocator_lock = threading.Lock()


def get_allocator() -> DisplayAllocator:
    """
    Return the module-level DisplayAllocator singleton.

    Reads MAX_CONCURRENT_SESSIONS from the environment on first call.
    """
    global _allocator_instance
    if _allocator_instance is None:
        with _allocator_lock:
            if _allocator_instance is None:
                import os
                max_sessions = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "4"))
                _allocator_instance = DisplayAllocator(max_sessions=max_sessions)
    return _allocator_instance
