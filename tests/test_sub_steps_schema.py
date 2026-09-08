
import pytest
from pydantic import ValidationError
from backend.engine.schemas import StructuredACStep, Verification

def test_sub_steps_default_empty_list():
    """
    Ensure sub_steps defaults to an empty list for backward compatibility.
    """
    step_data = {
        "step_id": 1,
        "goal": "Test goal",
        "step_type": "CLICK",
        "target_component": "button",
        "verification": [{"type": "element_visible", "selector_hint": "button"}]
    }
    step = StructuredACStep(**step_data)
    # This should fail if sub_steps is not in the schema
    assert hasattr(step, "sub_steps")
    assert step.sub_steps == []

def test_sub_steps_provided():
    """
    Ensure sub_steps can be provided and parsed.
    """
    step_data = {
        "step_id": 1,
        "goal": "Fill and Submit",
        "step_type": "FILL",
        "target_component": "input",
        "sub_steps": ["Fill the email", "Press Enter"],
        "verification": [{"type": "element_visible", "selector_hint": "success"}]
    }
    step = StructuredACStep(**step_data)
    assert step.sub_steps == ["Fill the email", "Press Enter"]

def test_sub_steps_validation():
    """
    Ensure sub_steps must be a list of strings.
    """
    step_data = {
        "step_id": 1,
        "goal": "Test goal",
        "step_type": "CLICK",
        "target_component": "button",
        "sub_steps": "not a list",
        "verification": []
    }
    with pytest.raises(ValidationError):
        StructuredACStep(**step_data)
