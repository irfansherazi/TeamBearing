from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_dependencies():
    mock_page = AsyncMock()
    mock_page.url = "http://test"
    mock_page.evaluate = AsyncMock(return_value={"total": 1, "visible": 1})
    mock_page.screenshot = AsyncMock(return_value=b"fake")

    mock_manager = MagicMock()
    mock_manager.page = mock_page

    mock_tracker = MagicMock()

    return mock_page, mock_manager, mock_tracker


@pytest.mark.anyio
class TestTask021SuccessLoop:
    async def test_coordinate_action_success_increments_circuit_breaker(self, mock_dependencies):
        from backend.engine.executor import executor_node

        mock_page, mock_manager, mock_tracker = mock_dependencies

        action = {"action": "coordinate_action", "strategy": "som_coordinates", "mark_id": "42"}

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
            patch("backend.engine.executor._dispatch_action", return_value={"success": True, "actual_url": "test"}),
        ):
            state = {"run_id": "run1", "ac_step_index": 0, "planned_action": action, "action_repeat_counts": {}}
            result = await executor_node(state)
            counts = result.get("action_repeat_counts", {})

            assert any(val == 1 for val in counts.values()), (
                "Circuit breaker should increment even on success for coordinate_action"
            )

    async def test_press_key_success_increments_circuit_breaker(self, mock_dependencies):
        from backend.engine.executor import executor_node

        mock_page, mock_manager, mock_tracker = mock_dependencies

        action = {"action": "press_key", "value": "Escape"}

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
            patch("backend.engine.executor._dispatch_action", return_value={"success": True, "actual_url": "test"}),
        ):
            state = {"run_id": "run1", "ac_step_index": 0, "planned_action": action, "action_repeat_counts": {}}
            result = await executor_node(state)
            counts = result.get("action_repeat_counts", {})

            assert any(val == 1 for val in counts.values()), (
                "Circuit breaker should increment even on success for press_key"
            )

    async def test_evaluator_preserves_budget_on_vision_mode_transition(self):
        from backend.engine.evaluator import evaluator_node

        state = {
            "run_id": "test",
            "jira_ticket": {"acceptance_criteria_steps": ["step 1"]},
            "ac_step_index": 0,
            "detailed_execution_log": [{"action_type": "click", "success": False, "error_message": "STRICT_MODE"}],
            "ac_step_action_fail_count": 2,  # Will trigger vision mode (>=2)
            "current_ac_step_action_count": 5,  # Some accumulated actions
            "vision_mode": "dom",
        }

        result = await evaluator_node(state)

        assert result.get("vision_mode") == "som_coordinates"
        assert result.get("current_ac_step_action_count", 0) == 5, (
            "Should preserve the total action count across mode transition"
        )
