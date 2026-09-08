from unittest.mock import MagicMock, patch

import pytest

from backend.engine.planner import planner_node
from backend.engine.state import make_initial_state


@pytest.fixture
def mock_planner_dependencies():
    with (
        patch("backend.engine.planner.get_manager") as mock_get_manager,
        patch("backend.engine.planner.capture_screenshot_b64") as mock_screenshot,
        patch("backend.engine.planner.extract_accessibility_tree") as mock_a11y,
        patch("backend.engine.planner._invoke_planner_with_tools") as mock_invoke,
        patch("backend.engine.planner._wait_for_page_stability") as mock_stability,
        patch("backend.engine.planner.extract_interactive_summary") as mock_summary,
        patch("backend.engine.planner.settings") as mock_settings,
    ):
        mock_manager = MagicMock()
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False

        # Mocking async methods
        async def mock_evaluate(*args, **kwargs):
            return "[]"

        mock_page.evaluate = mock_evaluate

        async def mock_wait_for_function(*args, **kwargs):
            return True

        mock_page.wait_for_function = mock_wait_for_function

        mock_manager.page = mock_page
        mock_get_manager.return_value = mock_manager

        # Valid base64 for 'fake_screenshot' (empty image or similar)
        # 'Z3VpZGFuY2U=' is 'guidance' in b64, padded correctly
        mock_screenshot.return_value = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        mock_a11y.return_value = "fake_a11y"
        mock_invoke.return_value = {"action": "wait", "reasoning": "testing"}
        mock_stability.return_value = {"wait_ms": 0, "spinner_cleared": False, "modal_detected": False}
        mock_summary.return_value = "fake_summary"
        mock_settings.prompt_budget_enabled = False

        yield {"manager": mock_manager, "page": mock_page, "invoke": mock_invoke}


@pytest.mark.anyio
async def test_planner_injects_and_clears_hitl_override(mock_planner_dependencies):
    state = make_initial_state(
        run_id="test-run", jira_ticket_id="VC-123", role="admin", target_url="http://test.com", mode="headless"
    )

    # Set up a HITL override
    state["hitl_override"] = {
        "ac_step": "Step 1: Click stuff",
        "explanation": "I clicked the blue button because the red one was broken.",
        "action_sequence": [{"action": "click", "selector": "button.blue"}],
    }

    # Run the planner node
    result = await planner_node(state)

    # Verify hitl_override is cleared in the result
    assert result["hitl_override"] is None

    # Verify that the system prompt passed to the LLM contained the override info
    args, kwargs = mock_planner_dependencies["invoke"].call_args
    system_prompt = kwargs.get("system_prompt", "")

    assert "HUMAN OPERATOR OVERRIDE" in system_prompt
    assert "I clicked the blue button" in system_prompt
    assert "button.blue" in system_prompt
