
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.engine.verifier import step_verifier_node

@pytest.mark.anyio
async def test_verifier_applies_human_correction():
    """AC-4: Human Correction Loop should override verifier logic."""
    state = {
        "run_id": "run-123",
        "jira_ticket": {"acceptance_criteria_steps": ["Step 1"], "id": "JIRA-123"},
        "ac_step_index": 0,
        "verifier_correction": {
            "ac_step_index": 0,
            "reason": "User marked as False Positive"
        },
        "ac_steps_completed": [],
    }
    
    mock_page = AsyncMock()
    mock_manager = MagicMock()
    mock_manager.page = mock_page
    
    # We patch everything to ensure it doesn't even try to capture screenshots or call LLM
    with patch("backend.engine.verifier.get_manager", return_value=mock_manager), \
         patch("backend.engine.verifier.capture_screenshot_b64") as mock_capture, \
         patch("backend.engine.verifier._get_verifier_llm") as mock_get_llm:
        
        result = await step_verifier_node(state)
        
        assert result["_verifier_verdict"] == "satisfied"
        assert "HUMAN OVERRIDE" in result["agent_critique"]
        assert result["ac_step_index"] == 1
        assert result["verifier_correction"] is None # Should be consumed
        
        # Verify no screenshots or LLM calls were made
        mock_capture.assert_not_called()
        mock_get_llm.assert_not_called()
