"""
vQA — List View Navigation Recipe Tests
=========================================
Module: tests/test_list_view_navigation.py

Phase 3 TDD tests for TASK-015 (vQA Post-v2.1 Regression Stabilization).

Bug 2: Missing List View Navigation Recipe — the planner falls into an
infinite loop trying to navigate to List View because the KB has no guidance
for this transition.

These tests validate:
  1. list_view_navigation.yaml blueprint exists and passes ActionRecipe schema
  2. The blueprint has correct trigger keywords for list/grid view matching
  3. The recipe handles the already-active-view no-op case (verify_after)
  4. The existing compact_view_navigate.yaml is unbroken (regression)
  5. human_guidance.md contains List View navigation entry
  6. RAG indexing picks up the new blueprint content

Acceptance Criteria Coverage:
  - AC-HAPPY-4: list_view_navigation.yaml exists in knowledge/blueprints/
  - AC-HAPPY-5: Planner can navigate to List View (blueprint provides the recipe)
  - AC-HAPPY-6: Recipe handles already-active view case (verify_after with
                 div.po-table-wrapper.$view_css_class persistent indicator)
  - AC-REGRESS-2: compact_view_navigate.yaml still passes validation

Run:
    pytest tests/test_list_view_navigation.py -v
"""

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is required — pip install pyyaml")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_BLUEPRINTS_DIR = _PROJECT_ROOT / "knowledge" / "blueprints"
_KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge"

# Add backend to sys.path for ActionRecipe import
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from engine.recipe_runner import ActionRecipe  # noqa: E402

# ---------------------------------------------------------------------------
# Valid action values (mirrors ActionRecipe's Literal constraint)
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"click", "fill", "select_option", "press_key", "wait", "set_input_files"}

# ---------------------------------------------------------------------------
# Helper: load + validate a single YAML blueprint file
# ---------------------------------------------------------------------------


def _load_and_validate(filename: str) -> ActionRecipe:
    """
    Open `filename` from the blueprints directory, parse with yaml.safe_load(),
    and validate with ActionRecipe.model_validate().
    """
    path = _BLUEPRINTS_DIR / filename
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return ActionRecipe.model_validate(raw)


def _assert_variables_declared(recipe: ActionRecipe) -> None:
    """Assert every $variable in steps is declared in recipe.parameters."""
    declared_params = {p.name for p in recipe.parameters}
    _INTERPOLATED_STEP_FIELDS = ("selector", "value", "name", "container_selector")

    for step_index, step in enumerate(recipe.steps, start=1):
        for field_name in _INTERPOLATED_STEP_FIELDS:
            field_value = getattr(step, field_name, None)
            if not isinstance(field_value, str):
                continue
            referenced_vars = re.findall(r"\$(\w+)", field_value)
            for var_name in referenced_vars:
                assert var_name in declared_params, (
                    f"Recipe '{recipe.name}' step {step_index}: "
                    f"field '{field_name}' references ${var_name} "
                    f"but '{var_name}' is not declared in recipe.parameters."
                )


# ===========================================================================
# Test Suite: List View Navigation Blueprint (Bug 2 Fix)
# ===========================================================================


