from backend.engine.planner import _build_failure_diary, _dispatch_build_system_prompt
from backend.engine.state import VQAState


def test_failure_diary_formatting():
    state = VQAState(
        run_id="test_run",
        ac_step_failure_diary=[
            {
                "attempt": 1,
                "action": "click",
                "locator": "get_by_role:button:Submit",
                "error": "STRICT_MODE (2 matches)",
                "suggestion": "Be more specific",
            },
            {
                "attempt": 2,
                "action": "click",
                "locator": "get_by_text:Submit",
                "error": "TIMEOUT",
                "suggestion": "Element not visible",
            },
        ],
    )
    diary_str = _build_failure_diary(state)
    assert "⚠ FAILURE DIARY" in diary_str
    assert "Attempt 1" in diary_str
    assert "get_by_role:button:Submit" in diary_str
    assert "STRICT_MODE" in diary_str
    assert "Attempt 2" in diary_str
    assert "TIMEOUT" in diary_str


def test_long_running_session_retains_role_context():
    # Construct a state with a very long execution log and history
    # to simulate a deep session.
    state = VQAState(
        run_id="test_run",
        role_context={"role_key": "account_executive", "role_name": "Account Executive"},
        jira_ticket={
            "ticket_id": "TEST-1",
            "summary": "Long test",
            "acceptance_criteria_steps": ["Step 1", "Step 2", "Step 3"],
        },
        ac_step_index=2,
        detailed_execution_log=[{"step_index": i, "action_type": "click", "success": True} for i in range(50)],
        ac_step_failure_diary=[
            {"attempt": i, "action": "click", "locator": "test", "error": "test"} for i in range(10)
        ],
        current_screenshot_b64="b64",
        current_accessibility_tree="tree",
        target_url="http://test",
        current_page_url="http://test/page",
        planner_iteration=10,
        test_plan={"steps": [{"action": "test", "target": "test"} for _ in range(3)]},
        structured_step_index=2,
    )

    system_prompt = _dispatch_build_system_prompt(state)

    # Verify that role context is preserved
    assert "ROLE CONSTRAINTS" in system_prompt

    # Verify failure diary is present
    assert "⚠ FAILURE DIARY" in system_prompt
