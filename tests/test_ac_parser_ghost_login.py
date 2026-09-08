"""
tests/test_ac_parser_ghost_login.py
====================================
TDD tests for TASK-102, Phase 1: AC Parser Detection.

Covers:
  - BDD_NORMALIZER_PROMPT contains ghost-login/impersonation guidance.
  - JSON_COMPILER_PROMPT contains GHOST_LOGIN step type and target_user field details.
  - ac_parser_node parses "Ghost In As [user]" and emits GHOST_LOGIN step.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs):
    """Build a minimal VQAState for testing."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-ghost",
        jira_ticket_id="QA-102",
        role="account_executive",
        target_url="http://localhost:4200",
        mode="headless",
    )
    for k, v in kwargs.items():
        state[k] = v
    return state


def _make_step_json(step_id: int, step_type: str, goal: str, target_user: str | None = None) -> dict:
    """Return a minimal step JSON dict compatible with StructuredACStep."""
    step = {
        "step_id": step_id,
        "goal": goal,
        "step_type": step_type,
        "target_component": "ghost_panel" if step_type == "GHOST_LOGIN" else "page",
        "preconditions": [],
        "verification": [{"type": "element_visible", "selector_hint": "body"}],
        "fallback_strategy": None,
        "max_actions": 8,
        "target_element_types": [],
        "input_value": None,
        "target_user": target_user,
    }
    return step


def _make_test_plan_json(*steps: dict) -> str:
    """Return a minimal TestPlan JSON with the given steps."""
    return json.dumps(
        {
            "test_title": "Ghost Login Support Test",
            "global_preconditions": ["logged_in"],
            "steps": list(steps),
        }
    )


# ---------------------------------------------------------------------------
# 1. Prompt-level tests
# ---------------------------------------------------------------------------


class TestGhostLoginPromptsSupport:
    """Verify BDD_NORMALIZER_PROMPT and JSON_COMPILER_PROMPT have ghost login support."""

    def test_bdd_normalizer_prompt_mentions_ghost_login(self):
        """BDD_NORMALIZER_PROMPT must mention 'Ghost In As' or 'ghost login'."""
        from backend.engine.prompts import BDD_NORMALIZER_PROMPT

        lower = BDD_NORMALIZER_PROMPT.lower()
        assert "ghost in as" in lower or "ghost_login" in lower, (
            "BDD_NORMALIZER_PROMPT must contain ghost-login/impersonation detection guidance."
        )

    def test_json_compiler_prompt_mentions_ghost_login_step_type(self):
        """JSON_COMPILER_PROMPT must include GHOST_LOGIN in its step type guide."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        assert "GHOST_LOGIN" in JSON_COMPILER_PROMPT, (
            "JSON_COMPILER_PROMPT must document GHOST_LOGIN in its step type guide."
        )

    def test_json_compiler_prompt_mentions_target_user_field(self):
        """JSON_COMPILER_PROMPT must explain the target_user field for GHOST_LOGIN steps."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        assert "target_user" in JSON_COMPILER_PROMPT, (
            "JSON_COMPILER_PROMPT must explain target_user field for GHOST_LOGIN steps."
        )


# ---------------------------------------------------------------------------
# 2. AC Parser Node Integration tests
# ---------------------------------------------------------------------------


class TestACParserNodeGhostLogin:
    """Verify that ac_parser_node correctly parses Ghost In As AC text into a GHOST_LOGIN step."""

    @pytest.mark.anyio
    async def test_ac_parser_emits_ghost_login_step(self):
        """
        When Stage 2 returns a GHOST_LOGIN step, the compiled test_plan
        must contain a step with step_type='GHOST_LOGIN' and correct target_user.
        """
        state = _make_state()
        state["jira_ticket"]["acceptance_criteria"] = (
            "Ghost In As Kat Morgan Gaines. Go to root page."
        )
        state["jira_ticket"]["summary"] = "Ghost Login Test"
        state["jira_ticket"]["description"] = "Test description"

        # Mock LLM calls to isolate compiler parsing
        mock_normalizer_resp = MagicMock()
        mock_normalizer_resp.content = "Step 1: Ghost In As Kat Morgan Gaines\nStep 2: Go to root page."

        step_1 = _make_step_json(1, "GHOST_LOGIN", "Ghost In As Kat Morgan Gaines", "Kat Morgan Gaines")
        step_2 = _make_step_json(2, "NAVIGATE", "Go to root page")
        mock_compiler_resp = MagicMock()
        mock_compiler_resp.content = _make_test_plan_json(step_1, step_2)

        # Seed ghost credentials so it does not block pre-flight
        from backend.engine.persona_switch_node import set_ghost_credentials
        set_ghost_credentials(state["run_id"], "admin@vpro.com", "pass")

        # Patch LLM clients
        with patch("backend.engine.ac_parser._get_parser_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.side_effect = [mock_normalizer_resp, mock_compiler_resp]
            mock_get_llm.return_value = mock_llm

            from backend.engine.ac_parser import ac_parser_node
            result_state = await ac_parser_node(state)

            test_plan = result_state.get("test_plan")
            assert test_plan is not None
            assert len(test_plan["steps"]) == 2

            ghost_step = test_plan["steps"][0]
            assert ghost_step["step_type"] == "GHOST_LOGIN"
            assert ghost_step["target_user"] == "Kat Morgan Gaines"
            assert ghost_step["target_component"] == "ghost_panel"

    @pytest.mark.anyio
    async def test_ac_parser_pre_flight_block_and_unblock(self):
        """ac_parser_node must block if GHOST_LOGIN is present and Admin credentials are missing."""
        from backend.engine.persona_switch_node import _ghost_creds, set_ghost_credentials

        state = _make_state()
        state["jira_ticket"]["acceptance_criteria"] = (
            "Ghost In As Kat Morgan Gaines"
        )
        state["jira_ticket"]["summary"] = "Ghost Login Test"

        _ghost_creds.pop(state["run_id"], None)

        mock_normalizer_resp = MagicMock()
        mock_normalizer_resp.content = "Step 1: Ghost In As Kat Morgan Gaines"

        step_1 = _make_step_json(1, "GHOST_LOGIN", "Ghost In As Kat Morgan Gaines", "Kat Morgan Gaines")
        mock_compiler_resp = MagicMock()
        mock_compiler_resp.content = _make_test_plan_json(step_1)

        # Asynchronously submit credentials to unblock the pre-flight gate
        async def provide_creds():
            await asyncio.sleep(0.1)
            set_ghost_credentials(state["run_id"], "admin@vpro.com", "pass")

        import asyncio
        asyncio.create_task(provide_creds())

        with patch("backend.engine.ac_parser._get_parser_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.side_effect = [mock_normalizer_resp, mock_compiler_resp]
            mock_get_llm.return_value = mock_llm

            from backend.engine.ac_parser import ac_parser_node
            result_state = await ac_parser_node(state)

            test_plan = result_state.get("test_plan")
            assert test_plan is not None
            assert test_plan["steps"][0]["step_type"] == "GHOST_LOGIN"

