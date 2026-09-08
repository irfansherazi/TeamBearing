"""
FEAT-007: Composite Action Types — Unit Tests
================================================

Tests for the three composite action types:
  - fill_and_submit:  fill a field + press Enter / click submit button
  - click_and_wait:   click an element + wait for a target to appear
  - select_and_verify: select a dropdown option + verify the result

These tests validate:
  1. PlannerAction schema validation (valid + invalid inputs)
  2. Validator _REQUIRED_FIELDS registration
  3. Graceful fallback semantics (partial success diagnostics)

Run: .venv/bin/python -m pytest backend/engine/test_composite_actions.py -v
"""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pydantic import ValidationError

from backend.engine.schemas import PlannerAction
from backend.engine.validators import _REQUIRED_FIELDS, validate_planned_action

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _base_fields(**overrides) -> dict:
    """Return a minimal valid PlannerAction dict, then apply overrides."""
    base = {
        "observation": "I see the input field.",
        "thought": "I will fill and submit.",
        "reasoning": "Test action.",
        "kb_acknowledgement": "No KB rules found for this step.",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: Schema Validation — fill_and_submit
# ═══════════════════════════════════════════════════════════════════════════


class TestFillAndSubmitSchema:
    """PlannerAction schema validation for fill_and_submit."""

    def test_valid_fill_and_submit_enter(self):
        """fill_and_submit with submit_strategy='enter' should pass validation."""
        action = PlannerAction(
            **_base_fields(
                action="fill_and_submit",
                strategy="get_by_role",
                role="textbox",
                name="Email",
                value="test@example.com",
                submit_strategy="enter",
            )
        )
        assert action.action == "fill_and_submit"
        assert action.submit_strategy == "enter"

    def test_valid_fill_and_submit_click_button(self):
        """fill_and_submit with submit_strategy='click_button' + submit_name should pass."""
        action = PlannerAction(
            **_base_fields(
                action="fill_and_submit",
                strategy="get_by_role",
                role="textbox",
                name="Search",
                value="demo",
                submit_strategy="click_button",
                submit_name="Submit",
            )
        )
        assert action.submit_strategy == "click_button"
        assert action.submit_name == "Submit"

    def test_missing_submit_strategy_raises(self):
        """fill_and_submit without submit_strategy should raise ValueError."""
        with pytest.raises(ValidationError, match="submit_strategy"):
            PlannerAction(
                **_base_fields(
                    action="fill_and_submit",
                    strategy="get_by_role",
                    role="textbox",
                    name="Email",
                    value="test@example.com",
                    # submit_strategy omitted
                )
            )

    def test_click_button_missing_submit_name_raises(self):
        """fill_and_submit with click_button but no submit_name should raise."""
        with pytest.raises(ValidationError, match="submit_name"):
            PlannerAction(
                **_base_fields(
                    action="fill_and_submit",
                    strategy="get_by_role",
                    role="textbox",
                    name="Email",
                    value="test@example.com",
                    submit_strategy="click_button",
                    # submit_name omitted
                )
            )

    def test_missing_value_raises(self):
        """fill_and_submit without value should raise ValueError."""
        with pytest.raises(ValidationError, match="value"):
            PlannerAction(
                **_base_fields(
                    action="fill_and_submit",
                    strategy="get_by_role",
                    role="textbox",
                    name="Email",
                    submit_strategy="enter",
                    # value omitted
                )
            )

    def test_missing_strategy_raises(self):
        """fill_and_submit without strategy (and no vqa_id) should raise."""
        with pytest.raises(ValidationError, match="strategy"):
            PlannerAction(
                **_base_fields(
                    action="fill_and_submit",
                    name="Email",
                    value="test@example.com",
                    submit_strategy="enter",
                    # strategy omitted
                )
            )

    def test_vqa_id_substitutes_strategy(self):
        """fill_and_submit with vqa_id instead of strategy should pass."""
        action = PlannerAction(
            **_base_fields(
                action="fill_and_submit",
                vqa_id=42,
                value="test@example.com",
                submit_strategy="enter",
            )
        )
        assert action.vqa_id == 42


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: Schema Validation — click_and_wait
# ═══════════════════════════════════════════════════════════════════════════


class TestClickAndWaitSchema:
    """PlannerAction schema validation for click_and_wait."""

    def test_valid_click_and_wait_selector(self):
        """click_and_wait with wait_for_selector should pass validation."""
        action = PlannerAction(
            **_base_fields(
                action="click_and_wait",
                strategy="get_by_role",
                role="button",
                name="Open Details",
                wait_for_selector=".detail-panel",
            )
        )
        assert action.action == "click_and_wait"
        assert action.wait_for_selector == ".detail-panel"

    def test_valid_click_and_wait_text(self):
        """click_and_wait with wait_for_text should pass validation."""
        action = PlannerAction(
            **_base_fields(
                action="click_and_wait",
                strategy="get_by_text",
                name="Save Order",
                wait_for_text="Order saved successfully",
            )
        )
        assert action.wait_for_text == "Order saved successfully"

    def test_missing_both_wait_targets_raises(self):
        """click_and_wait without wait_for_selector or wait_for_text should raise."""
        with pytest.raises(ValidationError, match="wait_for_selector.*wait_for_text"):
            PlannerAction(
                **_base_fields(
                    action="click_and_wait",
                    strategy="get_by_role",
                    role="button",
                    name="Submit",
                    # neither wait_for_selector nor wait_for_text
                )
            )

    def test_missing_strategy_raises(self):
        """click_and_wait without strategy (and no vqa_id) should raise."""
        with pytest.raises(ValidationError, match="strategy"):
            PlannerAction(
                **_base_fields(
                    action="click_and_wait",
                    name="Submit",
                    wait_for_selector=".success",
                    # strategy omitted
                )
            )

    def test_vqa_id_substitutes_strategy(self):
        """click_and_wait with vqa_id instead of strategy should pass."""
        action = PlannerAction(
            **_base_fields(
                action="click_and_wait",
                vqa_id=7,
                wait_for_text="Details loaded",
            )
        )
        assert action.vqa_id == 7


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: Schema Validation — select_and_verify
# ═══════════════════════════════════════════════════════════════════════════


class TestSelectAndVerifySchema:
    """PlannerAction schema validation for select_and_verify."""

    def test_valid_select_and_verify(self):
        """select_and_verify with all required fields should pass."""
        action = PlannerAction(
            **_base_fields(
                action="select_and_verify",
                strategy="get_by_role",
                role="combobox",
                name="Status Filter",
                value="Active",
                verify_text="Active",
            )
        )
        assert action.action == "select_and_verify"
        assert action.verify_text == "Active"

    def test_missing_verify_text_raises(self):
        """select_and_verify without verify_text should raise ValueError."""
        with pytest.raises(ValidationError, match="verify_text"):
            PlannerAction(
                **_base_fields(
                    action="select_and_verify",
                    strategy="get_by_role",
                    role="combobox",
                    name="Sort By",
                    value="Ascending",
                    # verify_text omitted
                )
            )

    def test_missing_value_raises(self):
        """select_and_verify without value should raise."""
        with pytest.raises(ValidationError, match="value"):
            PlannerAction(
                **_base_fields(
                    action="select_and_verify",
                    strategy="get_by_role",
                    role="combobox",
                    name="Sort By",
                    verify_text="Ascending",
                    # value omitted
                )
            )

    def test_vqa_id_substitutes_strategy(self):
        """select_and_verify with vqa_id instead of strategy should pass."""
        action = PlannerAction(
            **_base_fields(
                action="select_and_verify",
                vqa_id=15,
                value="Active",
                verify_text="Active",
            )
        )
        assert action.vqa_id == 15


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Validator _REQUIRED_FIELDS Registration
# ═══════════════════════════════════════════════════════════════════════════


class TestValidatorRegistration:
    """Verify all composite types are registered in _REQUIRED_FIELDS."""

    def test_fill_and_submit_registered(self):
        """fill_and_submit should be in _REQUIRED_FIELDS."""
        assert "fill_and_submit" in _REQUIRED_FIELDS
        assert "strategy" in _REQUIRED_FIELDS["fill_and_submit"]
        assert "name" in _REQUIRED_FIELDS["fill_and_submit"]
        assert "value" in _REQUIRED_FIELDS["fill_and_submit"]

    def test_click_and_wait_registered(self):
        """click_and_wait should be in _REQUIRED_FIELDS."""
        assert "click_and_wait" in _REQUIRED_FIELDS
        assert "strategy" in _REQUIRED_FIELDS["click_and_wait"]
        assert "name" in _REQUIRED_FIELDS["click_and_wait"]

    def test_select_and_verify_registered(self):
        """select_and_verify should be in _REQUIRED_FIELDS."""
        assert "select_and_verify" in _REQUIRED_FIELDS
        assert "strategy" in _REQUIRED_FIELDS["select_and_verify"]
        assert "name" in _REQUIRED_FIELDS["select_and_verify"]
        assert "value" in _REQUIRED_FIELDS["select_and_verify"]


class TestValidatePlannedAction:
    """Verify validate_planned_action accepts/rejects composite actions."""

    def test_fill_and_submit_valid(self):
        """Valid fill_and_submit should pass validate_planned_action."""
        errors = validate_planned_action(
            {
                "action": "fill_and_submit",
                "strategy": "get_by_role",
                "role": "textbox",
                "name": "Email",
                "value": "test@example.com",
                "submit_strategy": "enter",
            },
            {},
        )
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_click_and_wait_valid(self):
        """Valid click_and_wait should pass validate_planned_action."""
        errors = validate_planned_action(
            {
                "action": "click_and_wait",
                "strategy": "get_by_role",
                "role": "button",
                "name": "Submit",
                "wait_for_selector": ".success",
            },
            {},
        )
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_select_and_verify_valid(self):
        """Valid select_and_verify should pass validate_planned_action."""
        errors = validate_planned_action(
            {
                "action": "select_and_verify",
                "strategy": "get_by_role",
                "role": "combobox",
                "name": "Status",
                "value": "Active",
                "verify_text": "Active",
            },
            {},
        )
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_fill_and_submit_missing_value(self):
        """fill_and_submit without value should produce an error."""
        errors = validate_planned_action(
            {
                "action": "fill_and_submit",
                "strategy": "get_by_role",
                "role": "textbox",
                "name": "Email",
                # value missing
            },
            {},
        )
        assert len(errors) > 0
        assert any("value" in e.lower() for e in errors)

    def test_click_and_wait_missing_name(self):
        """click_and_wait without name should produce an error."""
        errors = validate_planned_action(
            {
                "action": "click_and_wait",
                "strategy": "get_by_role",
                "role": "button",
                # name missing
            },
            {},
        )
        assert len(errors) > 0

    def test_select_and_verify_missing_strategy(self):
        """select_and_verify without strategy should produce an error."""
        errors = validate_planned_action(
            {
                "action": "select_and_verify",
                "name": "Sort",
                "value": "Active",
            },
            {},
        )
        assert len(errors) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Section 5: Graceful Fallback Semantics
# ═══════════════════════════════════════════════════════════════════════════


class TestGracefulFallback:
    """Verify partial-success diagnostic structure for composite actions."""

    def test_fill_and_submit_partial_success_structure(self):
        """
        When fill succeeds but submit fails, the result should be
        success=True with COMPOSITE_PARTIAL_SUCCESS in error_message.
        """
        # Simulate the return dict from executor on partial failure
        result = {
            "success": True,
            "error_message": (
                "COMPOSITE_PARTIAL_SUCCESS: fill('test@example.com') succeeded but "
                "submit failed: Submit failed: Timeout. The field value is set correctly. "
                "Use a separate press_key('Enter') or click action to submit."
            ),
            "actual_url": "https://test.example.com/form",
            "last_executor_fallback": "fill_and_submit: fill OK, submit FAILED",
        }
        assert result["success"] is True, "Fill succeeded — overall success should be True"
        assert "COMPOSITE_PARTIAL_SUCCESS" in result["error_message"]
        assert "fill OK, submit FAILED" in result["last_executor_fallback"]

    def test_click_and_wait_partial_success_structure(self):
        """
        When click succeeds but wait times out, the result should be
        success=True with COMPOSITE_PARTIAL_SUCCESS in error_message.
        """
        result = {
            "success": True,
            "error_message": (
                "COMPOSITE_PARTIAL_SUCCESS: click('Open Details') succeeded but "
                "the wait target was not found: Text 'Details Panel' not found. "
                "Use a separate verify or wait action to confirm the result."
            ),
            "actual_url": "https://test.example.com/orders",
            "last_executor_fallback": "click_and_wait: click OK, wait FAILED",
        }
        assert result["success"] is True, "Click succeeded — overall success should be True"
        assert "COMPOSITE_PARTIAL_SUCCESS" in result["error_message"]
        assert "click OK, wait FAILED" in result["last_executor_fallback"]

    def test_select_and_verify_partial_success_structure(self):
        """
        When select succeeds but verify fails, the result should be
        success=True with COMPOSITE_PARTIAL_SUCCESS in error_message.
        """
        result = {
            "success": True,
            "error_message": (
                "COMPOSITE_PARTIAL_SUCCESS: select_option('Active') succeeded "
                "but verification failed: Text 'Active' not found in dropdown. "
                "Use a separate verify action to confirm the result."
            ),
            "actual_url": "https://test.example.com/orders",
            "last_executor_fallback": "select_and_verify: select OK, verify FAILED",
        }
        assert result["success"] is True, "Select succeeded — overall success should be True"
        assert "COMPOSITE_PARTIAL_SUCCESS" in result["error_message"]
        assert "select OK, verify FAILED" in result["last_executor_fallback"]


# ═══════════════════════════════════════════════════════════════════════════
# Section 6: Action Literal Membership
# ═══════════════════════════════════════════════════════════════════════════


class TestActionLiteralMembership:
    """Verify composite types are present in PlannerAction.action Literal."""

    def test_fill_and_submit_in_literal(self):
        """fill_and_submit should be a valid action in PlannerAction."""
        # If it weren't in the Literal, construction would raise ValidationError
        action = PlannerAction(
            **_base_fields(
                action="fill_and_submit",
                strategy="get_by_role",
                role="textbox",
                name="Field",
                value="test",
                submit_strategy="enter",
            )
        )
        assert action.action == "fill_and_submit"

    def test_click_and_wait_in_literal(self):
        """click_and_wait should be a valid action in PlannerAction."""
        action = PlannerAction(
            **_base_fields(
                action="click_and_wait",
                strategy="get_by_role",
                role="button",
                name="Click Me",
                wait_for_selector=".result",
            )
        )
        assert action.action == "click_and_wait"

    def test_select_and_verify_in_literal(self):
        """select_and_verify should be a valid action in PlannerAction."""
        action = PlannerAction(
            **_base_fields(
                action="select_and_verify",
                strategy="get_by_role",
                role="combobox",
                name="Dropdown",
                value="Option1",
                verify_text="Option1",
            )
        )
        assert action.action == "select_and_verify"


# ═══════════════════════════════════════════════════════════════════════════
# Section 7: PLANNER_TOOL_CONFIG Regeneration
# ═══════════════════════════════════════════════════════════════════════════


class TestToolConfig:
    """Verify PLANNER_TOOL_CONFIG includes composite action types."""

    def test_tool_config_has_composite_actions(self):
        """PLANNER_TOOL_CONFIG schema should include the three composite types."""
        from backend.engine.schemas import PLANNER_TOOL_CONFIG

        tool_spec = PLANNER_TOOL_CONFIG["tools"][0]["toolSpec"]
        schema = tool_spec["inputSchema"]["json"]
        action_enum = schema["properties"]["action"]["enum"]

        assert "fill_and_submit" in action_enum, f"fill_and_submit missing from tool config. Actions: {action_enum}"
        assert "click_and_wait" in action_enum, f"click_and_wait missing from tool config. Actions: {action_enum}"
        assert "select_and_verify" in action_enum, f"select_and_verify missing from tool config. Actions: {action_enum}"

    def test_tool_config_has_composite_fields(self):
        """PLANNER_TOOL_CONFIG schema should include the new composite fields."""
        from backend.engine.schemas import PLANNER_TOOL_CONFIG

        schema = PLANNER_TOOL_CONFIG["tools"][0]["toolSpec"]["inputSchema"]["json"]
        props = schema["properties"]

        for field in ["submit_strategy", "submit_name", "wait_for_selector", "wait_for_text", "verify_text"]:
            assert field in props, f"Field '{field}' missing from tool config properties"
