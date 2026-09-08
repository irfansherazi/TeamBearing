"""
tests/test_schemas_persona.py
==============================
RED phase tests for TASK-063, Phase 1: Schema & State.

Tests that the PERSONA_SWITCH step type is correctly added to
StructuredACStep and that target_persona is a valid optional field.
"""

import pytest
from pydantic import ValidationError

from backend.engine.schemas import StructuredACStep, TestPlan

# ---------------------------------------------------------------------------
# AC-ENTRY-1: PERSONA_SWITCH is a valid step_type
# ---------------------------------------------------------------------------


class TestPersonaSwitchStepType:
    """Verify PERSONA_SWITCH is a recognized step_type literal."""

    def test_persona_switch_step_type_accepted(self):
        """PERSONA_SWITCH should be a valid step_type value."""
        step = StructuredACStep(
            step_id=1,
            goal="Switch to persona: Demo Prod dir",
            step_type="PERSONA_SWITCH",
            target_component="auth_context",
            target_persona="Demo Prod dir",
        )
        assert step.step_type == "PERSONA_SWITCH"

    def test_persona_switch_target_persona_stored(self):
        """target_persona should be stored verbatim from construction."""
        step = StructuredACStep(
            step_id=1,
            goal="Switch to persona: Demo Prod dir",
            step_type="PERSONA_SWITCH",
            target_component="auth_context",
            target_persona="Demo Prod dir",
        )
        assert step.target_persona == "Demo Prod dir"

    def test_persona_switch_target_persona_optional(self):
        """target_persona should default to None if not provided."""
        step = StructuredACStep(
            step_id=1,
            goal="Switch to persona: Demo Prod dir",
            step_type="PERSONA_SWITCH",
            target_component="auth_context",
        )
        assert step.target_persona is None

    def test_persona_switch_step_type_in_test_plan(self):
        """TestPlan should accept steps with PERSONA_SWITCH step_type."""
        plan = TestPlan(
            test_title="Multi-persona test",
            steps=[
                StructuredACStep(
                    step_id=1,
                    goal="Login as AE",
                    step_type="NAVIGATE",
                    target_component="login_page",
                ),
                StructuredACStep(
                    step_id=2,
                    goal="Switch to persona: Demo Prod dir",
                    step_type="PERSONA_SWITCH",
                    target_component="auth_context",
                    target_persona="Demo Prod dir",
                ),
                StructuredACStep(
                    step_id=3,
                    goal="Verify dashboard as new persona",
                    step_type="VERIFY_ONLY",
                    target_component="dashboard",
                ),
            ],
        )
        assert len(plan.steps) == 3
        persona_steps = [s for s in plan.steps if s.step_type == "PERSONA_SWITCH"]
        assert len(persona_steps) == 1
        assert persona_steps[0].target_persona == "Demo Prod dir"

    def test_persona_switch_as_yourself_variant(self):
        """'as yourself' persona directive should be accepted as target_persona."""
        step = StructuredACStep(
            step_id=1,
            goal="Switch to persona: yourself",
            step_type="PERSONA_SWITCH",
            target_component="auth_context",
            target_persona="yourself",
        )
        assert step.target_persona == "yourself"

    def test_unknown_step_type_rejected(self):
        """Non-existent step_type values should still be rejected."""
        with pytest.raises(ValidationError):
            StructuredACStep(
                step_id=1,
                goal="Some step",
                step_type="INVALID_STEP_TYPE",
                target_component="somewhere",
            )

    def test_persona_switch_model_dump_includes_target_persona(self):
        """model_dump() should include target_persona for JSON serialization."""
        step = StructuredACStep(
            step_id=1,
            goal="Switch to persona: Demo Prod dir",
            step_type="PERSONA_SWITCH",
            target_component="auth_context",
            target_persona="Demo Prod dir",
        )
        dumped = step.model_dump()
        assert "target_persona" in dumped
        assert dumped["target_persona"] == "Demo Prod dir"

    def test_persona_switch_model_dump_none_for_other_steps(self):
        """target_persona should be None in model_dump for non-PERSONA_SWITCH steps."""
        step = StructuredACStep(
            step_id=1,
            goal="Click Submit",
            step_type="CLICK",
            target_component="submit_button",
        )
        dumped = step.model_dump()
        assert "target_persona" in dumped
        assert dumped["target_persona"] is None

    def test_multiple_persona_switches_in_plan(self):
        """Test plan should support multiple PERSONA_SWITCH steps (AC-HAPPY-4)."""
        plan = TestPlan(
            test_title="Multi-switch test",
            steps=[
                StructuredACStep(
                    step_id=1,
                    goal="Switch to Demo AE",
                    step_type="PERSONA_SWITCH",
                    target_component="auth_context",
                    target_persona="Demo AE",
                ),
                StructuredACStep(
                    step_id=2,
                    goal="Perform action as AE",
                    step_type="CLICK",
                    target_component="new_request_button",
                ),
                StructuredACStep(
                    step_id=3,
                    goal="Switch to Demo Producer",
                    step_type="PERSONA_SWITCH",
                    target_component="auth_context",
                    target_persona="Demo Producer",
                ),
            ],
        )
        persona_steps = [s for s in plan.steps if s.step_type == "PERSONA_SWITCH"]
        assert len(persona_steps) == 2
        assert persona_steps[0].target_persona == "Demo AE"
        assert persona_steps[1].target_persona == "Demo Producer"


