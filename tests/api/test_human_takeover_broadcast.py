"""
TASK-082: Production Readiness Hardening - Pillar 3: Human Takeover Broadcast
============================================================================
Tests for ensuring _broadcast_human_takeover accepts novnc_url without crashing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.api.routes import _broadcast_human_takeover

@pytest.mark.anyio
async def test_broadcast_accepts_novnc_url_kwarg():
    """
    AC-3: Ensure _broadcast_human_takeover accepts novnc_url kwarg.
    """
    # We need to mock _ws_connections and vnc_builder if we don't have real ones
    with patch("backend.api.routes._ws_connections", { "test-run": [MagicMock()] }):
        # This call should NOT raise TypeError
        await _broadcast_human_takeover(
            run_id="test-run",
            ac_step="Step 1",
            ac_step_index=0,
            error_message="Test error",
            instructions="Do something",
            novnc_url="http://localhost:6080/vnc.html"
        )

@pytest.mark.anyio
async def test_broadcast_novnc_url_none_safe():
    """
    Ensure novnc_url=None is also safe.
    """
    with patch("backend.api.routes._ws_connections", { "test-run": [MagicMock()] }):
        await _broadcast_human_takeover(
            run_id="test-run",
            ac_step="Step 1",
            ac_step_index=0,
            error_message="Test error",
            novnc_url=None
        )
