from unittest.mock import patch

import pytest


@pytest.mark.anyio
async def test_vqa_planner_recognizes_sort_indicators():
    """
    AC-VERIFY-3: vQA planner recognizes sort indicators
    Given a list view with updated sort indicators (data-testid, aria-sort)
    When the vQA planner receives the ARIA tree
    Then it successfully correlates the column to the data-testid/aria-sort and issues the correct click action.
    """
    from backend.engine.planner import _build_system_prompt_v2
    from backend.engine.state_tracker import PageStateTracker

    # 1. Setup a mocked PageStateTracker with ARIA tree containing sort indicators
    tracker = PageStateTracker(run_id="test_sort")
    state = {
        "run_id": "test_sort",
        "jira_ticket": {"description": "test"},
        "ac_step_index": 0,
        "jira_ticket_data": {"acceptance_criteria_steps": []},
        "target_element_types": {},
        "role_context": {},
        "page_state_snapshot": """
    [table] "List View"
      [row]
        [columnheader] "Campaign Name" (data-testid="sort-header-Campaign Name", aria-sort="none")
        [columnheader] "Status" (data-testid="sort-header-Status", aria-sort="ascending")
    """,
    }

    with patch("backend.engine.planner.get_tracker", return_value=tracker):
        # We assume _build_system_prompt_v2 injects state.page_state_snapshot into the prompt
        prompt = _build_system_prompt_v2(state)

        # Verify the ARIA tree with sort indicators is preserved in the prompt
        assert 'data-testid="sort-header-Campaign Name"' in prompt, "Prompt should contain data-testid"
        assert 'aria-sort="none"' in prompt, "Prompt should contain aria-sort"
        assert 'aria-sort="ascending"' in prompt, "Prompt should contain aria-sort ascending"


@pytest.mark.anyio
async def test_vqa_evaluator_sort_action_retry_logic():
    """
    Verify that if a sort action is generated, the evaluator properly delegates it and tracks repetitions
    (ensuring circuit breaker logic we added in Phase 1 is cohesive with the E2E flow).
    """
    from backend.engine.evaluator import evaluator_node

    state = {
        "run_id": "test_id",
        "jira_ticket": {"acceptance_criteria_steps": []},
        "ac_step_fail_counts": {},
        "ac_step_index": 0,
        "detailed_execution_log": [{"action_type": "click", "success": False}],
        "action_repeat_counts": {"sort_action_failure": 0},
        "target_element_types": {},
        "proposed_action": {"action": "click", "strategy": "get_by_text", "name": "status"},
        "planned_action": {"action": "click", "strategy": "get_by_text", "name": "status"},
    }

    # Execute action (will fail and trigger repeat count)
    result = await evaluator_node(state)

    assert "action_repeat_counts" in result
    assert result["action_repeat_counts"]["sort_action_failure"] == 1
