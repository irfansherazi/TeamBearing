import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_planner_dropdown_registry_eager_load():
    """AC-CODE-4: Make _load_dropdown_registry eager (singleton)."""
    from backend.engine.planner import _load_dropdown_registry

    registry1 = _load_dropdown_registry()
    registry2 = _load_dropdown_registry()
    assert registry1 is registry2, "Registry should be loaded eagerly/singleton"


def test_verifier_multiselect_count_guard():
    """AC-CODE-7: Guard int() cast with try/except ValueError."""
    # We test that passing a non-numeric expected_count does not crash
    import asyncio

    from backend.engine.verifier import _check_single_verification

    class MockPage:
        async def wait_for_timeout(self, *args, **kwargs):
            pass

        def locator(self, *args, **kwargs):
            class MockLocator:
                @property
                def first(self):
                    return self

                async def wait_for(self, *args, **kwargs):
                    pass

                async def count(self):
                    return 0

                def locator(self, *args, **kwargs):
                    return self

                async def inner_text(self):
                    return ""

            return MockLocator()

    # Create dummy VQAState context manually or use run_id
    v = {"type": "multiselect_count", "selector_hint": "div", "expected_count": "invalid"}
    coro = _check_single_verification(MockPage(), v, "run123")
    result = asyncio.run(coro)
    # Shouldn't crash, should return correctly
    assert result is not None


def test_evaluator_skip_step_mirror():
    """AC-CODE-6: Mirror full state-reset block in the skip-step branch."""
    import asyncio

    from backend.engine.evaluator import evaluator_node

    # Setup a state where step_iterations_used >= step_budget
    state = {
        "run_id": "test1",
        "detailed_execution_log": [{"success": True, "action_type": "click"}],
        "jira_ticket": {"acceptance_criteria_steps": ["step1", "step2", "step3"]},
        "ac_step_index": 0,
        "ac_step_iteration_budget": 5,
        "ac_step_iterations_used": 5,  # Exceeded budget
    }

    result = asyncio.run(evaluator_node(state))
    assert result["_next_node"] == "planner"
    assert result["ac_step_index"] == 1
    # Check that these fields are present in the reset block
    assert "target_element_types" in result
    assert "ac_step_fail_counts" in result
    assert "current_ac_step_action_count" in result
    assert "verifier_not_yet_count" in result
    assert "action_history_buffer" in result
