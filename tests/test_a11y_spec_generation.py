"""
vQA — Unit Tests for A11y-Augmented Spec Generation
===================================================
Module: tests/test_a11y_spec_generation.py

Verifies that generator_node.py correctly handles a11y_elements in card context,
formats them into the prompt, and passes them to the LLM.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from backend.engine.generator_node import _build_prompt, generate_spec


def test_build_prompt_with_a11y_elements():
    """Verify that _build_prompt integrates a11y-discovered elements when present."""
    card = {
        "ticket_id": "QA-106",
        "summary": "Check Dashboard Button",
        "acceptance_criteria": "Given I am on the dashboard, When I click 'Save', Then changes are saved.",
        "expected_steps": ["Click the save button"],
        "a11y_elements": [
            {"role": "button", "name": "Save Changes", "locator": 'page.getByRole("button", {"name": "Save Changes"})'},
            {"role": "textbox", "name": "Client Name", "locator": 'page.getByRole("textbox", {"name": "Client Name"})'}
        ]
    }
    
    tenant_context = {
        "selectors": {
            "save-btn": {"selector": "button#save", "description": "Save changes button"}
        },
        "helper_files": []
    }
    
    system_prompt, user_prompt = _build_prompt(card, tenant_context)
    
    # Assert that system prompt includes instructions for Discovered Interactive Elements
    assert "Discovered Interactive Elements" in system_prompt
    assert "prioritize using page.getByRole()" in system_prompt
    
    # Assert that user prompt contains the discovered elements block
    assert "Discovered Interactive Elements" in user_prompt
    assert 'Role: button, Name: "Save Changes" => Locator: page.getByRole("button", {"name": "Save Changes"})' in user_prompt
    assert 'Role: textbox, Name: "Client Name" => Locator: page.getByRole("textbox", {"name": "Client Name"})' in user_prompt


def test_build_prompt_without_a11y_elements():
    """Verify that _build_prompt does not include a11y section if elements are missing/empty."""
    card = {
        "ticket_id": "QA-106",
        "summary": "Check Dashboard Button",
        "acceptance_criteria": "Given I am on the dashboard, When I click 'Save', Then changes are saved.",
        "expected_steps": ["Click the save button"]
    }
    
    tenant_context = {
        "selectors": {},
        "helper_files": []
    }
    
    system_prompt, user_prompt = _build_prompt(card, tenant_context)
    
    # The string "Discovered Interactive Elements" should NOT be in user prompt (it's empty)
    assert "Discovered Interactive Elements" not in user_prompt


@pytest.mark.anyio
async def test_generate_spec_with_a11y_integration():
    """Verify that generate_spec passes a11y augmented prompt to the LLM and writes the spec."""
    card = {
        "ticket_id": "QA-106",
        "summary": "Check Dashboard Button",
        "acceptance_criteria": "Given I am on the dashboard, When I click 'Save', Then changes are saved.",
        "expected_steps": ["Click the save button"],
        "a11y_elements": [
            {"role": "button", "name": "Save Changes", "locator": 'page.getByRole("button", {"name": "Save Changes"})'}
        ]
    }
    
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '```typescript\nimport { test } from "@playwright/test";\n```'
    mock_llm.ainvoke.return_value = mock_response
    
    # Mock tenant context and settings/get_llm
    with patch("backend.engine.generator_node._load_tenant_context") as mock_load, \
         patch("backend.llm.get_llm", return_value=mock_llm), \
         patch("pathlib.Path.write_text") as mock_write:
         
        mock_load.return_value = {
            "selectors": {},
            "helper_files": []
        }
        
        result = await generate_spec(card, tenant_id="vpromedia")
        
        # Verify result format
        assert result["status"] == "generated"
        assert result["ticket_id"] == "QA-106"
        
        # Ensure LLM was called
        mock_llm.ainvoke.assert_called_once()
        
        # Verify system/user message were passed with dynamic instructions
        called_args = mock_llm.ainvoke.call_args[0][0]
        system_msg = called_args[0].content
        user_msg = called_args[1].content
        
        assert "Discovered Interactive Elements" in system_msg
        assert "Discovered Interactive Elements" in user_msg


@pytest.mark.anyio
async def test_execute_linear_run_wires_a11y_discovery():
    """Verify that _execute_linear_run triggers a11y tree capture and populates card['a11y_elements']."""
    from backend.api.routes import _execute_linear_run, _run_states
    
    class MockRequest:
        jira_ticket_id = "QA-106"
        role = "production_manager"
        target_url = "https://two-test.vcreative.net/dashboard"
        tenant_id = "vpromedia"
        mode = "headless"
        execution_engine = "linear"

    run_id = "test-a11y-wiring"
    _run_states[run_id] = {
        "status": "queued",
        "state": {},
        "jira_ticket_id": "QA-106",
        "role": "production_manager",
    }

    mock_ticket = {
        "summary": "Summary",
        "acceptance_criteria": "AC text",
        "acceptance_criteria_steps": ["Click button"]
    }

    # Setup Playwright mock structure
    mock_page = AsyncMock()
    mock_context = AsyncMock()
    mock_browser = AsyncMock()
    mock_playwright = AsyncMock()

    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context
    mock_playwright.chromium.launch.return_value = mock_browser

    # Mock a11y discovery utility functions
    mock_snapshot = {"role": "WebArea", "children": []}
    mock_elements = [{"role": "button", "name": "Submit", "locator": 'page.getByRole("button")'}]

    with patch("backend.jira.client.fetch_ticket_context", new_callable=AsyncMock, return_value=mock_ticket), \
         patch("backend.api.routes.run_linear_pipeline", new_callable=AsyncMock) as mock_run_pipe, \
         patch("playwright.async_api.async_playwright") as mock_ap_context_manager, \
         patch("backend.engine.a11y_discovery.capture_a11y_snapshot", new_callable=AsyncMock, return_value=mock_snapshot) as mock_capture, \
         patch("backend.engine.a11y_discovery.prune_and_map_a11y_tree", return_value=mock_elements) as mock_prune:

        # Configure the async context manager for async_playwright
        mock_ap_context_manager.return_value.__aenter__.return_value = mock_playwright

        from backend.engine.linear_bridge import LinearRunResult
        mock_run_pipe.return_value = LinearRunResult(
            status="completed",
            pipeline_status="SUCCESS",
            ticket_id="QA-106",
            elapsed_s=1.2,
        )

        await _execute_linear_run(run_id, MockRequest(), {})

        # Assert that the page went to target_url
        mock_page.goto.assert_called_once_with("https://two-test.vcreative.net/dashboard", timeout=30000)
        
        # Assert utility functions were called
        mock_capture.assert_called_once_with(mock_page)
        mock_prune.assert_called_once_with(mock_snapshot)

        # Assert card passed to pipeline had the elements populated!
        called_args, called_kwargs = mock_run_pipe.call_args
        passed_card = called_kwargs.get("card") or called_args[1]
        assert passed_card["a11y_elements"] == mock_elements

