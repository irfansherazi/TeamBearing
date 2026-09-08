"""
TASK-082: Production Readiness Hardening - Pillar 4: Playwright Lifecycle
========================================================================
Tests for ensuring graceful and idempotent Playwright teardown.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from backend.browser.context import BrowserManager

@pytest.mark.anyio
async def test_close_already_closed_browser_no_exception():
    """
    AC-4: BrowserManager.close() should suppress WriteUnixTransport errors.
    """
    bm = BrowserManager(run_id="test-run")
    
    # Mock internal components
    bm._browser = AsyncMock()
    bm._playwright = AsyncMock()
    bm._context = AsyncMock()
    
    # Simulate WriteUnixTransport error on browser.close()
    bm._browser.close.side_effect = Exception("WriteUnixTransport closed=True")
    
    # This should NOT raise an exception
    await bm.close()
    
    # Ensure it reached the end and cleared references
    assert bm._browser is None
    assert bm._playwright is None

@pytest.mark.anyio
async def test_close_idempotent_double_call():
    """
    Ensure calling close() twice is safe.
    """
    bm = BrowserManager(run_id="test-run")
    bm._browser = AsyncMock()
    bm._playwright = AsyncMock()
    bm._context = AsyncMock()
    
    await bm.close()
    # Second call should be a no-op and not crash
    await bm.close()
    
    assert bm._browser is None

@pytest.mark.anyio
async def test_teardown_order_context_before_browser():
    """
    AC-4: Teardown order matters for video finalization.
    Context must close before browser.
    """
    bm = BrowserManager(run_id="test-run")
    bm._browser = AsyncMock()
    bm._playwright = AsyncMock()
    bm._context = AsyncMock()
    
    # Track call order
    call_order = []
    
    def track_ctx(): call_order.append("context")
    def track_browser(): call_order.append("browser")
    
    bm._context.close.side_effect = track_ctx
    bm._browser.close.side_effect = track_browser
    
    await bm.close()
    
    assert "context" in call_order
    assert "browser" in call_order
    assert call_order.index("context") < call_order.index("browser")
