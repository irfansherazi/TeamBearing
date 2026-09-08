from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.state import VQAState
from backend.engine.verifier import step_verifier_node


@pytest.mark.anyio
async def test_verifier_not_yet_strips_dom_snapshot_from_critique():
    """
    Test that when the verifier returns a NOT_YET verdict, the returned
    agent_critique and failure diary error strings do not contain the raw
    <page_state> XML (which causes prompt bloat).
    """
    # Create a mock state
    state = VQAState(
        run_id="test_run",
        jira_ticket={"acceptance_criteria_steps": ["Step 1"]},
        ac_step_index=0,
        detailed_execution_log=[{"step_index": 0, "action_type": "click", "success": True}],
        planned_action={"action": "click", "strategy": "get_by_role", "name": "Submit"},
        test_plan=None,  # Force LLM fallback
        current_screenshot_b64="fake_b64",
    )

    # Mock the LLM to return NOT_YET
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "NOT_YET: Loading spinner is still visible"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    # Mock PageStateTracker
    mock_tracker = MagicMock()
    mock_tracker.format_for_prompt.return_value = "<page_state>BIG FAT XML</page_state>"

    with (
        patch("backend.engine.verifier._get_verifier_llm", return_value=mock_llm),
        patch("backend.engine.verifier.get_manager"),
        patch("backend.engine.state_tracker.get_tracker", return_value=mock_tracker),
    ):
        result = await step_verifier_node(state)

        # Verify the verdict is planner
        assert result["_next_node"] == "planner"
        assert result["_verifier_verdict"] == "not_yet"

        # Check the critique string
        agent_critique = result.get("agent_critique", "")

        # Ensure the brief reference is there
        assert "DOM state: (see <page_state> at top of prompt)" in agent_critique

        # Ensure the raw XML is NOT injected
        assert "<page_state>BIG FAT XML</page_state>" not in agent_critique

        # Check the failure diary entry error string
        diary = result.get("ac_step_failure_diary", [])
        if diary:
            last_entry = diary[-1]
            error_msg = last_entry.get("error", "")
            assert "DOM state at rejection: (see <page_state> at top of prompt)" in error_msg
            assert "<page_state>BIG FAT XML</page_state>" not in error_msg
