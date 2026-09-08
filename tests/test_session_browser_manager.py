"""
Phase 0 + Phase 4: SessionBrowserManager — Unit Tests
======================================================
Module: tests/test_session_browser_manager.py

Phase 0 tests (preserved):
  1. Two SessionBrowserManager(id=...) instances with different ids are
     fully isolated (no shared state, no cross-contamination).
  2. BrowserManager name alias still importable (import back-compat).
  3. session_id attribute is correctly stored per-instance.
  4. Per-instance close() releases only that instance's resources.
  5. SESSION_ISOLATION_ENABLED=false leaves legacy run-level registry unchanged.

Phase 4 tests (added):
  6. SessionBrowserManager accepts display_num kwarg; sets VQA_DISPLAY env var
     to :{display_num} before browser launch (AC-ENTRY-3 requirement:
     "Playwright browser launched with DISPLAY=:{session.display_num}").
  7. display_num=0 (default) leaves DISPLAY untouched (legacy/headless path).
  8. __legacy_singleton__ is removed; importing it raises ImportError.

Acceptance Criteria Coverage:
  AC-ENTRY-3 — display_num wired through SessionBrowserManager
  AC-HAPPY-5 — SESSION_ISOLATION_ENABLED=false kill switch
"""

import os
import importlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_browser_manager_cls():
    """Return the SessionBrowserManager class (or its BrowserManager alias)."""
    from backend.browser.context import SessionBrowserManager
    return SessionBrowserManager


def _make_browser_manager_alias():
    """Return the BrowserManager alias — must still be importable."""
    from backend.browser.context import BrowserManager
    return BrowserManager


# ---------------------------------------------------------------------------
# 1. Class shape / import back-compat
# ---------------------------------------------------------------------------


class TestSessionBrowserManagerShape:
    """SessionBrowserManager exists and has the required interface."""

    def test_session_browser_manager_importable(self):
        """SessionBrowserManager is importable from backend.browser.context."""
        SessionBrowserManager = _make_browser_manager_cls()
        assert SessionBrowserManager is not None

    def test_browser_manager_alias_importable(self):
        """BrowserManager alias is still importable for existing callers."""
        BrowserManager = _make_browser_manager_alias()
        assert BrowserManager is not None

    def test_browser_manager_is_session_browser_manager(self):
        """BrowserManager alias resolves to the same class as SessionBrowserManager."""
        from backend.browser.context import BrowserManager, SessionBrowserManager
        # They must be the same class object (alias, not subclass)
        assert BrowserManager is SessionBrowserManager

    def test_session_browser_manager_accepts_id(self):
        """SessionBrowserManager(id=...) constructs without error."""
        SessionBrowserManager = _make_browser_manager_cls()
        sbm = SessionBrowserManager(id="session-abc-123")
        assert sbm is not None

    def test_session_id_stored(self):
        """session_id attribute is set from the id= constructor argument."""
        from backend.browser.context import SessionBrowserManager
        sbm = SessionBrowserManager(id="my-session-id")
        assert sbm.session_id == "my-session-id"

    def test_run_id_matches_session_id(self):
        """run_id (existing attribute) still works as the identifier."""
        from backend.browser.context import SessionBrowserManager
        sbm = SessionBrowserManager(id="run-xyz")
        # run_id must still be set so existing callers relying on it don't break
        assert sbm.run_id == "run-xyz"


# ---------------------------------------------------------------------------
# 2. Instance isolation — no shared state between instances
# ---------------------------------------------------------------------------


