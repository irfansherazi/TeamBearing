import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from backend.engine.verifier import step_verifier_node

@pytest.mark.asyncio
async def test_step_verifier_wait_logic():
    """Verify verifier sleeps when post_action_wait_ms is set."""
    state = {
        "run_id": "test-run",
        "jira_ticket": {"acceptance_criteria_steps": ["Step 1"]},
        "ac_step_index": 0,
        "test_plan": {
            "steps": [
                {
                    "step_id": 1,
                    "goal": "Step 1",
                    "post_action_wait_ms": 1500,
                    "verification": []
                }
            ]
        },
        "current_screenshot_b64": "fake-b64",
        "planned_action": {"action": "click"}
    }
    
    # Mock everything we need to avoid side effects
    with patch("backend.engine.verifier.get_manager") as mock_get_manager, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("backend.engine.verifier._run_programmatic_verifications", new_callable=AsyncMock) as mock_prog:
        
        mock_page = MagicMock()
        mock_get_manager.return_value.page = mock_page
        mock_prog.return_value = ("satisfied", "passed", [])
        
        await step_verifier_node(state)
        
        # Verify sleep was called with 1.5 seconds
        mock_sleep.assert_awaited_once_with(1.5)

@pytest.mark.asyncio
async def test_step_verifier_no_wait_logic():
    """Verify verifier does NOT sleep when post_action_wait_ms is 0."""
    state = {
        "run_id": "test-run",
        "jira_ticket": {"acceptance_criteria_steps": ["Step 1"]},
        "ac_step_index": 0,
        "test_plan": {
            "steps": [
                {
                    "step_id": 1,
                    "goal": "Step 1",
                    "post_action_wait_ms": 0,
                    "verification": []
                }
            ]
        },
        "current_screenshot_b64": "fake-b64",
        "planned_action": {"action": "click"}
    }
    
    with patch("backend.engine.verifier.get_manager") as mock_get_manager, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("backend.engine.verifier._run_programmatic_verifications", new_callable=AsyncMock) as mock_prog:
        
        mock_page = MagicMock()
        mock_get_manager.return_value.page = mock_page
        mock_prog.return_value = ("satisfied", "passed", [])
        
        await step_verifier_node(state)
        
        # Verify sleep was NOT called
        mock_sleep.assert_not_awaited()
