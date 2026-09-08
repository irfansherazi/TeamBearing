import pytest
from backend.engine.schemas import StructuredACStep, Verification

def test_structured_ac_step_wait_ms_default():
    """Verify post_action_wait_ms defaults to 0."""
    step = StructuredACStep(
        step_id=1,
        goal="Test goal",
        step_type="CLICK",
        target_component="button",
        verification=[Verification(type="element_visible", selector_hint="button")]
    )
    # This should fail if the field isn't added yet
    assert hasattr(step, "post_action_wait_ms")
    assert step.post_action_wait_ms == 0

def test_structured_ac_step_wait_ms_explicit():
    """Verify post_action_wait_ms can be set explicitly."""
    step = StructuredACStep(
        step_id=1,
        goal="Test goal",
        step_type="CLICK",
        target_component="button",
        verification=[Verification(type="element_visible", selector_hint="button")],
        post_action_wait_ms=2000
    )
    assert step.post_action_wait_ms == 2000
