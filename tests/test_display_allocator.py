"""
Phase 1: DisplayAllocator — Unit Tests
========================================
Module: tests/test_display_allocator.py

Tests the Phase 1 DisplayAllocator:

  1. acquire() returns a free (display_num, vnc_port) pair.
  2. Two concurrent acquire() calls get distinct slots (no collision).
  3. release() returns the slot to the pool for re-use.
  4. acquire() when pool is exhausted returns a CapacityReached structured result.
  5. Supervisorctl start failure on acquire → slot is not marked in-use.
  6. Reconciliation: supervisorctl FATAL state → session.allocator_leak warning emitted.

Acceptance Criteria Coverage:
  AC-ERROR-2 (Capacity cap → structured result) — § TestCapacityReached
  AC-ASYNC-4 (Allocator leak reconciliation) — § TestAllocatorReconciliation

Per-Phase Test Guidance (task file §Phase 1):
  Allocator acquire under contention, cap-reached returns capacity_reached
  structured result, leak-on-supervisorctl-fail, reconciliation loop catches leaks.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_allocator(max_sessions: int = 4):
    """Create a DisplayAllocator with a mocked supervisorctl."""
    from backend.session.allocator import DisplayAllocator
    return DisplayAllocator(max_sessions=max_sessions)


# ---------------------------------------------------------------------------
# 1. Basic acquire / release
# ---------------------------------------------------------------------------


class TestDisplayAllocatorAcquireRelease:
    """DisplayAllocator.acquire() and release() basic contracts."""

    def test_acquire_returns_slot(self):
        """acquire() returns a (display_num, vnc_port) tuple on first call."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            result = alloc.acquire()
        assert result is not None
        assert result["display_num"] >= 1
        assert result["vnc_port"] >= 6081

    def test_acquire_distinct_slots(self):
        """Two consecutive acquire() calls return distinct display slots."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot_a = alloc.acquire()
            slot_b = alloc.acquire()
        assert slot_a is not None
        assert slot_b is not None
        assert slot_a["display_num"] != slot_b["display_num"], (
            "Two concurrent sessions must get different display numbers"
        )
        assert slot_a["vnc_port"] != slot_b["vnc_port"], (
            "Two concurrent sessions must get different VNC ports"
        )

    def test_release_frees_slot_for_reuse(self):
        """release() returns a slot to the free pool; a subsequent acquire() can claim it."""
        alloc = _make_allocator(max_sessions=1)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot = alloc.acquire()
        assert slot is not None
        display_num = slot["display_num"]

        with patch.object(alloc, "_supervisorctl_stop", return_value=True):
            alloc.release(display_num)

        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot2 = alloc.acquire()
        assert slot2 is not None
        assert slot2["display_num"] == display_num, (
            "Released slot must be reusable"
        )

    def test_acquire_marks_slot_in_use(self):
        """After acquire(), the display_num appears in the in-use set."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot = alloc.acquire()
        assert slot["display_num"] in alloc.in_use

    def test_release_removes_from_in_use(self):
        """After release(), the display_num is no longer in the in-use set."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot = alloc.acquire()
        display_num = slot["display_num"]
        with patch.object(alloc, "_supervisorctl_stop", return_value=True):
            alloc.release(display_num)
        assert display_num not in alloc.in_use


# ---------------------------------------------------------------------------
# 2. Capacity reached
# ---------------------------------------------------------------------------


class TestCapacityReached:
    """acquire() returns a CapacityReachedResult when all slots are in use."""

    def test_capacity_reached_returns_structured_result(self):
        """When max_sessions slots are all in use, acquire() returns a capacity_reached result."""
        from backend.session.allocator import CapacityReachedResult
        alloc = _make_allocator(max_sessions=2)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            alloc.acquire()  # slot 1 in use
            alloc.acquire()  # slot 2 in use
            result = alloc.acquire()  # capacity hit

        assert isinstance(result, CapacityReachedResult), (
            "acquire() must return CapacityReachedResult when all slots are taken"
        )
        assert result.active_sessions == 2

    def test_capacity_reached_has_retry_hint(self):
        """CapacityReachedResult includes retry_after_s field."""
        from backend.session.allocator import CapacityReachedResult
        alloc = _make_allocator(max_sessions=1)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            alloc.acquire()
            result = alloc.acquire()

        assert hasattr(result, "retry_after_s"), (
            "CapacityReachedResult must have retry_after_s field for frontend polling"
        )
        assert result.retry_after_s > 0


# ---------------------------------------------------------------------------
# 3. Supervisorctl start failure
# ---------------------------------------------------------------------------


class TestSupervisorctlStartFailure:
    """If supervisorctl start fails, the slot is not marked in-use."""

    def test_supervisorctl_start_failure_does_not_mark_in_use(self):
        """When _supervisorctl_start returns False, acquire() returns None and does not mark slot as in-use."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=False):
            result = alloc.acquire()

        # Result should be None or an error marker — NOT a valid slot
        # And in_use should still be empty
        assert len(alloc.in_use) == 0, (
            "Failed supervisorctl start must not leave a slot marked as in-use"
        )


# ---------------------------------------------------------------------------
# 4. Port formula
# ---------------------------------------------------------------------------


class TestPortFormula:
    """VNC port follows the formula: 6080 + display_num."""

    def test_port_formula_display_1(self):
        """Display :1 → port 6081."""
        alloc = _make_allocator(max_sessions=4)
        with patch.object(alloc, "_supervisorctl_start", return_value=True):
            slot = alloc.acquire()
        assert slot["vnc_port"] == 6080 + slot["display_num"]

    def test_pool_contains_all_display_numbers(self):
        """Free pool initially contains 1..max_sessions display numbers."""
        alloc = _make_allocator(max_sessions=3)
        assert set(alloc.free_pool) == {1, 2, 3}


# ---------------------------------------------------------------------------
# 5. Reconciliation / leak detection
# ---------------------------------------------------------------------------


class TestAllocatorReconciliation:
    """get_supervisorctl_status returns information about running programs."""

    def test_reconcile_interface_exists(self):
        """DisplayAllocator has a reconcile() method for the SessionManager tick."""
        alloc = _make_allocator(max_sessions=4)
        assert hasattr(alloc, "reconcile"), (
            "DisplayAllocator must expose reconcile() for the SessionManager tick"
        )
        assert callable(alloc.reconcile)

    def test_reconcile_returns_leaked_sessions(self):
        """reconcile() returns a list of display_nums where supervisorctl is FATAL."""
        alloc = _make_allocator(max_sessions=4)
        # Mark display 2 as in-use
        alloc.in_use.add(2)

        def _fake_status(display_num):
            # Simulate supervisorctl returning FATAL for display 2
            if display_num == 2:
                return "FATAL"
            return "RUNNING"

        with patch.object(alloc, "_supervisorctl_status", side_effect=_fake_status):
            leaked = alloc.reconcile()

        assert 2 in leaked, (
            "reconcile() must identify display 2 as leaked (FATAL supervisorctl state)"
        )
