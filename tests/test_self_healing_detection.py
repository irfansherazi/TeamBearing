"""
vQA — Unit Tests for A11y-Powered Self-Healing
==============================================
Module: tests/test_self_healing_detection.py

Verifies the detection of timing/interaction failures and the execution
of the 3-retry self-healing loop in the linear bridge pipeline.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pathlib
from backend.engine.linear_bridge import (
    _detect_timing_failure,
    _detect_interaction_change,
    _run_pipeline_inner,
    LinearRunResult
)


def test_detect_timing_failure():
    """Verify that timing and timeout failures are correctly identified."""
    timeout_log = "Error: page.click: Timeout 5000ms exceeded.\n=========================== logs ==========================="
    assert _detect_timing_failure(timeout_log) is True
    
    timeout_err = "playwright.async_api.TimeoutError: waiting for locator('button#submit') to be visible"
    assert _detect_timing_failure(timeout_err) is True
    
    happy_log = "playwright exited 0 (all tests passed)"
    assert _detect_timing_failure(happy_log) is False


def test_detect_interaction_change_patterns():
    """Verify that interaction changes are identified and getByRole target/name are parsed."""
    # Obscured/not clickable
    obscured_log = (
        "Error: page.click: element is not clickable because it is obscured by another element.\n"
        "locator.click: waiting for locator('button')\n"
        "Failed line: await page.getByRole(\"button\", { name: \"Save\" }).click();"
    )
    res = _detect_interaction_change(obscured_log)
    assert res == ("button", "Save")
    
    # Not visible / getByRole with single quotes
    not_visible_log = (
        "Error: locator.click: element is not visible\n"
        "Failed line: await page.getByRole('textbox', { name: 'Email Address' }).fill('abc');"
    )
    res2 = _detect_interaction_change(not_visible_log)
    assert res2 == ("textbox", "Email Address")
    
    # Happy path
    happy_log = "playwright exited 0 (all tests passed)"
    assert _detect_interaction_change(happy_log) is None


@pytest.mark.anyio
async def test_self_healing_loop_timing_retry():
    """Verify that a timing failure triggers asyncio.sleep and a successful retry on attempt 2."""
    run_id = "test-timing-sh"
    card = {"ticket_id": "QA-106"}
    
    # Mock pipeline nodes
    mock_gen = {"status": "generated", "spec_path": "playwright/tests/generated/QA-106.spec.ts", "spec_content": "test()"}
    mock_val = {"status": "COMPILE_OK", "attempts": 1}
    mock_analyze = "Analysis text"
    
    mock_emit = AsyncMock()
    
    # Attempt 1: Timeout failure, Attempt 2: Success
    mock_run_playwright = AsyncMock()
    mock_run_playwright.side_effect = [
        (False, "Error: Timeout 5000ms exceeded waiting for locator"),
        (True, "SUCCESS")
    ]
    
    # We patch generator, validator, analyzer, spec execution, sleep, and path writes
    with patch("backend.engine.generator_node.generate_spec", new_callable=AsyncMock, return_value=mock_gen), \
         patch("backend.engine.validator_node.validate_spec", new_callable=AsyncMock, return_value=mock_val), \
         patch("backend.engine.linear_bridge._run_playwright_spec", mock_run_playwright), \
         patch("backend.engine.linear_bridge._run_analyze", new_callable=AsyncMock, return_value=mock_analyze), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="test()"), \
         patch("pathlib.Path.write_text") as mock_write:
         
        result = await _run_pipeline_inner(run_id, card, "vpromedia", "QA-106", mock_emit)
        
        # Verify success
        assert result.status == "completed"
        assert result.pipeline_status == "SUCCESS"
        
        # Verify it slept and retried
        mock_sleep.assert_called_once_with(3.0)
        assert mock_run_playwright.call_count == 2


@pytest.mark.anyio
async def test_self_healing_loop_interaction_rewrite_retry():
    """Verify that an interaction shift failure fuzzy matches, rewrites the spec, and retries successfully."""
    run_id = "test-interaction-sh"
    
    # Original spec has "Save"
    spec_content = "await page.getByRole(\"button\", { name: \"Save\" }).click();"
    
    # We provide "Save Changes" as a dynamic locator on the viewport in the card's a11y_elements
    card = {
        "ticket_id": "QA-106",
        "a11y_elements": [
            {"role": "button", "name": "Save Changes", "locator": 'page.getByRole("button", {"name": "Save Changes"})'}
        ]
    }
    
    # Mock pipeline nodes
    mock_gen = {"status": "generated", "spec_path": "playwright/tests/generated/QA-106.spec.ts", "spec_content": spec_content}
    mock_val = {"status": "COMPILE_OK", "attempts": 1}
    mock_analyze = "Analysis text"
    
    mock_emit = AsyncMock()
    
    # Attempt 1: Obscured/not clickable on "Save"
    # Attempt 2: Success (using "Save Changes")
    mock_run_playwright = AsyncMock()
    mock_run_playwright.side_effect = [
        (False, "Error: element not clickable.\nFailed line: await page.getByRole(\"button\", { name: \"Save\" }).click();"),
        (True, "SUCCESS")
    ]
    
    written_contents = []
    def mock_write_text(content, encoding=None):
        written_contents.append(content)
        
    with patch("backend.engine.generator_node.generate_spec", new_callable=AsyncMock, return_value=mock_gen), \
         patch("backend.engine.validator_node.validate_spec", new_callable=AsyncMock, return_value=mock_val), \
         patch("backend.engine.linear_bridge._run_playwright_spec", mock_run_playwright), \
         patch("backend.engine.linear_bridge._run_analyze", new_callable=AsyncMock, return_value=mock_analyze), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=spec_content), \
         patch("pathlib.Path.write_text", side_effect=mock_write_text) as mock_write:
         
        result = await _run_pipeline_inner(run_id, card, "vpromedia", "QA-106", mock_emit)
        
        # Verify success
        assert result.status == "completed"
        assert result.pipeline_status == "SUCCESS"
        
        # Verify spec content was rewritten with "Save Changes" locator!
        assert len(written_contents) == 1
        assert "Save Changes" in written_contents[0]
        assert "Save" not in written_contents[0].replace("Save Changes", "") # original "Save" is gone
        
        # Ensure it was run twice
        assert mock_run_playwright.call_count == 2
