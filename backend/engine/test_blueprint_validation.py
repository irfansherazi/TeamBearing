"""
vQA — Blueprint YAML Validation Tests
=======================================
Module: backend/engine/test_blueprint_validation.py

Phase 2 TDD guard tests for TASK-001 (KB Refactor & Coverage Expansion).

These 9 tests validate that every YAML blueprint in knowledge/blueprints/ can be
loaded and successfully validated against the ActionRecipe Pydantic schema.

Validation assertions (per recipe):
  1. ActionRecipe.model_validate(raw) does not raise ValidationError
  2. recipe.name is a non-empty string
  3. recipe.steps is non-empty
  4. recipe.trigger_keywords is non-empty
  5. Every step.action is one of the 6 allowed values
  6. Every $variable used in step fields is declared in recipe.parameters

Regression tests (4 existing blueprints):
  - compact_view_navigate.yaml       — PASS before and after Phase 2
  - p_calendar_single.yaml           — PASS before and after Phase 2
  - p_calendar_range.yaml            — PASS before and after Phase 2
  - p_select_column_sort.yaml        — PASS before and after Phase 2

New blueprint tests (5 files added in Phase 2):
  - inline_edit.yaml                 — ERROR/FAIL until Phase 2 implementation
  - status_dropdown.yaml             — ERROR/FAIL until Phase 2 implementation
  - batch_checkbox.yaml              — ERROR/FAIL until Phase 2 implementation
  - approvals_workflow.yaml          — ERROR/FAIL until Phase 2 implementation
  - voice_form_combobox.yaml         — ERROR/FAIL until Phase 2 implementation

Run:
    pytest backend/engine/test_blueprint_validation.py -v
"""

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is required — pip install pyyaml")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_BLUEPRINTS_DIR = _PROJECT_ROOT / "knowledge" / "blueprints"

# ---------------------------------------------------------------------------
# Import ActionRecipe from recipe_runner — must be importable before testing
# ---------------------------------------------------------------------------

# Add backend to sys.path so recipe_runner can be imported standalone
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from engine.recipe_runner import ActionRecipe  # noqa: E402  (after sys.path setup)

# ---------------------------------------------------------------------------
# Valid action values (mirrors ActionRecipe's Literal constraint exactly)
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"click", "fill", "select_option", "press_key", "wait", "set_input_files"}

# ---------------------------------------------------------------------------
# Step fields that may contain $variable references (mirrors INTERPOLATED_FIELDS)
# ---------------------------------------------------------------------------

_INTERPOLATED_STEP_FIELDS = ("selector", "value", "name", "container_selector")


# ---------------------------------------------------------------------------
# Helper: load + validate a single YAML blueprint file
# ---------------------------------------------------------------------------


def _load_and_validate(filename: str) -> ActionRecipe:
    """
    Open `filename` from the blueprints directory, parse with yaml.safe_load(),
    and validate with ActionRecipe.model_validate().

    Raises FileNotFoundError if the file does not exist (signals pre-implementation).
    Raises pydantic.ValidationError if the YAML fails schema validation.
    """
    path = _BLUEPRINTS_DIR / filename
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return ActionRecipe.model_validate(raw)


# ---------------------------------------------------------------------------
# Helper: assert $variable consistency for a validated recipe
# ---------------------------------------------------------------------------


def _assert_variables_declared(recipe: ActionRecipe) -> None:
    """
    For every step in the recipe, extract all $variable references from the
    interpolatable fields (selector, value, name, container_selector) and assert
    that each referenced variable name appears in recipe.parameters.

    This catches YAML authoring typos before they reach Template.substitute(),
    where they would produce RecipeConfigurationError mid-run.
    """
    declared_params = {p.name for p in recipe.parameters}

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
                    f"but '{var_name}' is not declared in recipe.parameters. "
                    f"Declared parameters: {sorted(declared_params)}"
                )

    # Also check cleanup_on_failure steps
    for step_index, step in enumerate(recipe.cleanup_on_failure, start=1):
        for field_name in _INTERPOLATED_STEP_FIELDS:
            field_value = getattr(step, field_name, None)
            if not isinstance(field_value, str):
                continue
            referenced_vars = re.findall(r"\$(\w+)", field_value)
            for var_name in referenced_vars:
                assert var_name in declared_params, (
                    f"Recipe '{recipe.name}' cleanup_on_failure step {step_index}: "
                    f"field '{field_name}' references ${var_name} but '{var_name}' "
                    f"is not declared in recipe.parameters. "
                    f"Declared: {sorted(declared_params)}"
                )


# ---------------------------------------------------------------------------
# Helper: full structural assertions for a loaded recipe
# ---------------------------------------------------------------------------


def _assert_recipe_valid(recipe: ActionRecipe) -> None:
    """
    Run all structural assertions on a successfully loaded ActionRecipe.

    Called from every test function after _load_and_validate() succeeds.
    """
    # recipe.name is a non-empty string
    assert isinstance(recipe.name, str) and recipe.name.strip(), (
        f"Recipe name must be a non-empty string, got: {recipe.name!r}"
    )

    # steps is non-empty (Pydantic @model_validator also enforces this, but assert for clarity)
    assert len(recipe.steps) > 0, f"Recipe '{recipe.name}' must have at least one step"

    # trigger_keywords is non-empty
    assert len(recipe.trigger_keywords) > 0, f"Recipe '{recipe.name}' must have at least one trigger_keyword"

    # Every step action must be one of the 6 allowed values
    for step_index, step in enumerate(recipe.steps, start=1):
        assert step.action in _VALID_ACTIONS, (
            f"Recipe '{recipe.name}' step {step_index}: "
            f"action '{step.action}' is not valid. "
            f"Allowed: {sorted(_VALID_ACTIONS)}"
        )

    # Every $variable referenced in step fields must be declared in parameters
    _assert_variables_declared(recipe)