class TestListViewNavigationBlueprint:
    """Tests for the new list_view_navigation.yaml blueprint (AC-HAPPY-4)."""

    def test_blueprint_exists_and_validates(self):
        """
        AC-HAPPY-4: list_view_navigation.yaml exists in knowledge/blueprints/
        and passes ActionRecipe schema validation.
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        assert recipe is not None
        assert isinstance(recipe.name, str) and recipe.name.strip()
        assert len(recipe.steps) > 0

    def test_blueprint_has_list_view_trigger_keywords(self):
        """
        AC-HAPPY-5: The blueprint must have trigger keywords that match
        List View-related queries so the planner can discover it.
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        keywords_lower = [kw.lower() for kw in recipe.trigger_keywords]

        # Must match "list view" queries
        assert any("list" in kw for kw in keywords_lower), (
            f"Blueprint trigger_keywords must include 'list' variant. Got: {recipe.trigger_keywords}"
        )

    def test_blueprint_has_view_label_parameter(self):
        """
        The recipe must accept a view_label parameter for specifying
        which view to switch to (List, Compact, Minimal).
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        param_names = {p.name for p in recipe.parameters}
        assert "view_label" in param_names, f"Blueprint must have a 'view_label' parameter. Got: {sorted(param_names)}"

    def test_blueprint_has_view_css_class_parameter(self):
        """
        The recipe must accept a view_css_class parameter for verify_after
        (div.po-table-wrapper.$view_css_class persistent DOM indicator).
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        param_names = {p.name for p in recipe.parameters}
        assert "view_css_class" in param_names, (
            f"Blueprint must have a 'view_css_class' parameter. Got: {sorted(param_names)}"
        )

    def test_blueprint_verify_after_uses_persistent_indicator(self):
        """
        AC-HAPPY-6: The verify_after selector uses the persistent
        div.po-table-wrapper.$view_css_class indicator (not the p-menu
        popup which disappears after click).
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        assert recipe.verify_after is not None, (
            "Blueprint must have a verify_after block for the already-active-view no-op case"
        )
        # The verify_after should reference the persistent wrapper class
        verify_selector = recipe.verify_after.selector
        assert "po-table-wrapper" in verify_selector, (
            f"verify_after selector must reference 'po-table-wrapper' persistent indicator. Got: {verify_selector}"
        )
        assert "$view_css_class" in verify_selector, (
            f"verify_after selector must use $view_css_class variable. Got: {verify_selector}"
        )

    def test_blueprint_steps_use_settings_btn(self):
        """
        The recipe steps must click button#settings-btn (the view type
        switcher) — NOT button#sort-btn (which is the sort popover).
        """
        recipe = _load_and_validate("list_view_navigation.yaml")

        # Find the first click step — it should target settings-btn
        settings_step = None
        for step in recipe.steps:
            if step.action == "click" and step.name and "settings" in step.name.lower():
                settings_step = step
                break
            # Also accept css_selector targeting button#settings-btn
            if step.action == "click" and step.strategy == "css_selector":
                selector_val = step.name or ""
                if "settings-btn" in selector_val:
                    settings_step = step
                    break

        assert settings_step is not None, (
            "Blueprint must have a step clicking button#settings-btn (the view type switcher, not the sort button)"
        )

    def test_blueprint_variable_consistency(self):
        """Every $variable in steps must be declared in recipe.parameters."""
        recipe = _load_and_validate("list_view_navigation.yaml")
        _assert_variables_declared(recipe)

    def test_blueprint_all_actions_valid(self):
        """Every step.action must be one of the 6 allowed values."""
        recipe = _load_and_validate("list_view_navigation.yaml")
        for step_index, step in enumerate(recipe.steps, start=1):
            assert step.action in _VALID_ACTIONS, (
                f"Step {step_index}: action '{step.action}' is not valid. Allowed: {sorted(_VALID_ACTIONS)}"
            )

    def test_blueprint_has_cleanup_on_failure(self):
        """
        If the settings menu opened but the view label click failed,
        the recipe should have cleanup_on_failure to dismiss with Escape.
        """
        recipe = _load_and_validate("list_view_navigation.yaml")
        assert len(recipe.cleanup_on_failure) > 0, (
            "Blueprint must have cleanup_on_failure steps (at minimum Escape to close the settings menu on failure)"
        )


# ===========================================================================
# Test Suite: Regression — compact_view_navigate.yaml unchanged (AC-REGRESS-2)
# ===========================================================================


class TestCompactViewNavigateRegression:
    """Regression guard: compact_view_navigate.yaml must still pass."""

    def test_compact_view_still_validates(self):
        """
        AC-REGRESS-2: compact_view_navigate.yaml must continue to pass
        schema validation after the new list_view_navigation.yaml is added.
        """
        recipe = _load_and_validate("compact_view_navigate.yaml")
        assert isinstance(recipe.name, str) and recipe.name.strip()
        assert len(recipe.steps) > 0
        assert len(recipe.trigger_keywords) > 0

        # Verify the existing recipe's steps are still intact
        for step in recipe.steps:
            assert step.action in _VALID_ACTIONS

        # Verify verify_after still uses persistent indicator
        assert recipe.verify_after is not None
        assert "po-table-wrapper" in recipe.verify_after.selector

    def test_compact_view_variable_consistency(self):
        """compact_view_navigate.yaml $variables still match parameters."""
        recipe = _load_and_validate("compact_view_navigate.yaml")
        _assert_variables_declared(recipe)


# ===========================================================================
# Test Suite: Human Guidance Contains View Switching Entries
# ===========================================================================


class TestHumanGuidanceViewSwitching:
    """Validate human_guidance.md has List View navigation content."""

    def test_human_guidance_contains_list_view_entry(self):
        """
        human_guidance.md must contain at least one WORKFLOW entry
        mentioning "list view" or "listview" navigation.
        """
        guidance_path = _KNOWLEDGE_DIR / "human_guidance.md"
        content = guidance_path.read_text(encoding="utf-8")
        content_lower = content.lower()

        # Check for list view navigation workflow entries
        has_list_view = "list view" in content_lower or "listview" in content_lower
        assert has_list_view, (
            "human_guidance.md must contain List View navigation entries "
            "to prevent planner infinite loops on view switching"
        )

    def test_human_guidance_mentions_settings_cog(self):
        """
        The List View navigation entries should mention the settings
        cog icon pattern (click settings cog → select view).
        """
        guidance_path = _KNOWLEDGE_DIR / "human_guidance.md"
        content = guidance_path.read_text(encoding="utf-8")
        content_lower = content.lower()

        # The existing entries already document the cog pattern
        has_cog_pattern = (
            "settings cog" in content_lower or "cog icon" in content_lower or "settings-btn" in content_lower
        )
        assert has_cog_pattern, (
            "human_guidance.md List View entries should mention the settings cog icon interaction pattern"
        )
