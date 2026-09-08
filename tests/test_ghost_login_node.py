"""
tests/test_ghost_login_node.py
==============================
TDD tests for TASK-102, Phase 2: Ghost Node.

Covers:
  - Importability and existence of ghost_login_node
  - Happy path ghost login (Admin credentials found -> login -> type user -> submit)
  - HITL Admin credentials gate (Credentials missing -> wait -> credentials provided -> resume)
  - Escalate to human takeover when ghost-panel-input is missing
  - State mutations (current_persona, history, step index advancement)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state(**kwargs):
    """Build a minimal VQAState for testing."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-ghost-node",
        jira_ticket_id="QA-102",
        role="account_executive",
        target_url="http://localhost:4200",
        mode="headless",
    )
    state.setdefault("current_persona", "account_executive")
    state.setdefault("persona_switch_history", [])
    state.setdefault("run_memory", {})
    for k, v in kwargs.items():
        state[k] = v
    return state


def _make_test_plan_with_ghost_login(target_user: str = "Kat Morgan Gaines") -> dict:
    """Return a minimal test_plan dict with a GHOST_LOGIN step."""
    return {
        "test_title": "Ghost Login Test",
        "global_preconditions": ["logged_in"],
        "steps": [
            {
                "step_id": 1,
                "goal": f"Ghost In As {target_user}",
                "step_type": "GHOST_LOGIN",
                "target_component": "ghost_panel",
                "preconditions": [],
                "verification": [],
                "fallback_strategy": None,
                "max_actions": 1,
                "target_element_types": [],
                "input_value": None,
                "target_user": target_user,
            }
        ],
    }


# ---------------------------------------------------------------------------
# 1. Module and Existence
# ---------------------------------------------------------------------------


class TestGhostLoginNodeModule:
    """Verify ghost_login_node module exists and exports expected symbols."""

    def test_module_importable(self):
        """backend.engine.ghost_login_node must be importable."""
        import backend.engine.ghost_login_node  # noqa: F401

    def test_ghost_login_node_exists(self):
        """ghost_login_node must be a callable async function."""
        from backend.engine.ghost_login_node import ghost_login_node

        assert callable(ghost_login_node)
        assert asyncio.iscoroutinefunction(ghost_login_node)


# ---------------------------------------------------------------------------
# 2. Happy Path Tests
# ---------------------------------------------------------------------------


class TestGhostLoginNodeHappyPath:
    """AC-HAPPY-3, AC-HAPPY-4, AC-HAPPY-5: Happy path execution."""

    @pytest.mark.asyncio
    async def test_happy_path_ghost_login(self):
        """When Admin credentials exist, login and impersonate target user."""
        from backend.engine.ghost_login_node import ghost_login_node
        from backend.engine.persona_switch_node import set_ghost_credentials

        run_id = "test-run-ghost-happy"
        state = _make_state(
            run_id=run_id,
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_ghost_login("Kat Morgan Gaines"),
        )

        # Cache credentials beforehand
        set_ghost_credentials(run_id, "admin@vpromedia.com", "password123")

        # Mock page locators
        mock_input = AsyncMock()
        mock_input.count = AsyncMock(return_value=1)
        mock_input.fill = AsyncMock()
        mock_input.press = AsyncMock()

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_input)
        mock_page.evaluate = AsyncMock(return_value="jwt-token")
        mock_page.wait_for_url = AsyncMock()

        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = AsyncMock()

        with (
            patch("backend.engine.ghost_login_node.get_manager", return_value=mock_manager),
            patch("backend.engine.ghost_login_node._login_with_ephemeral_creds", AsyncMock(return_value={"success": True})),
            patch("backend.engine.ghost_login_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.ghost_login_node.broadcast_ws_message", AsyncMock()),
        ):
            result = await ghost_login_node(state)

        assert result["_next_node"] == "planner"
        assert result["current_persona"] == "Kat Morgan Gaines"
        assert result["ac_step_index"] == 1
        assert result["structured_step_index"] == 1

        history = result.get("persona_switch_history", [])
        assert len(history) == 1
        entry = history[0]
        assert entry["from"] == "admin"
        assert entry["to"] == "Kat Morgan Gaines"
        assert entry["method"] == "ghost"


# ---------------------------------------------------------------------------
# 3. HITL Credential Gate Tests
# ---------------------------------------------------------------------------


class TestGhostLoginNodeHITL:
    """AC-HAPPY-6: Unknown/missing credentials trigger HITL credential gate."""

    @pytest.mark.asyncio
    async def test_missing_credentials_triggers_hitl(self):
        """When Admin credentials are missing, wait for them via HITL gate."""
        from backend.engine.ghost_login_node import ghost_login_node
        from backend.engine.persona_switch_node import _ghost_creds, set_ghost_credentials

        run_id = "test-run-ghost-hitl"
        state = _make_state(
            run_id=run_id,
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_ghost_login("Kat Morgan Gaines"),
        )

        # Clear credentials first
        _ghost_creds.pop(run_id, None)

        mock_input = AsyncMock()
        mock_input.count = AsyncMock(return_value=1)
        mock_input.fill = AsyncMock()
        mock_input.press = AsyncMock()

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_input)
        mock_page.evaluate = AsyncMock(return_value="jwt-token")
        mock_page.wait_for_url = AsyncMock()

        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = AsyncMock()

        # Submit credentials as a task to unblock
        async def provide_creds():
            await asyncio.sleep(0.1)
            set_ghost_credentials(run_id, "admin@vpromedia.com", "secret")

        asyncio.create_task(provide_creds())

        with (
            patch("backend.engine.ghost_login_node.get_manager", return_value=mock_manager),
            patch("backend.engine.ghost_login_node._login_with_ephemeral_creds", AsyncMock(return_value={"success": True})),
            patch("backend.engine.ghost_login_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.ghost_login_node.broadcast_ws_message", AsyncMock()),
        ):
            result = await ghost_login_node(state)

        assert result["_next_node"] == "planner"
        assert result["current_persona"] == "Kat Morgan Gaines"


# ---------------------------------------------------------------------------
# 4. Error and Escalation Tests
# ---------------------------------------------------------------------------


class TestGhostLoginNodeErrors:
    """AC-ERROR-1: Handle missing panel input with human takeover."""

    @pytest.mark.asyncio
    async def test_ghost_panel_input_missing_escalates(self):
        """If id='ghost-panel-input' is missing, escalate to human takeover."""
        from backend.engine.ghost_login_node import ghost_login_node
        from backend.engine.persona_switch_node import set_ghost_credentials

        run_id = "test-run-ghost-escalate"
        state = _make_state(
            run_id=run_id,
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_ghost_login("Kat Morgan Gaines"),
        )

        # Set credentials
        set_ghost_credentials(run_id, "admin@vpromedia.com", "password")

        # Mock input as missing
        mock_input = AsyncMock()
        mock_input.count = AsyncMock(return_value=0)  # Panel NOT found

        mock_page = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_input)

        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = AsyncMock()

        with (
            patch("backend.engine.ghost_login_node.get_manager", return_value=mock_manager),
            patch("backend.engine.ghost_login_node._login_with_ephemeral_creds", AsyncMock(return_value={"success": True})),
            patch("backend.engine.ghost_login_node.broadcast_ws_message", AsyncMock()),
        ):
            result = await ghost_login_node(state)

        assert result["_next_node"] == "human_takeover"
        assert "not found" in result["last_error"]
