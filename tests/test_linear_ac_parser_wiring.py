import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.schemas import TestPlan, StructuredACStep
from backend.api.routes import _execute_linear_run

class MockExecuteRequest:
    def __init__(self, ticket_id: str = "QA-106", tenant_id: str = "vpromedia", role: str = "production_manager"):
        self.jira_ticket_id = ticket_id
        self.tenant_id = tenant_id
        self.role = role

@pytest.mark.anyio
async def test_linear_run_wires_ac_parser_when_expected_steps_empty():
    """Verify that _execute_linear_run calls ac_parser_node if expected_steps is empty."""
    run_id = "run-test-wiring"
    request = MockExecuteRequest()
    initial_state = {}
    
    mock_ticket = {
        "summary": "Test Summary",
        "description": "Test Description",
        "acceptance_criteria": "Verify page title",
        "acceptance_criteria_steps": [], # Empty legacy steps
    }
    
    # Pre-populate run state as routes.py does
    from backend.api.routes import _run_states
    _run_states[run_id] = {
        "status": "queued",
        "state": initial_state,
        "jira_ticket_id": request.jira_ticket_id,
        "role": request.role,
    }
    
    mock_parsed_result = {
        "jira_ticket": {
            "acceptance_criteria_steps": ["Navigate to page and check title", "Verify text is visible"],
        },
        "test_plan": None,
    }
    
    with patch("backend.jira.client.fetch_ticket_context", new_callable=AsyncMock, return_value=mock_ticket), \
         patch("backend.engine.ac_parser.ac_parser_node", new_callable=AsyncMock, return_value=mock_parsed_result) as mock_parser, \
         patch("backend.api.routes.run_linear_pipeline", new_callable=AsyncMock) as mock_run_pipe:
        
        # We want to mock run_linear_pipeline to just return a dummy result
        from backend.engine.linear_bridge import LinearRunResult
        mock_run_pipe.return_value = LinearRunResult(
            status="completed",
            pipeline_status="SUCCESS",
            ticket_id="QA-106",
            elapsed_s=1.5,
        )
        
        await _execute_linear_run(run_id, request, initial_state)
        
        # Ensure ac_parser_node was called because expected_steps was empty
        mock_parser.assert_called_once()
        called_state = mock_parser.call_args[0][0]
        assert called_state["run_id"] == run_id
        assert called_state["jira_ticket"]["acceptance_criteria"] == "Verify page title"
        
        # Ensure the card passed to run_linear_pipeline had expected_steps populated
        called_args, called_kwargs = mock_run_pipe.call_args
        passed_card = called_kwargs.get("card") or called_args[1]
        assert passed_card["expected_steps"] == ["Navigate to page and check title", "Verify text is visible"]
