"""
vQA — ARIA Tree Pruning Tests
===============================
Module: backend/engine/test_aria_pruning.py

FEAT-025: Tests for multi-stage ARIA tree pruning.
Covers:
  - Viewport pruning (accessibility.py)
  - Semantic pruning (accessibility.py)
  - Step-aware role management (evaluator.py, ac_parser.py)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.browser.accessibility import extract_interactive_elements
from backend.engine.ac_parser import ac_parser_node
from backend.engine.evaluator import evaluator_node
from backend.engine.state import make_initial_state


@pytest.mark.anyio
async def test_extract_interactive_elements_viewport_pruning():
    """Verify elements outside the viewport are flagged correctly."""
    mock_page = AsyncMock()
    # Mock return from JS walk
    mock_elements = [
        {"role": "button", "name": "Visible", "state": "enabled", "isInViewport": True},
        {"role": "button", "name": "Hidden", "state": "enabled", "isInViewport": False},
    ]
    mock_page.evaluate.return_value = mock_elements

    with patch("backend.config.settings") as mock_settings:
        mock_settings.aria_pruning_enabled = True
        mock_settings.viewport_pruning_enabled = True
        mock_settings.semantic_pruning_enabled = False
        mock_settings.always_keep_roles = ["button"]

        # Note: extract_interactive_elements internally passes viewport_pruning=True to JS
        # Our mock return simulates the JS already did the pruning if viewport_pruning was True.
        # But wait, our JS walk in accessibility.py DOES the pruning.
        # So we test if the Python side correctly handles the output.

        elements = await extract_interactive_elements(mock_page)
        assert len(elements) == 2
        assert elements[0]["in_viewport"] == "yes"
        assert elements[1]["in_viewport"] == "no"


@pytest.mark.anyio
async def test_extract_interactive_elements_semantic_pruning():
    """Verify semantic pruning keeps target roles + safety set."""
    mock_page = AsyncMock()
    mock_elements = [
        {"role": "button", "name": "Save", "state": "enabled", "isInViewport": True},
        {"role": "textbox", "name": "Email", "state": "enabled", "isInViewport": True},
        {"role": "combobox", "name": "Status", "state": "enabled", "isInViewport": True},
    ]
    mock_page.evaluate.return_value = mock_elements

    with patch("backend.config.settings") as mock_settings:
        mock_settings.aria_pruning_enabled = True
        mock_settings.viewport_pruning_enabled = False
        mock_settings.semantic_pruning_enabled = True
        mock_settings.always_keep_roles = ["button"]

        # 1. Target = ["textbox"] -> should keep textbox (target) and button (safety)
        elements = await extract_interactive_elements(mock_page, target_element_types=["textbox"])
        roles = [el["role"] for el in elements]
        assert "textbox" in roles
        assert "button" in roles
        assert "combobox" not in roles
        assert len(elements) == 2

        # 2. Target = [] -> should keep everything (no semantic pruning)
        elements = await extract_interactive_elements(mock_page, target_element_types=[])
        assert len(elements) == 3


@pytest.mark.anyio
async def test_evaluator_advances_step_and_updates_roles():
    """Verify evaluator_node updates structured_step_index and target_element_types."""
    test_plan = {
        "steps": [
            {"step_id": 1, "goal": "Step 1", "target_element_types": ["button"], "max_actions": 5},
            {"step_id": 2, "goal": "Step 2", "target_element_types": ["textbox"], "max_actions": 5},
        ]
    }
    state = make_initial_state(
        run_id="test", jira_ticket_id="VC-123", role="account_executive", target_url="http://test.com", mode="headless"
    )
    state["test_plan"] = test_plan
    state["jira_ticket"]["acceptance_criteria_steps"] = ["Step 1", "Step 2"]
    state["ac_step_index"] = 0
    state["structured_step_index"] = 0
    state["target_element_types"] = ["button"]

    # Simulate a successful 'done' action
    state["detailed_execution_log"] = [{"action_type": "done", "success": True, "step_index": 0, "ac_step_index": 0}]
    state["planned_action"] = {"action": "done"}

    with (
        patch("backend.config.settings") as mock_settings,
        patch("backend.engine.evaluator._selector_registry", None),
        patch("backend.engine.evaluator._skill_library", None),
        patch("backend.engine.evaluator._kb", None),
    ):
        mock_settings.auto_escalate_threshold = 0
        mock_settings.enable_deferred_verification = False

        result = await evaluator_node(state)

        assert result["ac_step_index"] == 1
        assert result["structured_step_index"] == 1
        assert result["target_element_types"] == ["textbox"]


@pytest.mark.anyio
async def test_ac_parser_initializes_target_roles():
    """Verify ac_parser_node sets initial target_element_types."""
    # Mock state
    state = make_initial_state(
        run_id="test", jira_ticket_id="VC-123", role="account_executive", target_url="http://test.com", mode="headless"
    )
    state["jira_ticket"]["acceptance_criteria"] = "1. Login\n2. Logout"

    # Mock the internal stages
    mock_plan = MagicMock()
    mock_plan.steps = [
        MagicMock(
            goal="Login",
            target_element_types=["textbox", "button"],
            step_id=1,
            step_type="FILL",
            target_component="login",
            verification=[],
        ),
        MagicMock(
            goal="Logout",
            target_element_types=["link"],
            step_id=2,
            step_type="CLICK",
            target_component="logout",
            verification=[],
        ),
    ]
    mock_plan.model_dump.return_value = {
        "steps": [
            {"goal": "Login", "target_element_types": ["textbox", "button"]},
            {"goal": "Logout", "target_element_types": ["link"]},
        ],
        "test_title": "Test Plan",
    }

    with (
        patch("backend.engine.ac_parser._stage_1_normalize") as mock_stage1,
        patch("backend.engine.ac_parser._stage_2_compile") as mock_stage2,
        patch("backend.engine.ac_parser.score_ac_quality") as mock_score,
        patch("backend.engine.ac_parser.enrich_ac_text", new_callable=AsyncMock) as mock_enrich,
        patch("backend.engine.ac_parser.build_global_context") as mock_ctx,
    ):
        # Setup mocks
        mock_stage1.return_value = "mock BDD"
        mock_stage2.return_value = mock_plan

        mock_score.return_value = MagicMock(overall_score=10, quality_grade="good", to_dict=lambda: {})
        mock_enrich.return_value = MagicMock(enrichment_applied=False, to_dict=lambda: {})
        mock_ctx.return_value = "mock context"

        # Execute ac_parser_node
        result = await ac_parser_node(state)

        assert result["structured_step_index"] == 0
        assert result["target_element_types"] == ["textbox", "button"]
        assert result["test_plan"]["steps"][0]["target_element_types"] == ["textbox", "button"]
