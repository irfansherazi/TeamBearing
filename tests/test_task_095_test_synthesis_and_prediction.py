"""
tests/test_task_095_test_synthesis_and_prediction.py
=====================================================
Comprehensive tests for TASK-095: LLM compiler, git auto-PR, and predictive state verification.
"""

import os
import json
import pytest
import re
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from backend.kb.test_synthesis_compiler import TestSynthesisCompiler
from backend.engine.verifier import PredictiveVerifier, PredictiveVerificationError
from backend.engine.schemas import PlannerAction


# ============================================================================
# Section 1: TestSynthesisCompiler Tests
# ============================================================================

@pytest.mark.anyio
async def test_compiler_translates_actions_to_typescript():
    """Verify that TestSynthesisCompiler invokes LLM and cleans markdown fences."""
    action_log = [
        {"action": "navigate", "value": "http://test-app.com/login"},
        {"action": "fill", "strategy": "get_by_placeholder", "name": "Email", "value": "test@vpro.com", "state_expectation": "Email field contains 'test@vpro.com'"},
        {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Login", "state_expectation": "URL contains /dashboard"}
    ]

    mock_llm_response = """
```typescript
import { test, expect } from '@playwright/test';

test('synthesis run test_run_123', async ({ page }) => {
  await page.goto('http://test-app.com/login');
  await page.fill('[placeholder="Email"]', 'test@vpro.com');
  await page.click('role=button[name="Login"]');
});
```
"""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=mock_llm_response)

    with patch("backend.kb.test_synthesis_compiler.get_llm", return_value=mock_llm):
        compiler = TestSynthesisCompiler()
        code = compiler.compile_run("test_run_123", action_log)

        assert "import { test, expect } from '@playwright/test';" in code
        assert "await page.goto" in code
        assert "await page.fill" in code
        assert "await page.click" in code
        # Verify markdown fences are stripped
        assert "```typescript" not in code
        assert "```" not in code


def test_compiler_saves_test_to_disk(tmp_path):
    """Verify TestSynthesisCompiler saves TS files to disk."""
    compiler = TestSynthesisCompiler(tests_dir=str(tmp_path))
    code = "console.log('test');"
    test_file_path = compiler.save_test("run_abc", code)

    assert test_file_path.exists()
    assert test_file_path.name == "synthesis_run_run_abc.spec.ts"
    assert test_file_path.read_text() == code


def test_compiler_registers_test_in_json(tmp_path):
    """Verify synthesized tests are appended to the JSON index file."""
    registry_file = tmp_path / "playwright_index.json"
    compiler = TestSynthesisCompiler(registry_file=str(registry_file))

    action_log = [
        {"action": "navigate", "value": "http://test-app.com/login"},
        {"action": "click", "strategy": "get_by_role", "role": "button", "name": "Login", "state_expectation": "Dashboard is visible"}
    ]

    compiler.register_test("run_789", action_log)

    assert registry_file.exists()
    with open(registry_file, "r") as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        assert entry["id"] == "synthesis_run_run_789"
        assert entry["file"] == "tests/synthesis_run_run_789.spec.ts"
        assert entry["steps_count"] == 2
        assert "Dashboard is visible" in entry["step_names"]


def test_compiler_git_automation_and_pr(tmp_path):
    """Verify git branch, commit, and PR subprocesses are triggered with expected arguments."""
    registry_file = tmp_path / "playwright_index.json"
    compiler = TestSynthesisCompiler(registry_file=str(registry_file))
    
    # Mock individual Git operations on compiler
    compiler.git_checkout_branch = MagicMock()
    compiler.git_add_files = MagicMock()
    compiler.git_commit = MagicMock()
    compiler.github_pr_create = MagicMock(return_value="https://github.com/vpro/vqa/pull/123")

    test_file_path = tmp_path / "synthesis_run_run_999.spec.ts"
    test_file_path.write_text("console.log('test');")

    pr_url = compiler.automate_branch_and_pr("run_999", test_file_path)

    assert pr_url == "https://github.com/vpro/vqa/pull/123"
    compiler.git_checkout_branch.assert_called_once()
    assert compiler.git_checkout_branch.call_args[0][0].startswith("synthesis/run-run_999-")
    compiler.git_add_files.assert_called_once()
    compiler.git_commit.assert_called_once()
    compiler.github_pr_create.assert_called_once_with(
        "Synthesized Test: Run run_999",
        "Automatically generated integration test from exploratory execution run run_999."
    )


# ============================================================================
# Section 2: PredictiveVerifier Unit Tests
# ============================================================================

class MockLocator:
    def __init__(self, visible=True):
        self._visible = visible
    async def is_visible(self):
        return self._visible
    @property
    def first(self):
        return self


class MockPage:
    def __init__(self, url="http://test.com", body_content="", element_visibility=None):
        self.url = url
        self._body_content = body_content
        self._element_visibility = element_visibility or {}
        self.wait_for_timeout = AsyncMock()
        
    def get_by_text(self, text, **kwargs):
        visible = self._element_visibility.get(text, True)
        return MockLocator(visible)
        
    def locator(self, selector, **kwargs):
        visible = self._element_visibility.get(selector, True)
        return MockLocator(visible)
        
    async def text_content(self, selector):
        if selector == "body":
            return self._body_content
        return ""