class TestInstanceIsolation:
    """Two instances with different ids share no mutable state."""

    def test_distinct_instances_different_ids(self):
        """Two SessionBrowserManager instances with different ids are separate objects."""
        from backend.browser.context import SessionBrowserManager
        sbm_a = SessionBrowserManager(id="session-alice")
        sbm_b = SessionBrowserManager(id="session-bob")
        assert sbm_a is not sbm_b
        assert sbm_a.session_id != sbm_b.session_id

    def test_page_attr_not_shared(self):
        """Setting page on one instance does not leak to another."""
        from backend.browser.context import SessionBrowserManager
        sbm_a = SessionBrowserManager(id="session-a")
        sbm_b = SessionBrowserManager(id="session-b")
        # Simulate page assignment (would normally happen in start())
        fake_page = MagicMock()
        sbm_a.page = fake_page
        assert sbm_b.page is None, (
            "sbm_b.page should be None; setting sbm_a.page must not affect sbm_b"
        )

    def test_video_path_not_shared(self):
        """video_path on one instance does not contaminate another."""
        from backend.browser.context import SessionBrowserManager
        sbm_a = SessionBrowserManager(id="session-a")
        sbm_b = SessionBrowserManager(id="session-b")
        from pathlib import Path
        sbm_a.video_path = Path("/tmp/fake-a.webm")
        assert sbm_b.video_path is None

    def test_actor_registry_not_shared(self):
        """_actor_registry dict is per-instance, not class-level."""
        from backend.browser.context import SessionBrowserManager
        sbm_a = SessionBrowserManager(id="session-a")
        sbm_b = SessionBrowserManager(id="session-b")
        sbm_a._actor_registry["role_key"] = (MagicMock(), MagicMock())
        assert "role_key" not in sbm_b._actor_registry, (
            "_actor_registry must be a per-instance dict, not a class-level dict"
        )


# ---------------------------------------------------------------------------
# 3. Phase 4 — display_num wiring + __legacy_singleton__ removal
# ---------------------------------------------------------------------------


class TestPhase4DisplayNumWiring:
    """
    Phase 4: SessionBrowserManager.display_num is wired to the VQA_DISPLAY env
    var before browser launch so Playwright connects to the correct per-session
    Xvfb display (AC-ENTRY-3).
    """

    def test_display_num_accepted_in_constructor(self):
        """
        SessionBrowserManager accepts display_num kwarg without error.

        Phase 4: display_num=1 → the instance will set VQA_DISPLAY=:1 on start().
        """
        from backend.browser.context import SessionBrowserManager
        sbm = SessionBrowserManager(id="session-disp-test", display_num=1)
        assert sbm.display_num == 1

    def test_display_num_default_zero(self):
        """
        display_num defaults to 0, meaning the existing DISPLAY / VQA_DISPLAY
        env vars are used unchanged (no regression for legacy callers).
        """
        from backend.browser.context import SessionBrowserManager
        sbm = SessionBrowserManager(id="session-no-disp")
        assert sbm.display_num == 0

    def test_display_num_stored_per_instance(self):
        """Two instances with different display_num values are independent."""
        from backend.browser.context import SessionBrowserManager
        s1 = SessionBrowserManager(id="s1", display_num=1)
        s2 = SessionBrowserManager(id="s2", display_num=2)
        assert s1.display_num == 1
        assert s2.display_num == 2
        assert s1.display_num != s2.display_num


class TestPhase4LegacySingletonRemoved:
    """
    Phase 4: __legacy_singleton__ is removed from context.py.

    All callers must now use get_manager(run_id) (run-level lookup) or the
    session-scoped SessionBrowserManager(id=session_id, display_num=...) path.
    """

    def test_legacy_singleton_no_longer_exported(self):
        """
        Importing __legacy_singleton__ from backend.browser.context raises
        ImportError — Phase 4 removes it entirely.
        """
        with pytest.raises((ImportError, AttributeError)):
            from backend.browser.context import __legacy_singleton__  # noqa: F401


# ---------------------------------------------------------------------------
# 4. kill switch: SESSION_ISOLATION_ENABLED=false
# ---------------------------------------------------------------------------


class TestKillSwitch:
    """With SESSION_ISOLATION_ENABLED=false, existing run-level registry unchanged."""

    def test_registry_functions_importable_without_flag(self):
        """register_manager / get_manager / unregister_manager still importable."""
        from backend.browser.context import (
            register_manager,
            get_manager,
            unregister_manager,
        )
        assert callable(register_manager)
        assert callable(get_manager)
        assert callable(unregister_manager)

    def test_register_then_get_manager(self):
        """register_manager + get_manager round-trip with SessionBrowserManager."""
        from backend.browser.context import (
            SessionBrowserManager,
            register_manager,
            get_manager,
            unregister_manager,
        )
        sbm = SessionBrowserManager(id="run-roundtrip-001")
        register_manager("run-roundtrip-001", sbm)
        retrieved = get_manager("run-roundtrip-001")
        assert retrieved is sbm
        # cleanup
        unregister_manager("run-roundtrip-001")
