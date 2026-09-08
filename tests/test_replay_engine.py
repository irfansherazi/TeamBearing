"""
vQA — Unit Tests: ReplayEngine & replay_check_node (TASK-031 Phase 3)
======================================================================
Module: tests/test_replay_engine.py

Tests the Smart Replay system:
  - backend/engine/replay_engine.py::ReplayEngine
  - backend/engine/graph.py::replay_check_node
  - backend/engine/graph.py::route_after_replay_check

Coverage:
  - No accepted test → routes to planner (AC-HAPPY-5)
  - Smart replay disabled via settings → routes to planner (AC-HAPPY-5)
  - Accepted test found → replay dispatches all actions (AC-HAPPY-5)
  - Replay success → replay_succeeded=True, _next_node="reporter" (AC-HAPPY-5)
  - Replay step failure → fallback to planner, replay_failed=True (AC-HAPPY-6)
  - route_after_replay_check routing logic (AC-HAPPY-5)

Author: vQA Build Agent (TASK-031 Phase 3)
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_state() -> dict:
    """Minimal VQAState dict for replay tests."""
    return {
        "run_id": "run-replay-test-001",
        "jira_ticket": {
            "ticket_id": "VC2-9001",
            "acceptance_criteria_steps": [
                "Log in as Account Executive",
                "Click New Request button",
                "Select Radio Commercial",
            ],
        },
        "detailed_execution_log": [],
        "ac_steps_completed": [],
        "replay_succeeded": False,
        "replay_failed": False,
        "_next_node": "",
    }


@pytest.fixture
def sample_replay_actions() -> list[dict]:
    """Sample accepted test replay actions."""
    return [
        {
            "step_index": 0,
            "action_type": "navigate",
            "action_payload": {"action": "navigate", "url": "https://example.com"},
            "locator_strategy": "",
            "locator_value": "",
            "success": True,
        },
        {
            "step_index": 1,
            "action_type": "click",
            "action_payload": {
                "action": "click",
                "strategy": "get_by_role",
                "role": "button",
                "name": "New Request",
            },
            "locator_strategy": "get_by_role",
            "locator_value": "role=button, name='New Request'",
            "success": True,
        },
    ]


@pytest.fixture
def accepted_record(sample_replay_actions) -> dict:
    """A simulated accepted test record returned by AcceptedTestStore.load()."""
    return {
        "ticket_id": "VC2-9001",
        "ac_hash": "a3f8c12de901",
        "run_id": "run-original-001",
        "accepted_at": "2026-05-19T12:00:00Z",
        "execution_log": sample_replay_actions,
        "replay_actions": sample_replay_actions,
        "step_count": len(sample_replay_actions),
    }


# ---------------------------------------------------------------------------
# ReplayEngine: no accepted test → route to planner
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestReplayEngineNoAcceptedTest:
    """Tests for when no accepted test is found."""

    async def test_no_accepted_test_routes_to_planner(
        self,
        minimal_state: dict,
    ):
        """
        AC-HAPPY-5: When no accepted test exists, replay_check routes to planner.
        replay_succeeded=False, replay_failed=False, _next_node=planner.
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = None  # No accepted test
            mock_store_factory.return_value = mock_store

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["replay_succeeded"] is False
        assert result["replay_failed"] is False
        assert result["_next_node"] == "planner"

    async def test_smart_replay_disabled_routes_to_planner(
        self,
        minimal_state: dict,
    ):
        """
        AC-HAPPY-5: When ENABLE_SMART_REPLAY=False, always routes to planner.
        """
        from backend.engine.replay_engine import ReplayEngine

        with patch("backend.engine.replay_engine.settings") as mock_settings:
            mock_settings.enable_smart_replay = False

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["_next_node"] == "planner"
        assert result["replay_succeeded"] is False
        assert result["replay_failed"] is False

    async def test_empty_replay_actions_routes_to_planner(
        self,
        minimal_state: dict,
    ):
        """Accepted record with no replay_actions → route to planner."""
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = {
                "ticket_id": "VC2-9001",
                "replay_actions": [],  # empty!
            }
            mock_store_factory.return_value = mock_store

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["_next_node"] == "planner"
        assert result["replay_succeeded"] is False


