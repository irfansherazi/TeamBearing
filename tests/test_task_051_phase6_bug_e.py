"""
TASK-051 Phase 6 — Bug E: Strict Mode aka get_by_role Hint Injection
======================================================================

Tests for extracting the `aka get_by_role(...)` hint from strict mode
violation error messages and injecting it into the planner critique.

Bug E: When Playwright strict mode violations include the hint text
`aka get_by_role("link", name="Campaigns")`, this hint is NOT currently
extracted and provided to the planner. As a result, the planner continues
to use `get_by_text("Campaigns")` instead of the more precise role-based
locator that Playwright itself recommends.

Fix: In evaluator.py, add a function `_extract_aka_hint(error_msg)` that
parses the error message for `aka get_by_role(...)` patterns and returns
a CORRECTION directive string. This directive is prepended to the
`agent_critique` in the normal failure retry path.

Tests:
  - test_strict_mode_hint_extracted_to_critique: critique contains extracted hint
  - test_strict_mode_no_hint_when_no_aka: critique unchanged when no 'aka' in error
  - test_extract_aka_hint_parses_role_and_name: extracted hint format is correct
  - test_extract_aka_hint_returns_none_without_match: returns None for non-strict errors

Run: python3 -m pytest tests/test_task_051_phase6_bug_e.py -v
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: _extract_aka_hint function (pure function tests)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractAkaHint:
    """Unit tests for the _extract_aka_hint helper function."""

    def test_extract_aka_hint_is_importable(self):
        """_extract_aka_hint must be importable from evaluator."""
        from backend.engine.evaluator import _extract_aka_hint

        assert callable(_extract_aka_hint)

    def test_extract_aka_hint_returns_none_without_match(self):
        """Returns None when error message has no 'aka get_by_role' pattern."""
        from backend.engine.evaluator import _extract_aka_hint

        result = _extract_aka_hint("Timeout 15000ms exceeded.")
        assert result is None, f"Expected None, got {result!r}"

    def test_extract_aka_hint_returns_none_for_empty(self):
        """Returns None for empty error message."""
        from backend.engine.evaluator import _extract_aka_hint

        result = _extract_aka_hint("")
        assert result is None

    def test_extract_aka_hint_parses_link_role(self):
        """
        Extracts 'aka get_by_role(\"link\", name=\"Campaigns\")' from a strict
        mode violation and returns a CORRECTION directive.
        """
        from backend.engine.evaluator import _extract_aka_hint

        # Real Playwright error message format
        error = (
            'locator.click: strict mode violation: locator("text=Campaigns") resolved to 3 elements:\n'
            '    1) <a href="/campaigns">Campaigns</a> aka get_by_role("link", name="Campaigns")\n'
            "    2) <span>Campaigns label</span>"
        )
        result = _extract_aka_hint(error)
        assert result is not None, "Expected a CORRECTION hint, got None"
        assert "get_by_role" in result, f"Expected 'get_by_role' in hint: {result!r}"
        assert "CORRECTION" in result.upper() or "Use" in result, f"Expected correction phrasing in hint: {result!r}"

    def test_extract_aka_hint_parses_button_role(self):
        """Handles get_by_role('button', ...) in the aka hint."""
        from backend.engine.evaluator import _extract_aka_hint

        error = (
            "strict mode violation: text=Submit matched 2 elements\n"
            '1) <button>Submit</button> aka get_by_role("button", name="Submit")'
        )
        result = _extract_aka_hint(error)
        assert result is not None
        assert "get_by_role" in result

    def test_extract_aka_hint_first_match_only(self):
        """When multiple aka hints present, extracts first match only."""
        from backend.engine.evaluator import _extract_aka_hint

        error = (
            "strict mode violation: matched 3 elements\n"
            '1) <a>Home</a> aka get_by_role("link", name="Home")\n'
            '2) <a>Home</a> aka get_by_role("link", name="Home Page")'
        )
        result = _extract_aka_hint(error)
        # Should extract the first match
        assert result is not None
        assert "Home" in result  # First match

    def test_extract_aka_hint_single_quotes_in_error(self):
        """Handles single-quoted role names in error messages."""
        from backend.engine.evaluator import _extract_aka_hint

        error = "strict mode violation ... aka get_by_role('link', name='Campaigns')"
        result = _extract_aka_hint(error)
        assert result is not None
        assert "get_by_role" in result


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Integration — critique includes the hint for strict mode failures
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluatorStrictModeHintInjection:
    """Integration tests: evaluator critique includes aka hint for strict mode."""

    def _make_state_for_strict_mode_failure(self, error_msg: str, planned_name: str = "Campaigns") -> dict:
        """Create a state dict that simulates a strict mode failure."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="test-bug-e",
            jira_ticket_id="QA-BUGE",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )
        state["jira_ticket"]["acceptance_criteria_steps"] = ["Navigate to Campaigns"]
        state["detailed_execution_log"] = [
            {
                "step_index": 1,
                "ac_step_index": 0,
                "timestamp": "2026-05-22T10:00:00Z",
                "action_type": "click",
                "action_payload": {
                    "action": "click",
                    "strategy": "get_by_text",
                    "name": planned_name,
                },
                "locator_strategy": "get_by_text",
                "locator_value": f"get_by_text('{planned_name}')",
                "data_input": None,
                "screenshot_url": "",
                "accessibility_tree_snippet": "",
                "success": False,
                "error_message": error_msg,
                "self_heal_attempt": 0,
                "llm_reasoning": "Trying to click navigation link",
                "llm_observation": "",
                "llm_thought": "",
            }
        ]
        state["planned_action"] = {
            "action": "click",
            "strategy": "get_by_text",
            "name": planned_name,
        }
        # Bug E: recovery_router reads state["last_error"] to find the aka hint
        state["last_error"] = error_msg
        return state

    def test_strict_mode_hint_extracted_to_critique(self):
        """
        AC-HAPPY-6 Bug E: When strict mode violation error contains
        'aka get_by_role(\"link\", name=\"Campaigns\")', the evaluator's
        agent_critique for the retry should include a CORRECTION directive
        referencing get_by_role.
        """
        import asyncio

        from backend.engine.evaluator import evaluator_node

        error_with_hint = (
            "locator.click: strict mode violation: locator(\"get_by_text('Campaigns')\") "
            "resolved to 3 elements:\n"
            '    1) <a href="/campaigns">Campaigns</a> '
            'aka get_by_role("link", name="Campaigns")\n'
            "    2) <span class='breadcrumb'>Campaigns</span>\n"
            "    3) <div class='nav-label'>Campaigns</div>"
        )
        state = self._make_state_for_strict_mode_failure(error_with_hint)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(evaluator_node(state))

        # Should route to planner (not yet at threshold)
        assert result.get("_next_node") == "planner", f"Expected planner routing, got {result.get('_next_node')!r}"

        critique = result.get("agent_critique", "")
        assert "get_by_role" in critique, f"Expected 'get_by_role' in agent_critique, but got:\n{critique[:300]}"

    def test_strict_mode_no_hint_when_no_aka(self):
        """
        When strict mode violation error does NOT contain 'aka get_by_role',
        the critique should NOT include a CORRECTION directive for get_by_role.
        Normal critique content is unaffected.
        """
        import asyncio

        from backend.engine.evaluator import evaluator_node

        error_without_hint = (
            'locator.click: strict mode violation: locator("text=Submit") '
            "resolved to 2 elements:\n"
            "    1) <button type='submit'>Submit</button>\n"
            "    2) <input type='submit' value='Submit' />"
        )
        state = self._make_state_for_strict_mode_failure(error_without_hint, planned_name="Submit")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(evaluator_node(state))

        assert result.get("_next_node") == "planner", f"Expected planner routing, got {result.get('_next_node')!r}"
        # The critique should still mention the locator failure, not crash
        critique = result.get("agent_critique", "")
        assert critique, "agent_critique should be non-empty"
        # The constraint: if no 'aka' in error, don't hallucinate get_by_role
        # The critique may naturally mention get_by_role as a suggestion,
        # but must not claim "CORRECTION: Use get_by_role..." as from Playwright.
        assert "CORRECTION: Use get_by_role" not in critique, (
            "Should not inject a CORRECTION when no 'aka' hint is present in the error"
        )
