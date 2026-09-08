"""
TASK-082: Production Readiness Hardening - Pillar 2: Visual Delta CV Verification
================================================================================
Tests for dual-signal (Visual + DOM) verification of CV-fallback clicks.
Ensures canvas/SPA targets with no DOM mutation but visual changes are
correctly identified as successful.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.engine.verifier import cv_fallback_state_change_check

@pytest.mark.anyio
async def test_cv_fallback_visual_delta_canvas_click_succeeds():
    """
    AC-2: CV fallback succeeds if visual delta is detected, even if DOM is unchanged.
    """
    page = AsyncMock()
    page.is_closed = MagicMock(return_value=False)
    page.url = "http://example.com"
    
    pre_state = {
        "url": "http://example.com",
        "element_count": 100,
        "aria_snapshot": "{}"
    }
    
    # Mock screenshot capture to return different values pre/post
    # Note: In the real implementation, we'll need to mock capture_screenshot_b64
    # which is likely used inside cv_fallback_state_change_check.
    
    # We'll use different base64 strings to simulate a visual change.
    # A real implementation would compare the pixels.
    # For RED phase, we just want to see it fail because it doesn't have visual check yet.
    
    with patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture:
        # First call (inside verifier for post-state)
        mock_capture.return_value = "post_screenshot_different"
        
        # We need to simulate that DOM signals (URL, ARIA, count) are UNCHANGED
        page.evaluate.return_value = 100 # count unchanged
        page.accessibility.snapshot.return_value = {} # aria unchanged
        
        # Call with pre_screenshot_b64 passed in
        result = await cv_fallback_state_change_check(
            page, 
            pre_state, 
            pre_screenshot_b64="pre_screenshot_original"
        )
        
        # Should be True because of visual delta
        assert result is True

@pytest.mark.anyio
async def test_cv_fallback_both_unchanged_fails():
    """
    CV fallback fails if BOTH DOM and Visual are unchanged.
    """
    page = AsyncMock()
    page.is_closed = MagicMock(return_value=False)
    page.url = "http://example.com"
    
    pre_state = {
        "url": "http://example.com",
        "element_count": 100,
        "aria_snapshot": "{}"
    }
    
    with patch("backend.engine.verifier.capture_screenshot_b64", new_callable=AsyncMock) as mock_capture:
        mock_capture.return_value = "identical_screenshot"
        page.evaluate.return_value = 100
        page.accessibility.snapshot.return_value = {}
        
        result = await cv_fallback_state_change_check(
            page, 
            pre_state, 
            pre_screenshot_b64="identical_screenshot"
        )
        
        assert result is False

@pytest.mark.anyio
async def test_cv_fallback_visual_diff_threshold():
    """
    Visual delta should ignore minor noise (below threshold).
    """
    # This might be harder to test without real images, 
    # but we can mock the pixel diff result.
    pass
