import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.api.routes import _execute_linear_run

class MockExecuteRequest:
    def __init__(self, ticket_id: str = "QA-106", tenant_id: str = "vpromedia", role: str = "production_manager"):
        self.jira_ticket_id = ticket_id
        self.tenant_id = tenant_id
        self.role = role

@pytest.mark.anyio
async def test_fair_gate_linear_log_only_mvp():
    """Verify that _execute_linear_run runs score_ac_quality on the acceptance criteria and logs it without blocking."""
    run_id = "run-test-fair-gate"
    request = MockExecuteRequest()
    initial_state = {}
    
    mock_ticket = {
        "summary": "Test Summary",
        "description": "Test Description",
        "acceptance_criteria": "Verify page title",
        "acceptance_criteria_steps": ["Step 1"], # already populated so parser is skipped
    }
    
    # Pre-populate run state as routes.py does
    from backend.api.routes import _run_states
    _run_states[run_id] = {
        "status": "queued",
        "state": initial_state,
        "jira_ticket_id": request.jira_ticket_id,
        "role": request.role,
    }
    
    mock_quality_result = MagicMock()
    mock_quality_result.overall_score = 8
    mock_quality_result.quality_grade = "good"
    
    with patch("backend.jira.client.fetch_ticket_context", new_callable=AsyncMock, return_value=mock_ticket), \
         patch("backend.engine.ac_quality_gate.score_ac_quality", return_value=mock_quality_result) as mock_score, \
         patch("backend.api.routes.run_linear_pipeline", new_callable=AsyncMock) as mock_run_pipe:
        
        from backend.engine.linear_bridge import LinearRunResult
        mock_run_pipe.return_value = LinearRunResult(
            status="completed",
            pipeline_status="SUCCESS",
            ticket_id="QA-106",
            elapsed_s=1.5,
        )
        
        with patch("backend.api.routes.logger.info") as mock_log:
            await _execute_linear_run(run_id, request, initial_state)
            
            # Assert score_ac_quality is called with the acceptance criteria
            mock_score.assert_called_once_with("Verify page title")
            
            # Assert that the score was logged (format string + arg check)
            any_fair_log = any(
                "Linear: AC Quality score=%d/10" in args[0] and args[2] == 8
                for args, kwargs in mock_log.call_args_list
            )
            assert any_fair_log is True
            
            # Assert that pipeline succeeded (non-blocking)
            assert _run_states[run_id]["status"] == "completed"