# ---------------------------------------------------------------------------
# Regression tests — 4 existing blueprints
# ---------------------------------------------------------------------------


def test_compact_view_navigate_blueprint():
    """
    Regression guard: compact_view_navigate.yaml must continue to pass schema
    validation after Phase 2 changes.

    Covers: compact_view_navigate.yaml with view_label + view_css_class params,
    element_visible verify_after, and cleanup_on_failure steps.
    """
    recipe = _load_and_validate("compact_view_navigate.yaml")
    _assert_recipe_valid(recipe)


def test_p_calendar_single_blueprint():
    """
    Regression guard: p_calendar_single.yaml must continue to pass schema
    validation after Phase 2 changes.

    Covers: p_calendar_single.yaml with container_selector + date params,
    4 steps (click, fill, press_key x2), element_visible verify_after.
    """
    recipe = _load_and_validate("p_calendar_single.yaml")
    _assert_recipe_valid(recipe)


def test_p_calendar_range_blueprint():
    """
    Regression guard: p_calendar_range.yaml must continue to pass schema
    validation after Phase 2 changes.

    Covers: p_calendar_range.yaml with container_selector + start_date + end_date
    params, 5 steps (click, fill, press_key, fill, press_key), element_visible verify_after.
    """
    recipe = _load_and_validate("p_calendar_range.yaml")
    _assert_recipe_valid(recipe)


def test_p_select_column_sort_blueprint():
    """
    Regression guard: p_select_column_sort.yaml must continue to pass schema
    validation after Phase 2 changes.

    Covers: p_select_column_sort.yaml with col_css + option_value + expected_column
    + expected_direction params, is_sort_recipe=True, table_sort verify_after.
    """
    recipe = _load_and_validate("p_select_column_sort.yaml")
    _assert_recipe_valid(recipe)


# ---------------------------------------------------------------------------
# New blueprint tests — 5 files added in Phase 2
# (All FAIL/ERROR before Phase 2 implementation; pass after)
# ---------------------------------------------------------------------------


def test_inline_edit_blueprint():
    """
    Phase 2 (WI-005): inline_edit.yaml must exist and pass schema validation.

    Expected behavior: double-click a table cell to enter edit mode, fill a value,
    press Enter to commit.

    Steps expected: click (double-click), fill, press_key (Enter).
    Parameters expected: at minimum a cell locator param and a value param.

    FAILS until knowledge/blueprints/inline_edit.yaml is created.
    """
    recipe = _load_and_validate("inline_edit.yaml")
    _assert_recipe_valid(recipe)


def test_status_dropdown_blueprint():
    """
    Phase 2 (WI-006): status_dropdown.yaml must exist and pass schema validation.

    Expected behavior: click a status badge to open its overlay, then click the
    desired option inside the overlay.

    Steps expected: click (status badge), click (option in overlay).
    Parameters expected: at minimum a status badge locator param and an option param.

    FAILS until knowledge/blueprints/status_dropdown.yaml is created.
    """
    recipe = _load_and_validate("status_dropdown.yaml")
    _assert_recipe_valid(recipe)


def test_batch_checkbox_blueprint():
    """
    Phase 2 (WI-007): batch_checkbox.yaml must exist and pass schema validation.

    Expected behavior: click a header checkbox ("all" mode) or a row checkbox
    ("row" mode) to select/deselect items.

    Steps expected: at least one click step.
    Parameters expected: at minimum a mode param or checkbox locator param.

    FAILS until knowledge/blueprints/batch_checkbox.yaml is created.
    """
    recipe = _load_and_validate("batch_checkbox.yaml")
    _assert_recipe_valid(recipe)


def test_approvals_workflow_blueprint():
    """
    Phase 2 (WI-008): approvals_workflow.yaml must exist and pass schema validation.

    Expected behavior: click an approval item, click approve or deny button,
    confirm the resulting dialog.

    Steps expected: click (item), click (approve/deny button), click (confirm dialog).
    Parameters expected: at minimum item locator, action (approve/deny), and confirm params.

    FAILS until knowledge/blueprints/approvals_workflow.yaml is created.
    """
    recipe = _load_and_validate("approvals_workflow.yaml")
    _assert_recipe_valid(recipe)


def test_voice_form_combobox_blueprint():
    """
    Phase 2 (WI-009): voice_form_combobox.yaml must exist and pass schema validation.

    Expected behavior: type in an autocomplete/combobox input to trigger an overlay,
    wait for the overlay to render, then click the desired option.

    Steps expected: fill (type query), wait (overlay render), click (option in overlay).
    Parameters expected: at minimum an input locator param and an option value param.

    FAILS until knowledge/blueprints/voice_form_combobox.yaml is created.
    """
    recipe = _load_and_validate("voice_form_combobox.yaml")
    _assert_recipe_valid(recipe)


def test_p_multiselect_search_blueprint():
    """
    Validate the p_multiselect_search.yaml blueprint.

    Expected behavior: opens a multiselect trigger, waits for render, clicks option,
    and presses Escape to dismiss panel.
    """
    recipe = _load_and_validate("p_multiselect_search.yaml")
    _assert_recipe_valid(recipe)

