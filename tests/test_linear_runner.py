"""
vQA — Unit Tests for Linear Runner
==================================
Module: tests/test_linear_runner.py

Verifies the refactored Week 2 Linear Pipeline Runner:
  - run_card handles completed run (SUCCESS) with proper AC step counts.
  - run_card handles failed run and estimates which step failed correctly.
  - run_batch runs multiple cards and calculates aggregates.
"""

from unittest.mock import AsyncMock, patch
import pytest
from backend.engine.linear_runner import run_card, run_batch


@pytest.mark.anyio
async def test_run_card_success():
    """Verify run_card with a successful pipeline execution."""
    card = {
        "ticket_id": "QA-170",
        "expected_steps": ["Given step A", "When step B", "Then step C"]
    }
    
    from backend.engine.linear_bridge import LinearRunResult
    mock_result = LinearRunResult(
        status="completed",
        pipeline_status="SUCCESS",
        ticket_id="QA-170",
        spec_path="playwright/tests/generated/QA-170.spec.ts",
        elapsed_s=15.5,
    )
    
    with patch("backend.engine.linear_bridge.run_linear_pipeline", new_callable=AsyncMock, return_value=mock_result):
        res = await run_card(card, tenant_id="vpromedia")
        
        assert res["ticket_id"] == "QA-170"
        assert res["status"] == "completed"
        assert res["pipeline_status"] == "SUCCESS"
        assert res["ac_steps_total"] == 3
        assert res["ac_steps_passed"] == 3
        assert len(res["step_results"]) == 3
        assert all(sr["success"] is True for sr in res["step_results"])


@pytest.mark.anyio
async def test_run_card_execute_failed_with_heuristic():
    """Verify run_card estimates step breakdown on execution failure."""
    card = {
        "ticket_id": "QA-170",
        "expected_steps": ["Given step A", "When step B", "Then step C", "And step D"]
    }
    
    from backend.engine.linear_bridge import LinearRunResult
    mock_result = LinearRunResult(
        status="failed",
        pipeline_status="EXECUTE_FAILED",
        ticket_id="QA-170",
        spec_path="playwright/tests/generated/QA-170.spec.ts",
        elapsed_s=25.0,
        error="locator('button#submit') failed: Timeout 5000ms exceeded",
        analysis="Step 3: Click button#submit failed",
    )
    
    with patch("backend.engine.linear_bridge.run_linear_pipeline", new_callable=AsyncMock, return_value=mock_result):
        res = await run_card(card, tenant_id="vpromedia")
        
        assert res["ticket_id"] == "QA-170"
        assert res["status"] == "failed"
        assert res["pipeline_status"] == "EXECUTE_FAILED"
        assert res["ac_steps_total"] == 4
        # Since analysis contains "Step 3" or similar, we expect failed_idx = 2 (0-indexed step 3)
        assert res["ac_steps_passed"] == 2
        assert res["step_results"][0]["success"] is True
        assert res["step_results"][1]["success"] is True
        assert res["step_results"][2]["success"] is False
        assert res["step_results"][3]["success"] is False


@pytest.mark.anyio
async def test_run_batch_calculates_rates():
    """Verify run_batch processes multiple cards and computes correct aggregates."""
    cards = [
        {"ticket_id": "QA-1", "expected_steps": ["step A"]},
        {"ticket_id": "QA-2", "expected_steps": ["step B", "step C"]}
    ]
    
    mock_res_1 = {
        "ticket_id": "QA-1",
        "status": "completed",
        "pipeline_status": "SUCCESS",
        "ac_steps_total": 1,
        "ac_steps_passed": 1,
        "step_results": [{"step": "step A", "success": True}],
        "compile_attempts": 1,
        "elapsed_s": 5.0,
    }
    
    mock_res_2 = {
        "ticket_id": "QA-2",
        "status": "failed",
        "pipeline_status": "EXECUTE_FAILED",
        "ac_steps_total": 2,
        "ac_steps_passed": 1,
        "step_results": [{"step": "step B", "success": True}, {"step": "step C", "success": False}],
        "compile_attempts": 1,
        "elapsed_s": 10.0,
    }
    
    with patch("backend.engine.linear_runner.run_card", new_callable=AsyncMock) as mock_run_card:
        mock_run_card.side_effect = [mock_res_1, mock_res_2]
        
        batch_res = await run_batch(cards, tenant_id="vpromedia", concurrency=1)
        
        assert batch_res["total"] == 2
        assert batch_res["passed"] == 1
        assert batch_res["failed"] == 1
        assert batch_res["compilation_rate"] == 50.0  # 1 out of 2 card success rate
        assert batch_res["total_ac_steps"] == 3
        assert batch_res["passed_ac_steps"] == 2
        assert batch_res["ac_pass_rate"] == 66.7  # 2 out of 3 step success rate
