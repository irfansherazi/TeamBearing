
import pytest
from pydantic import ValidationError
from backend.engine.schemas import PlannerAction

def test_planner_action_validates_new_strategies():
    """TASK-087: PlannerAction should allow 'window' and 'coordinate_action' strategies."""
    # Test 'window' strategy
    action_window = PlannerAction(
        observation="Page is loaded",
        thought="I need to resize the window",
        action="wait",
        strategy="window",
        reasoning="Testing window strategy",
        kb_acknowledgement="Standard interaction"
    )
    assert action_window.strategy == "window"
    
    # Test 'coordinate_action' strategy
    action_coord = PlannerAction(
        observation="Element not found in DOM",
        thought="Using vision coordinates",
        action="click",
        strategy="coordinate_action",
        reasoning="Testing coordinate_action strategy",
        kb_acknowledgement="Standard interaction"
    )
    assert action_coord.strategy == "coordinate_action"

def test_planner_action_invalid_strategy():
    """Sanity check: random strategy should still fail."""
    with pytest.raises(ValidationError):
        PlannerAction(
            observation="Page is loaded",
            thought="Thinking",
            action="click",
            strategy="invalid_strategy",
            reasoning="Should fail",
            kb_acknowledgement="Standard interaction"
        )