@pytest.mark.anyio
async def test_predictive_verifier_url_check():
    """Verify predictive verifier detects matching/mismatching URLs."""
    # Met expectation
    page = MockPage(url="http://test-app.com/dashboard")
    res = await PredictiveVerifier.verify_expectation(page, "URL contains /dashboard")
    assert res is True

    # Failed expectation
    page_wrong = MockPage(url="http://test-app.com/login")
    res_wrong = await PredictiveVerifier.verify_expectation(page_wrong, "URL contains /dashboard")
    assert res_wrong is False


@pytest.mark.anyio
async def test_predictive_verifier_quoted_text_check():
    """Verify predictive verifier detects text presence/absence in quotes."""
    # Met expectation (element is visible directly)
    page_ok = MockPage(element_visibility={"Create Folder": True})
    res_ok = await PredictiveVerifier.verify_expectation(page_ok, "Dialog 'Create Folder' is visible")
    assert res_ok is True

    # Met expectation (found in body text fallback)
    page_body = MockPage(body_content="Welcome back, Josh!", element_visibility={"Welcome back, Josh!": False})
    res_body = await PredictiveVerifier.verify_expectation(page_body, "Assert text 'Welcome back, Josh!' exists")
    assert res_body is True

    # Mismatch text
    page_missing = MockPage(body_content="No user found", element_visibility={"Create Folder": False})
    res_missing = await PredictiveVerifier.verify_expectation(page_missing, "Dialog 'Create Folder' is visible")
    assert res_missing is False


@pytest.mark.anyio
async def test_predictive_verifier_selector_check():
    """Verify predictive verifier detects CSS selector visibility."""
    # Met selector check
    page_ok = MockPage(element_visibility={".success-banner": True})
    res_ok = await PredictiveVerifier.verify_expectation(page_ok, "Element .success-banner is visible")
    assert res_ok is True

    # Failed selector check
    page_fail = MockPage(element_visibility={".success-banner": False})
    res_fail = await PredictiveVerifier.verify_expectation(page_fail, "Element .success-banner is visible")
    assert res_fail is False


# ============================================================================
# Section 3: Schema and Executor Hook Tests
# ============================================================================

def test_planner_action_schema_supports_state_expectation():
    """Verify Pydantic PlannerAction supports state_expectation field and serialises properly."""
    action = PlannerAction(
        observation="Page loaded",
        thought="I should click login",
        action="click",
        strategy="get_by_role",
        role="button",
        name="Login",
        state_expectation="URL contains /dashboard",
        reasoning="Logging in",
        kb_acknowledgement="No KB rules found for this step."
    )
    
    # Assert deserialisation and field inclusion
    assert action.state_expectation == "URL contains /dashboard"
    
    # Export and verify JSON schema includes it
    json_schema = PlannerAction.model_json_schema()
    assert "state_expectation" in json_schema["properties"]


@pytest.mark.anyio
async def test_executor_hook_fast_fail_on_predictive_mismatch():
    """Verify that a mismatch in state_expectation in _dispatch_action triggers fast-fail."""
    from backend.engine.executor import _dispatch_action

    # Prepare a mock action dict with state_expectation
    action = {
        "action": "click",
        "strategy": "get_by_role",
        "role": "button",
        "name": "Submit",
        "state_expectation": "Element .success-banner is visible"
    }

    # Mock the page and mock verifications
    # Expectation fails because .success-banner is missing
    mock_page = MockPage(url="http://test.com", element_visibility={".success-banner": False})
    
    # Mock locator for the action execution itself so click succeeds
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.first = mock_locator
    mock_page.get_by_role = MagicMock(return_value=mock_locator)

    with (
        patch("backend.engine.executor._resolve_locator", return_value=mock_locator),
        patch("backend.engine.executor._wait_for_stable_dom", new_callable=AsyncMock),
        patch("backend.browser.network_sync.wait_for_spinners_cleared", new_callable=AsyncMock),
        patch("backend.browser.network_sync.wait_for_data_settled", new_callable=AsyncMock)
    ):
        result = await _dispatch_action(page=mock_page, action=action, state={})
        
        # Verify action failed immediately due to PredictiveVerificationError
        assert result["success"] is False
        assert "PredictiveVerificationError" in result["error_message"]
        assert "Predictive verification mismatch: expected 'Element .success-banner is visible'" in result["error_message"]


@pytest.mark.anyio
async def test_executor_hook_success_when_predictive_met():
    """Verify that _dispatch_action succeeds if state_expectation is fully met."""
    from backend.engine.executor import _dispatch_action

    # Prepare a mock action dict with state_expectation
    action = {
        "action": "click",
        "strategy": "get_by_role",
        "role": "button",
        "name": "Submit",
        "state_expectation": "Element .success-banner is visible"
    }

    # Expectation succeeds because .success-banner is visible
    mock_page = MockPage(url="http://test.com", element_visibility={".success-banner": True})
    
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.first = mock_locator
    mock_page.get_by_role = MagicMock(return_value=mock_locator)

    with (
        patch("backend.engine.executor._resolve_locator", return_value=mock_locator),
        patch("backend.engine.executor._wait_for_stable_dom", new_callable=AsyncMock),
        patch("backend.browser.network_sync.wait_for_spinners_cleared", new_callable=AsyncMock),
        patch("backend.browser.network_sync.wait_for_data_settled", new_callable=AsyncMock)
    ):
        result = await _dispatch_action(page=mock_page, action=action, state={})
        
        # Verify action succeeded because predictive expectation was met
        assert result["success"] is True
        assert result["error_message"] is None