# ---------------------------------------------------------------------------
# Phase 1: VQAState fields — current_persona, persona_switch_history, ephemeral_persona_creds
# ---------------------------------------------------------------------------


class TestVQAStatePersonaFields:
    """
    Verify that VQAState contains the three new persona tracking fields:
      - current_persona: str
      - persona_switch_history: list[dict]  (Annotated with operator.add)
      - ephemeral_persona_creds: dict
    """

    def test_vqa_state_has_current_persona_field(self):
        """VQAState must declare current_persona: str."""
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState)
        assert "current_persona" in hints, (
            "VQAState is missing 'current_persona' field. "
            "Add: current_persona: str"
        )

    def test_vqa_state_has_persona_switch_history_field(self):
        """VQAState must declare persona_switch_history as an append-reducer list."""
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState, include_extras=True)
        assert "persona_switch_history" in hints, (
            "VQAState is missing 'persona_switch_history' field. "
            "Add: persona_switch_history: Annotated[list[dict], operator.add]"
        )

    def test_vqa_state_has_ephemeral_persona_creds_field(self):
        """VQAState must declare ephemeral_persona_creds: dict."""
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState)
        assert "ephemeral_persona_creds" in hints, (
            "VQAState is missing 'ephemeral_persona_creds' field. "
            "Add: ephemeral_persona_creds: dict"
        )

    def test_persona_switch_history_is_annotated_with_operator_add(self):
        """persona_switch_history must use operator.add reducer (append semantics)."""
        import operator
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState, include_extras=True)
        persona_history_hint = hints.get("persona_switch_history")
        assert persona_history_hint is not None

        # Annotated types expose __metadata__ with the reducer
        metadata = getattr(persona_history_hint, "__metadata__", None)
        assert metadata is not None, (
            "persona_switch_history should be Annotated[list[dict], operator.add] "
            "but is missing __metadata__. The reducer is required for LangGraph."
        )
        assert operator.add in metadata, (
            "persona_switch_history's Annotated metadata should contain operator.add "
            f"but found: {metadata}"
        )

    def test_ephemeral_persona_creds_is_not_annotated(self):
        """
        ephemeral_persona_creds must NOT use operator.add (it's plain dict).
        This is a security property — the field is never serialized/appended
        to audit logs; it's overwritten in-place.
        """
        import operator
        import typing

        from backend.engine.state import VQAState

        hints = typing.get_type_hints(VQAState, include_extras=True)
        ephemeral_hint = hints.get("ephemeral_persona_creds")
        assert ephemeral_hint is not None

        metadata = getattr(ephemeral_hint, "__metadata__", None)
        # Should NOT have operator.add in metadata (plain dict is OK)
        if metadata is not None:
            assert operator.add not in metadata, (
                "ephemeral_persona_creds should NOT use operator.add — "
                "credentials must not be appended to append-only audit logs."
            )
