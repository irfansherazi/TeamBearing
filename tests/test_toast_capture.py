"""
TASK-009: Toast Capture Infrastructure — Unit Tests
===================================================

Tests for toast observer injection and buffer management.
Verifies that MutationObserver is correctly injected and captures
PrimeNG toast messages into a FIFO buffer.

Run: .venv/bin/python -m pytest tests/test_toast_capture.py -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Configuration
# ═══════════════════════════════════════════════════════════════════════════


class TestToastCaptureConfig:
    """Verify toast capture configuration in Settings."""

    def test_enable_toast_buffer_flag_exists(self):
        """enable_toast_buffer should be defined in Settings."""
        from backend.config import Settings

        assert "enable_toast_buffer" in Settings.model_fields

    def test_enable_toast_buffer_default_true(self):
        """enable_toast_buffer should default to True."""
        from backend.config import Settings

        s = Settings()
        assert s.enable_toast_buffer is True


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Injection Logic
# ═══════════════════════════════════════════════════════════════════════════


class TestToastCaptureInjection:
    """Verify that the JS is injected into the browser context."""

    @pytest.mark.anyio
    async def test_toast_observer_constant_defined(self):
        """TOAST_OBSERVER_JS constant should be defined in context.py."""
        from backend.browser import context

        assert hasattr(context, "TOAST_OBSERVER_JS")
        assert "MutationObserver" in context.TOAST_OBSERVER_JS
        assert "__VQA_TOAST_BUFFER__" in context.TOAST_OBSERVER_JS

    @pytest.mark.anyio
    async def test_real_injection_on_start(self):
        """Verify window.__VQA_TOAST_BUFFER__ exists in a real browser session."""
        from backend.browser.context import BrowserManager

        # This test will fail if enable_toast_buffer is False or injection is missing
        async with BrowserManager(run_id="test-real-injection") as bm:
            await bm.page.goto("about:blank")
            buffer_exists = await bm.page.evaluate("() => window.__VQA_TOAST_BUFFER__ !== undefined")
            assert buffer_exists is True


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Buffer Logic (In-Browser)
# ═══════════════════════════════════════════════════════════════════════════


class TestToastCaptureLogic:
    """Verify the MutationObserver logic in the browser."""

    @pytest.mark.anyio
    async def test_toast_capture_flow(self):
        """Verify that adding a toast element updates the buffer."""
        from backend.browser.context import BrowserManager

        async with BrowserManager(run_id="test-capture-behavior") as bm:
            # 1. Ensure page is loaded
            await bm.page.goto("about:blank")

            # 2. Simulate a PrimeNG toast message
            # PrimeNG toasts have .p-toast-message and usually a severity class
            await bm.page.evaluate("""
                () => {
                    const message = document.createElement('div');
                    message.className = 'p-toast-message p-toast-message-success';

                    const content = document.createElement('div');
                    content.className = 'p-toast-message-content';

                    const summary = document.createElement('div');
                    summary.className = 'p-toast-summary';
                    summary.innerText = 'Success Summary';

                    const detail = document.createElement('div');
                    detail.className = 'p-toast-detail';
                    detail.innerText = 'Detailed message content';

                    content.appendChild(summary);
                    content.appendChild(detail);
                    message.appendChild(content);
                    document.body.appendChild(message);
                }
            """)

            # Wait a bit for MutationObserver to fire
            await asyncio.sleep(0.2)

            # 3. Verify buffer entry
            buffer = await bm.page.evaluate("() => window.__VQA_TOAST_BUFFER__")
            assert len(buffer) == 1
            assert "Success Summary" in buffer[0]["text"]
            assert "Detailed message content" in buffer[0]["text"]
            assert buffer[0]["severity"] == "success"
            assert isinstance(buffer[0]["timestamp"], int)

    @pytest.mark.anyio
    async def test_buffer_fifo_limit(self):
        """Verify the buffer respects the 10-item limit."""
        from backend.browser.context import BrowserManager

        async with BrowserManager(run_id="test-fifo-limit") as bm:
            await bm.page.goto("about:blank")

            # Add 15 toasts
            for i in range(15):
                await bm.page.evaluate(
                    """
                    (idx) => {
                        const msg = document.createElement('div');
                        msg.className = 'p-toast-message p-toast-message-info';
                        msg.innerText = `Toast ${idx}`;
                        document.body.appendChild(msg);
                    }
                """,
                    i,
                )

            await asyncio.sleep(0.2)
            buffer = await bm.page.evaluate("() => window.__VQA_TOAST_BUFFER__")

            # Should capped at 10
            assert len(buffer) == 10

            # Should contain the LAST 10 toasts (5 through 14)
            assert "Toast 5" in buffer[0]["text"]
            assert "Toast 14" in buffer[9]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Verifier Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestToastVerifierIntegration:
    """Verify that the verifier correctly reads from the toast buffer."""

    @pytest.mark.anyio
    async def test_verifier_reads_from_buffer(self):
        """Verifier should satisfy toast_message if it exists in the buffer."""
        from backend.browser.context import BrowserManager
        from backend.engine.verifier import _check_single_verification

        async with BrowserManager(run_id="test-verifier-integration") as bm:
            await bm.page.goto("about:blank")

            # 1. Manually populate the buffer (simulate a toast that auto-dismissed)
            await bm.page.evaluate("""
                () => {
                    window.__VQA_TOAST_BUFFER__.push({
                        text: 'Record saved successfully',
                        timestamp: Date.now(),
                        severity: 'success'
                    });
                }
            """)

            # 2. Run the verifier check
            v = {"type": "toast_message", "expected_text": "Record saved"}
            verdict, evidence, _ = await _check_single_verification(bm.page, v, run_id="test-verifier-integration")

            assert verdict == "satisfied"
            assert "T0-buffer" in evidence
            assert "Record saved" in evidence

    @pytest.mark.anyio
    async def test_verifier_ignores_stale_toasts(self):
        """Verifier should ignore toasts older than 15 seconds."""
        from backend.browser.context import BrowserManager
        from backend.engine.verifier import _check_single_verification

        async with BrowserManager(run_id="test-stale-toast") as bm:
            await bm.page.goto("about:blank")

            # 1. Populate buffer with an old toast (20 seconds ago)
            await bm.page.evaluate("""
                () => {
                    window.__VQA_TOAST_BUFFER__.push({
                        text: 'Old stale toast',
                        timestamp: Date.now() - 20000,
                        severity: 'info'
                    });
                }
            """)

            # 2. Run the verifier check
            v = {"type": "toast_message", "expected_text": "stale toast"}
            verdict, evidence, _ = await _check_single_verification(bm.page, v, run_id="test-stale-toast")

            # Should NOT match Tier 0, and since it's not in DOM/cache, should be not_yet
            assert verdict == "not_yet"