# ---------------------------------------------------------------------------
# ReplayEngine: successful replay
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestReplayEngineSuccess:
    """Tests for successful replay execution."""

    async def test_successful_replay_sets_replay_succeeded(
        self,
        minimal_state: dict,
        accepted_record: dict,
        sample_replay_actions: list[dict],
    ):
        """
        AC-HAPPY-5: When all replay steps succeed, replay_succeeded=True
        and _next_node="reporter".
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch("backend.engine.replay_engine.get_manager") as mock_get_manager,
            patch("backend.engine.replay_engine.dispatch_action") as mock_dispatch,
        ):
            mock_settings.enable_smart_replay = True

            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            # Mock BrowserManager
            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_manager = MagicMock()
            mock_manager.page = mock_page
            mock_get_manager.return_value = mock_manager

            # All actions succeed
            mock_dispatch.return_value = {"success": True}

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["replay_succeeded"] is True, f"Expected replay_succeeded=True. Got: {result}"
        assert result["replay_failed"] is False
        assert result["_next_node"] == "reporter"

    async def test_successful_replay_marks_all_ac_steps_completed(
        self,
        minimal_state: dict,
        accepted_record: dict,
    ):
        """
        AC-HAPPY-5: After successful replay, all AC step indices are in
        ac_steps_completed.
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch("backend.engine.replay_engine.get_manager") as mock_get_manager,
            patch("backend.engine.replay_engine.dispatch_action") as mock_dispatch,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_manager = MagicMock()
            mock_manager.page = mock_page
            mock_get_manager.return_value = mock_manager
            mock_dispatch.return_value = {"success": True}

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        # All 3 AC steps should be marked complete
        ac_steps = minimal_state["jira_ticket"]["acceptance_criteria_steps"]
        completed = result.get("ac_steps_completed", [])
        assert set(completed) == set(range(len(ac_steps))), (
            f"Expected all AC steps completed {list(range(len(ac_steps)))}, got {completed}"
        )

    async def test_successful_replay_populates_execution_log(
        self,
        minimal_state: dict,
        accepted_record: dict,
        sample_replay_actions: list[dict],
    ):
        """
        AC-HAPPY-5: Replay steps are recorded in detailed_execution_log
        with replay_source='accepted_test'.
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch("backend.engine.replay_engine.get_manager") as mock_get_manager,
            patch("backend.engine.replay_engine.dispatch_action") as mock_dispatch,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_manager = MagicMock()
            mock_manager.page = mock_page
            mock_get_manager.return_value = mock_manager
            mock_dispatch.return_value = {"success": True}

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        log = result.get("detailed_execution_log", [])
        assert len(log) == len(sample_replay_actions), (
            f"Expected {len(sample_replay_actions)} log entries, got {len(log)}"
        )
        for entry in log:
            assert entry.get("replay_source") == "accepted_test", (
                f"Missing replay_source='accepted_test' in entry: {entry}"
            )


# ---------------------------------------------------------------------------
# ReplayEngine: replay failure → fallback to planner
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestReplayEngineFailure:
    """Tests for replay failure handling (AC-HAPPY-6)."""

    async def test_failed_replay_step_routes_to_planner(
        self,
        minimal_state: dict,
        accepted_record: dict,
        sample_replay_actions: list[dict],
    ):
        """
        AC-HAPPY-6: When a replay step fails, replay_failed=True and
        _next_node="planner" (transparent fallback to AI planner).
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch("backend.engine.replay_engine.get_manager") as mock_get_manager,
            patch("backend.engine.replay_engine.dispatch_action") as mock_dispatch,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_manager = MagicMock()
            mock_manager.page = mock_page
            mock_get_manager.return_value = mock_manager

            # First action succeeds, second FAILS
            mock_dispatch.side_effect = [
                {"success": True},
                {"success": False, "error": "Element not found: button[name='New Request']"},
            ]

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["replay_failed"] is True, f"Expected replay_failed=True. Got: {result}"
        assert result["replay_succeeded"] is False
        assert result["_next_node"] == "planner"

    async def test_failed_replay_clears_execution_log_for_clean_ai_run(
        self,
        minimal_state: dict,
        accepted_record: dict,
    ):
        """
        AC-HAPPY-6: On replay failure, the partial execution log is cleared
        so the AI planner starts with a clean slate.
        """
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch("backend.engine.replay_engine.get_manager") as mock_get_manager,
            patch("backend.engine.replay_engine.dispatch_action") as mock_dispatch,
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            mock_page = MagicMock()
            mock_page.is_closed.return_value = False
            mock_manager = MagicMock()
            mock_manager.page = mock_page
            mock_get_manager.return_value = mock_manager
            mock_dispatch.return_value = {"success": False, "error": "Timeout"}

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        # Cleared log allows a clean AI run
        assert result.get("detailed_execution_log", []) == []

    async def test_browser_manager_not_found_causes_fallback(
        self,
        minimal_state: dict,
        accepted_record: dict,
    ):
        """If BrowserManager is None, replay falls back gracefully."""
        from backend.engine.replay_engine import ReplayEngine

        with (
            patch("backend.engine.replay_engine.get_accepted_test_store") as mock_store_factory,
            patch("backend.engine.replay_engine.settings") as mock_settings,
            patch(
                "backend.engine.replay_engine.get_manager",
                return_value=None,  # No manager!
            ),
        ):
            mock_settings.enable_smart_replay = True
            mock_store = MagicMock()
            mock_store.load.return_value = accepted_record
            mock_store_factory.return_value = mock_store

            engine = ReplayEngine(run_id="run-replay-test-001")
            result = await engine.replay(minimal_state)

        assert result["replay_failed"] is True
        assert result["_next_node"] == "planner"


# ---------------------------------------------------------------------------
# route_after_replay_check
# ---------------------------------------------------------------------------


class TestRouteAfterReplayCheck:
    """Tests for the conditional edge routing function."""

    def test_routes_to_reporter_when_replay_succeeded(self, minimal_state: dict):
        """replay_succeeded=True → 'reporter'."""
        from backend.engine.graph import route_after_replay_check

        minimal_state["replay_succeeded"] = True
        assert route_after_replay_check(minimal_state) == "reporter"

    def test_routes_to_planner_when_replay_failed(self, minimal_state: dict):
        """replay_failed=True but replay_succeeded=False → 'planner'."""
        from backend.engine.graph import route_after_replay_check

        minimal_state["replay_succeeded"] = False
        minimal_state["replay_failed"] = True
        assert route_after_replay_check(minimal_state) == "planner"

    def test_routes_to_planner_when_no_replay(self, minimal_state: dict):
        """Both False (no accepted test) → 'planner'."""
        from backend.engine.graph import route_after_replay_check

        minimal_state["replay_succeeded"] = False
        minimal_state["replay_failed"] = False
        assert route_after_replay_check(minimal_state) == "planner"
