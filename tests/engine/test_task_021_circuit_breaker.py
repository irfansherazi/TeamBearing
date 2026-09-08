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
class TestTask021CircuitBreaker:
    async def test_deduplication_key_differentiates_mark_id(self, mock_dependencies):
        from backend.engine.executor import executor_node

        mock_page, mock_manager, mock_tracker = mock_dependencies

        action1 = {
            "action": "coordinate_action",
            "strategy": "som_coordinates",
            "mark_id": "42",
            "target_text": "Option A",
        }

        action2 = {
            "action": "coordinate_action",
            "strategy": "som_coordinates",
            "mark_id": "43",
            "target_text": "Option B",
        }

        with (
            patch("backend.engine.executor.get_manager", return_value=mock_manager),
            patch("backend.engine.executor.get_tracker", return_value=mock_tracker),
            patch(
                "backend.engine.executor._dispatch_action",
                return_value={"success": False, "error_message": "err", "actual_url": "test"},
            ),
        ):
            state1 = {"run_id": "run1", "ac_step_index": 0, "planned_action": action1, "action_repeat_counts": {}}
            result1 = await executor_node(state1)
            counts1 = result1.get("action_repeat_counts", {})
            keys1 = list(counts1.keys())

            state2 = {"run_id": "run1", "ac_step_index": 0, "planned_action": action2, "action_repeat_counts": counts1}
            result2 = await executor_node(state2)
            counts2 = result2.get("action_repeat_counts", {})
            keys2 = list(counts2.keys())

            assert len(keys2) == 2, f"Expected 2 unique keys due to different mark_ids, but got {keys2}"

            # Now repeat action1, it should increment
            state3 = {"run_id": "run1", "ac_step_index": 0, "planned_action": action1, "action_repeat_counts": counts2}
            result3 = await executor_node(state3)
            counts3 = result3.get("action_repeat_counts", {})

            assert counts3[keys1[0]] == 2, "Expected repeat count to increment for the same mark_id"
