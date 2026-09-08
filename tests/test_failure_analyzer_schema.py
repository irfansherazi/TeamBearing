import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.engine.failure_analyzer import run_failure_analysis
from backend.engine.state import VQAState


@pytest.mark.asyncio
async def test_failure_analyzer_produces_lesson():
    # Mock state
    state: VQAState = {
        "run_id": "test-run",
        "jira_ticket": {
            "ticket_id": "QA-123",
            "summary": "Test Ticket",
            "description": "Desc",
            "acceptance_criteria_steps": ["Step 1", "Step 2"]
        },
        "ac_steps_completed": [0], # Step 1 passed, Step 2 failed
        "detailed_execution_log": [
            {"action_type": "click", "success": True, "reasoning": "Clicked 1"},
            {"action_type": "click", "success": False, "error_message": "Timeout", "reasoning": "Tried 2"}
        ],
        "role_context": {"role_name": "Admin"},
    }

    # Mock LLM response
    mock_response = AsyncMock()
    mock_response.content = json.dumps({
        "overall": "agent_issue",
        "summary": "The agent timed out on step 2.",
        "steps": [
            {
                "ac_index": 1,
                "ac_step": "Step 2",
                "classification": "agent_issue",
                "confidence": "high",
                "reason": "Selector not found",
                "visual_observation": "The page was still loading",
                "lesson": {
                    "diagnosis": "Selector .btn-next was not present",
                    "suggestion": "Wait for .btn-next",
                    "suggested_selector": ".btn-next",
                    "confidence": 0.95
                }
            }
        ]
    })

    with patch("backend.llm.get_llm") as mock_get_llm:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = await run_failure_analysis(state)

    assert result["overall"] == "agent_issue"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["lesson"]["suggested_selector"] == ".btn-next"
    assert result["error_context"]["ticket"] == "QA-123"
    assert result["error_context"]["failed_steps"][0]["lesson"]["diagnosis"] == "Selector .btn-next was not present"
