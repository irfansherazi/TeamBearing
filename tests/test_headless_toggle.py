"""
vQA — Unit Tests: Headless Toggle (TASK-031 / AC-ENTRY-1, AC-HAPPY-1)
=======================================================================
Module: tests/test_headless_toggle.py

Tests the VQA_HEADLESS environment variable gate in:
  - backend/browser/context.py::_get_slow_mo()
  - backend/browser/context.py::BrowserManager.start() headless decision

Coverage:
  - VQA_HEADLESS=0 → is_headless=False, slowMo=10ms
  - VQA_HEADLESS=1 → is_headless=True, slowMo=0ms
  - VQA_HEADLESS absent → is_headless=False (headed by default)
  - VQA_HEADLESS=0 → chromium.launch called with headless=False
  - VQA_SLOW_MO override still respected when set

Author: vQA Build Agent (TASK-031 Phase 1)
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_playwright_cleanup():
    """Ensure backend.browser.context.async_playwright is restored after tests."""
    import backend.browser.context as ctx_mod

    original = ctx_mod.async_playwright
    yield
    ctx_mod.async_playwright = original


# ---------------------------------------------------------------------------
# _get_slow_mo tests
# ---------------------------------------------------------------------------


class TestGetSlowMo:
    """Unit tests for the _get_slow_mo() helper function."""

    def test_headless_returns_zero_slowmo(self):
        """When is_headless=True, _get_slow_mo returns 0."""
        # Ensure VQA_SLOW_MO override is not set
        with patch.dict(os.environ, {}, clear=False):
            if "VQA_SLOW_MO" in os.environ:
                del os.environ["VQA_SLOW_MO"]
            # Re-import to ensure fresh module state without the override
            import importlib

            import backend.browser.context as ctx_mod

            importlib.reload(ctx_mod)
            result = ctx_mod._get_slow_mo(is_headless=True)
            assert result == 0, f"Expected 0ms for headless, got {result}"

    def test_headed_returns_10ms_slowmo(self):
        """When is_headless=False, _get_slow_mo returns 10."""
        with patch.dict(os.environ, {}, clear=False):
            if "VQA_SLOW_MO" in os.environ:
                del os.environ["VQA_SLOW_MO"]
            import importlib

            import backend.browser.context as ctx_mod

            importlib.reload(ctx_mod)
            result = ctx_mod._get_slow_mo(is_headless=False)
            assert result == 10, f"Expected 10ms for headed, got {result}"

    def test_vqa_slow_mo_override_respected(self):
        """VQA_SLOW_MO env var overrides the default slowMo for both modes."""
        with patch.dict(os.environ, {"VQA_SLOW_MO": "250"}):
            import importlib

            import backend.browser.context as ctx_mod

            importlib.reload(ctx_mod)
            assert ctx_mod._get_slow_mo(is_headless=True) == 250
            assert ctx_mod._get_slow_mo(is_headless=False) == 250

    def test_vqa_slow_mo_zero_override(self):
        """VQA_SLOW_MO=0 forces zero slowMo even in headed mode."""
        with patch.dict(os.environ, {"VQA_SLOW_MO": "0"}):
            import importlib

            import backend.browser.context as ctx_mod

            importlib.reload(ctx_mod)
            assert ctx_mod._get_slow_mo(is_headless=False) == 0


# ---------------------------------------------------------------------------
# is_headless decision logic tests (via BrowserManager.start)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.usefixtures("mock_playwright_cleanup")
class TestHeadlessDecision:
    """
    Tests for the is_headless decision in BrowserManager.start().

    We mock chromium.launch so no real browser is spawned, then assert
    that the headless= kwarg matches the expected value based on VQA_HEADLESS.
    """

    async def test_vqa_headless_0_launches_headed(self):
        """
        VQA_HEADLESS=0 → chromium.launch(headless=False).
        Verifies AC-HAPPY-1: headed mode launches a visible browser.
        """
        with patch.dict(os.environ, {"VQA_HEADLESS": "0"}):
            # Remove any settings.vqa_mode that might override
            from backend.config import get_settings

            get_settings.cache_clear()

            mock_page = MagicMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            manager = _make_manager_with_mock_playwright(mock_playwright)
            await manager.start()

            # Verify chromium.launch was called with headless=False
            call_kwargs = mock_playwright.chromium.launch.call_args
            assert call_kwargs is not None, "chromium.launch was never called"
            _, kwargs = call_kwargs
            assert kwargs.get("headless") is False, (
                f"Expected headless=False when VQA_HEADLESS=0, got: {kwargs.get('headless')}"
            )

    async def test_vqa_headless_1_launches_headless(self):
        """VQA_HEADLESS=1 → chromium.launch(headless=True)."""
        with patch.dict(os.environ, {"VQA_HEADLESS": "1"}):
            from backend.config import get_settings

            get_settings.cache_clear()

            mock_page = MagicMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            manager = _make_manager_with_mock_playwright(mock_playwright)
            await manager.start()

            call_kwargs = mock_playwright.chromium.launch.call_args
            assert call_kwargs is not None
            _, kwargs = call_kwargs
            assert kwargs.get("headless") is True, (
                f"Expected headless=True when VQA_HEADLESS=1, got: {kwargs.get('headless')}"
            )

    async def test_vqa_headless_absent_defaults_headed(self):
        """
        VQA_HEADLESS absent (not set) → headed mode (headless=False).
        The default is headed for local QA/product observation.
        """
        env_without_headless = {k: v for k, v in os.environ.items() if k != "VQA_HEADLESS"}
        with patch.dict(os.environ, env_without_headless, clear=True):
            from backend.config import get_settings

            get_settings.cache_clear()

            mock_page = MagicMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            manager = _make_manager_with_mock_playwright(mock_playwright)
            await manager.start()

            call_kwargs = mock_playwright.chromium.launch.call_args
            assert call_kwargs is not None
            _, kwargs = call_kwargs
            assert kwargs.get("headless") is False, (
                f"Expected headless=False when VQA_HEADLESS is absent, got: {kwargs.get('headless')}"
            )

    async def test_headed_mode_log_message(self, caplog):
        """
        AC-HAPPY-1 verification: log line contains 'headed' mode label
        (NOT 'headless') when VQA_HEADLESS=0.

        Note: exact slowMo ms value depends on VQA_SLOW_MO env var at module
        import time, so we only assert the 'headed' (not headless) label.
        """
        import logging

        with patch.dict(os.environ, {"VQA_HEADLESS": "0"}):
            from backend.config import get_settings

            get_settings.cache_clear()

            mock_page = MagicMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            with caplog.at_level(logging.INFO, logger="backend.browser.context"):
                manager = _make_manager_with_mock_playwright(mock_playwright)
                await manager.start()

            # Must log "headed" mode — exact ms depends on VQA_SLOW_MO at import
            log_messages = " ".join(caplog.messages)
            assert "headed" in log_messages, f"Expected 'headed' in log (VQA_HEADLESS=0). Got: {log_messages[:300]}"
            # Must NOT log 'headless'
            assert "Launching Chromium in headless" not in log_messages, (
                f"Did not expect headless mode log when VQA_HEADLESS=0. Got: {log_messages[:300]}"
            )

    async def test_headless_mode_log_message(self, caplog):
        """
        Log line contains 'headless mode' when VQA_HEADLESS=1.
        """
        import logging

        with patch.dict(os.environ, {"VQA_HEADLESS": "1"}):
            from backend.config import get_settings

            get_settings.cache_clear()

            mock_page = MagicMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            with caplog.at_level(logging.INFO, logger="backend.browser.context"):
                manager = _make_manager_with_mock_playwright(mock_playwright)
                await manager.start()

            log_messages = " ".join(caplog.messages)
            assert "headless" in log_messages.lower(), f"Expected 'headless' in log. Got: {log_messages[:300]}"


# ---------------------------------------------------------------------------
# Config settings tests (AC-ENTRY-1 supplemental)
# ---------------------------------------------------------------------------


class TestConfigSettings:
    """Tests for the new settings fields added in Phase 1."""

    def test_accepted_tests_dir_default(self):
        """Settings.accepted_tests_dir defaults to 'memory/accepted_tests'."""
        from backend.config import get_settings

        get_settings.cache_clear()
        with patch.dict(os.environ, {}, clear=False):
            if "ACCEPTED_TESTS_DIR" in os.environ:
                del os.environ["ACCEPTED_TESTS_DIR"]
            get_settings.cache_clear()
            s = get_settings()
            assert s.accepted_tests_dir == "memory/accepted_tests", (
                f"Expected default 'memory/accepted_tests', got: {s.accepted_tests_dir}"
            )

    def test_enable_smart_replay_default_true(self):
        """Settings.enable_smart_replay defaults to True."""
        from backend.config import get_settings

        get_settings.cache_clear()
        with patch.dict(os.environ, {}, clear=False):
            if "ENABLE_SMART_REPLAY" in os.environ:
                del os.environ["ENABLE_SMART_REPLAY"]
            get_settings.cache_clear()
            s = get_settings()
            assert s.enable_smart_replay is True, f"Expected enable_smart_replay=True, got: {s.enable_smart_replay}"

    def test_enable_smart_replay_disabled_via_env(self):
        """ENABLE_SMART_REPLAY=false disables smart replay."""
        from backend.config import get_settings

        with patch.dict(os.environ, {"ENABLE_SMART_REPLAY": "false"}):
            get_settings.cache_clear()
            s = get_settings()
            assert s.enable_smart_replay is False

    def test_accepted_tests_dir_override_via_env(self):
        """ACCEPTED_TESTS_DIR env var overrides the default."""
        from backend.config import get_settings

        with patch.dict(os.environ, {"ACCEPTED_TESTS_DIR": "/custom/path"}):
            get_settings.cache_clear()
            s = get_settings()
            assert s.accepted_tests_dir == "/custom/path"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_manager_with_mock_playwright(mock_playwright):
    """
    Create a BrowserManager instance patched to use the provided mock playwright.
    """
    import backend.browser.context as ctx_mod
    from backend.browser.context import BrowserManager

    manager = BrowserManager(run_id="test-run-headless-001")

    class _FakePWCtx:
        async def start(self):
            return mock_playwright

    ctx_mod.async_playwright = lambda: _FakePWCtx()

    return manager
