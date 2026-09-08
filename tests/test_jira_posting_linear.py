import pytest
from unittest.mock import AsyncMock, patch
from backend.api.routes import post_triage_to_jira

@pytest.mark.anyio
async def test_jira_posting_linear_success():
    """Verify that post_triage_to_jira successfully reads failure_analysis from linear run_data and posts to Jira."""
    run_id = "run-test-jira-posting"
    
    # Pre-populate linear-style run state
    from backend.api.routes import _run_states
    _run_states[run_id] = {
        "status": "failed",
        "jira_ticket_id": "QA-106",
        "analysis": "This is the linear pipeline's analysis.",
        "failure_analysis": {"jira_comment": "This is the linear pipeline's analysis."},
    }
    
    with patch("backend.jira.client.post_jira_comment", new_callable=AsyncMock, return_value=True) as mock_post:
        result = await post_triage_to_jira(run_id)
        
        assert result == {"status": "posted", "ticket_id": "QA-106"}
        mock_post.assert_called_once_with("QA-106", "This is the linear pipeline's analysis.")
