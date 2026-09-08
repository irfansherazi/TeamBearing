"""
tests/test_schemas_ghost_login.py
==================================
TDD tests for TASK-102, Phase 1: Schema & State.

Verifies that the GHOST_LOGIN step type is correctly added to
StructuredACStep and that target_user is a valid optional field.
"""


from backend.engine.schemas import StructuredACStep, TestPlan

# ---------------------------------------------------------------------------
# GHOST_LOGIN is a valid step_type
# ---------------------------------------------------------------------------


class TestGhostLoginStepType:
    """Verify GHOST_LOGIN is a recognized step_type literal."""

    def test_ghost_login_step_type_accepted(self):
        """GHOST_LOGIN should be a valid step_type value."""
        step = StructuredACStep(
            step_id=1,
            goal="Ghost In As Kat Morgan Gaines",
            step_type="GHOST_LOGIN",
            target_component="ghost_panel",
            target_user="Kat Morgan Gaines",
        )
        assert step.step_type == "GHOST_LOGIN"

    def test_ghost_login_target_user_stored(self):
        """target_user should be stored verbatim from construction."""
        step = StructuredACStep(
            step_id=1,
            goal="Ghost In As Kat Morgan Gaines",
            step_type="GHOST_LOGIN",
            target_component="ghost_panel",
            target_user="Kat Morgan Gaines",
        )
        assert step.target_user == "Kat Morgan Gaines"

    def test_ghost_login_target_user_optional(self):
        """target_user should default to None if not provided."""
        step = StructuredACStep(
            step_id=1,
            goal="Ghost In As Kat Morgan Gaines",
            step_type="GHOST_LOGIN",
            target_component="ghost_panel",
        )
        assert step.target_user is None

    def test_ghost_login_step_type_in_test_plan(self):
        """TestPlan should accept steps with GHOST_LOGIN step_type."""
        plan = TestPlan(
            test_title="Ghost Login Support Test",
            steps=[
                StructuredACStep(
                    step_id=1,
                    goal="Ghost In As Kat Morgan Gaines",
                    step_type="GHOST_LOGIN",
                    target_component="ghost_panel",
                    target_user="Kat Morgan Gaines",
                ),
            ],
        )
        assert len(plan.steps) == 1
        ghost_steps = [s for s in plan.steps if s.step_type == "GHOST_LOGIN"]
        assert len(ghost_steps) == 1
        assert ghost_steps[0].target_user == "Kat Morgan Gaines"
