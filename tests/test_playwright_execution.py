from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.state import make_initial_state

# We expect this to fail initially (RED phase)
try:
    from backend.engine.playwright_executor import playwright_executor_node
except ImportError:
    playwright_executor_node = None

@pytest.fixture
def state():
    return make_initial_state(
        run_id="test-run",
        jira_ticket_id="VC2-1234",
        role="account_executive",
        target_url="https://test.com",
        mode="headless",
        execution_engine="static",
        playwright_test_id="demo.spec.ts"
    )

@pytest.mark.asyncio
async def test_playwright_executor_not_implemented(state):
    if playwright_executor_node is None:
        pytest.fail("playwright_executor_node not implemented yet")

@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
@patch("backend.storage.playwright_registry.PlaywrightRegistry.get_test")
@patch("os.path.exists")
async def test_playwright_executor_success(mock_exists, mock_get_test, mock_exec, state):
    if playwright_executor_node is None:
        pytest.skip("playwright_executor_node not implemented yet")

    mock_exists.return_value = True
    mock_get_test.return_value = {"path": "backend/playwright_tests/demo.spec.ts"}

    # Mock async subprocess
    process = MagicMock()
    process.wait = AsyncMock(return_value=0)
    process.stdout.readline = AsyncMock(side_effect=[b"Running test...\n", b"Test passed!\n", b""])
    process.stderr.readline = AsyncMock(return_value=b"")
    mock_exec.return_value = process

    with patch("backend.api.routes._broadcast_terminal_log", new_callable=AsyncMock) as mock_broadcast:
        result = await playwright_executor_node(state)

        assert result["static_execution_pid"] is None
        assert result["_next_node"] == "reporter"
        assert mock_exec.called
        # Check if logs were "streamed" (broadcast called)
        assert mock_broadcast.called
        assert mock_broadcast.call_count == 2
