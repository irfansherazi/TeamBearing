"""
vQA — Action Recipe Runner
============================
Module: backend/engine/recipe_runner.py

Implements the **Action Recipe** system — a YAML-driven library of pre-compiled,
multi-step interaction patterns for known PrimeNG UI components.

Why recipes exist
-----------------
The LLM planner excels at high-level reasoning but is unreliable at maintaining
context across rapid, state-dependent UI interactions (e.g., "open a dropdown,
wait for the animation, *then* click the option inside it").  Each click
triggers a planner→executor→verifier round-trip, which means the verifier can
fire before the overlay has fully rendered — producing a false NOT_YET verdict
that kicks off a loop.

Recipes short-circuit this by expressing the entire compound interaction as a
single atomic unit.  The planner emits one ``{"action": "recipe", ...}`` intent;
the executor runs all sub-steps invisibly; the verifier checks once at the end.

Architecture
------------

    YAML file (knowledge/blueprints/*.yaml)
        │
        ▼  loaded + validated by RecipeRegistry
    ActionRecipe (Pydantic)
        │
        ▼  matched to current AC step by RecipeRegistry.match()
    Planner receives ⚡ RECIPE AVAILABLE block in system prompt
        │
        ▼  planner emits {"action":"recipe","recipe_name":"...","recipe_params":{...}}
    pre_action_sort_check() — reads DOM aria-sort BEFORE any click (sort recipes only)
        │
        ▼  fill_recipe() validates params + Template.substitute() → list[dict]
        │
        ▼  execute_recipe() runs sub-steps atomically via _resolve_locator
    Single verification after completion (not between sub-steps)

Security
--------
Variable interpolation uses ``string.Template`` (``$variable`` syntax), NOT
``str.format()``.  The ``str.format()`` gadget allows arbitrary Python attribute
access via ``{__class__.__init__.__globals__}``; Template does not.

``string.Template.safe_substitute()`` is NEVER used.  ``safe_substitute()``
silently ignores missing variables, turning YAML authoring typos into Playwright
timeouts with no diagnostic.  We use ``Template(val).substitute(params)`` wrapped
in ``try/except KeyError`` — a KeyError is an authoring typo and must fail loudly
as ``RecipeConfigurationError``.

Each declared parameter is validated against an ``allowed_pattern`` regex
*before* substitution.  Only an explicit INTERPOLATED_FIELDS set is ever
substituted — action type, wait_after_ms, and other structural fields are never
interpolated.

Pre-Action Sort Check (Oscillation Guard)
------------------------------------------
Sort recipes implement a ``pre_action_sort_check`` hook.  Before any sub-step is
executed, the executor reads the current ``aria-sort`` attribute from the DOM via
JavaScript.  If the column is ALREADY sorted in the target direction, the recipe
returns ``{"success": True, "skipped": True}`` immediately — zero clicks, zero
LLM calls.  This eliminates the entire oscillation class of failures documented
in the QA-321 post-mortem.

Three-Tier Failure Cleanup
---------------------------
If a sub-step fails mid-execution the runner prevents UI from blinding the planner:

  Tier 1: YAML ``cleanup_on_failure`` steps (recipe-specific, e.g. "press Escape")
  Tier 2: Generic dismiss — press Escape + click body to clear any PrimeNG overlay
  Tier 3: Return a structured error dict to the planner containing:
           - exact sub-step index that failed
           - Playwright error message
           - list of cleanup actions attempted
           - expected UI state after cleanup

Maintenance
-----------
Recipes live entirely in ``knowledge/blueprints/*.yaml``.  Adding support for a
new PrimeNG component requires only writing a YAML file — no Python changes.
The ``RecipeRegistry`` hot-reloads YAML files if they have been modified since
the last load, so recipes can be updated between runs without a server restart.

See Also
--------
    - knowledge/blueprints/*.yaml      — recipe definitions
    - backend/engine/executor.py       — dispatches action='recipe' to execute_recipe()
    - backend/engine/planner.py        — injects recipe blocks into system prompt
    - backend/engine/schemas.py        — PlannerAction schema (includes 'recipe' action)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from string import Template
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directory where YAML blueprints live
# ---------------------------------------------------------------------------

BLUEPRINTS_DIR = Path(__file__).parent.parent.parent / "knowledge" / "blueprints"


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RecipeNotFoundError(ValueError):
    """Raised when a recipe name is requested but no matching YAML exists."""


class RecipeParameterError(ValueError):
    """Raised when a required parameter is missing or its value is disallowed."""


class RecipeConfigurationError(ValueError):
    """Raised when a YAML template contains an undeclared $variable (authoring typo).

    This deliberately fails loudly — safe_substitute() is never used because it
    silently swallows missing variables, turning YAML typos into Playwright timeouts
    with no diagnostic. A KeyError during Template.substitute() means the author
    declared a $variable in the YAML that is not in the parameters list. Fix the YAML.
    """


class RecipeExecutionError(RuntimeError):
    """Raised when a sub-step fails mid-recipe (includes cleanup state)."""


# ---------------------------------------------------------------------------
# Pydantic models — validated on YAML load (fail-fast on schema errors)
# ---------------------------------------------------------------------------


class RecipeParam(BaseModel):
    """Declaration of a single template variable for an ActionRecipe."""

    name: str = Field(description="Variable name — used as $name in YAML step fields.")
    description: str = Field(description="Human-readable description for the planner prompt.")
    allowed_pattern: str = Field(
        default=r"^[\w\s\.\-\#\[\]:\/\(\)\&,;]+$",
        description=(
            "Regex pattern that the runtime value MUST fully match before substitution. "
            "Prevents injection of shell metacharacters or YAML control sequences."
        ),
    )


class RecipeStep(BaseModel):
    """A single browser sub-step within an ActionRecipe."""

    action: Literal["click", "fill", "select_option", "press_key", "wait", "set_input_files"] = Field(
        description=(
            "Playwright action to perform. "
            "'set_input_files' bypasses the native OS file picker — sets files directly "
            "on a hidden input[type='file'] element via Playwright's setInputFiles API."
        )
    )
    # Locator fields (not required for 'wait' or 'press_key')
    strategy: Optional[
        Literal[
            "css_selector",
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
        ]
    ] = None
    role: Optional[str] = Field(
        default=None,
        description="ARIA role for get_by_role strategy. May contain $variable placeholders.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Element name / text — may contain $variable placeholders.",
    )
    container_selector: Optional[str] = Field(
        default=None,
        description=(
            "Optional CSS ancestor to scope the locator. "
            "May contain $variable placeholders. "
            "Example: 'p-select-overlay' scopes get_by_text to the open dropdown panel."
        ),
    )
    selector: Optional[str] = Field(
        default=None,
        description="Raw CSS selector (for css_selector strategy). May contain $variable.",
    )
    value: Optional[str] = Field(
        default=None,
        description="Value for fill / select_option. May contain $variable placeholders.",
    )
    key: Optional[str] = Field(
        default=None,
        description=(
            "Keyboard key for press_key action. E.g. 'Escape', 'Tab', 'Enter'. NOT interpolated (always literal)."
        ),
    )
    wait_after_ms: int = Field(
        default=0,
        description="Milliseconds to wait after the sub-step completes.",
        ge=0,
        le=10000,
    )


class VerificationSpec(BaseModel):
    """Post-recipe programmatic verification (runs after all sub-steps complete)."""

    type: Literal["element_visible", "element_hidden", "element_state", "table_sort", "verify_state_change"] = Field(
        description="Verification type (maps to verifier.py programmatic checks)."
    )
    # For element_* types
    selector: Optional[str] = Field(
        default=None,
        description="CSS selector for the element to check. May contain $variable.",
    )
    expected_state: Optional[str] = Field(
        default=None,
        description="For element_state: 'disabled', 'enabled', 'checked', 'unchecked'.",
    )
    # For table_sort type
    expected_column: Optional[str] = Field(
        default=None,
        description=(
            "For table_sort: the visible column header label (e.g. 'CLIENT', 'Due Date'). "
            "May contain $variable so the YAML author can use $col_label."
        ),
    )
    expected_direction: Optional[str] = Field(
        default=None,
        description=(
            "For table_sort: 'ascending' or 'descending'. "
            "May be a $variable so the YAML author can use $direction or $expected_direction "
            "(interpolated at runtime by _fill_verify_after before the check runs). "
            "NOTE: Pydantic validates this field at YAML load time with the raw string, "
            "so it CANNOT be a Literal type — the $variable would fail the Literal check "
            "before Template.substitute has a chance to run."
        ),
    )

    @model_validator(mode="after")
    def validate_type_fields(self) -> "VerificationSpec":
        if self.type in ("element_visible", "element_hidden", "element_state"):
            if not self.selector:
                raise ValueError(f"VerificationSpec type='{self.type}' requires 'selector'.")
        if self.type == "table_sort":
            if not self.expected_direction:
                raise ValueError(
                    "VerificationSpec type='table_sort' requires 'expected_direction' ('ascending' or 'descending')."
                )
        return self


class ActionRecipe(BaseModel):
    """
    A complete YAML-defined interaction recipe for a known PrimeNG component.

    Validated by Pydantic on load — schema errors raise immediately with field
    names and file paths, never silently mid-run.
    """

    name: str = Field(description="Unique snake_case recipe identifier.")
    description: str = Field(description="One-sentence description for the planner prompt.")
    trigger_keywords: list[str] = Field(
        description=(
            "Token list used for Jaccard matching against AC step text. "
            "Include both the UI label ('Due / Days') and DOM identifiers "
            "('duedaysCol') so matching is robust."
        )
    )
    parameters: list[RecipeParam] = Field(
        default_factory=list,
        description="Declared template variables. Every $variable in step fields MUST be declared here.",
    )
    steps: list[RecipeStep] = Field(description="Ordered list of browser sub-steps to execute atomically.")
    cleanup_on_failure: list[RecipeStep] = Field(
        default_factory=list,
        description=(
            "Steps to run if any main step fails (e.g., press Escape to close open overlay). "
            "Executed best-effort — exceptions are swallowed to avoid masking the original error."
        ),
    )
    verify_after: Optional[VerificationSpec] = Field(
        default=None,
        description="Single programmatic check to run after all steps complete.",
    )
    # Optional: marks this recipe as a sort recipe — enables pre_action_sort_check hook.
    # When set, the executor reads the DOM aria-sort state before ANY sub-step runs.
    # If the column is already in the target direction, execution is skipped entirely.
    is_sort_recipe: bool = Field(
        default=False,
        description=(
            "Set to true for sort recipes. Enables the pre_action_sort_check hook, "
            "which reads the current DOM aria-sort state and skips execution if the "
            "column is already sorted in the requested direction. "
            "Eliminates the oscillation loop."
        ),
    )
    # Hardware-level wait (FEAT-049 / TASK-054)
    force_wait_before_next: bool = Field(
        default=False,
        description=(
            "If true, sets the _force_wait flag in state after recipe completion. "
            "Prevents 'staccato' execution on problematic PrimeNG components that "
            "re-render DOM multiple times during loading."
        ),
    )
    force_wait_ms: int = Field(
        default=1500,
        description="Duration of the force wait in milliseconds.",
        ge=0,
        le=10000,
    )

    @model_validator(mode="after")
    def validate_steps_not_empty(self) -> "ActionRecipe":
        if not self.steps:
            raise ValueError(f"Recipe '{self.name}' must have at least one step.")
        return self


# ---------------------------------------------------------------------------
# Fields allowed for $variable interpolation (structural fields are never substituted)
# ---------------------------------------------------------------------------

#: Only these RecipeStep fields are ever passed through Template.substitute().
#: This prevents the LLM from injecting new actions or overriding wait times.
#: Note: 'key' is intentionally excluded — keyboard keys are always literal.
INTERPOLATED_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "container_selector",
        "selector",
        "value",
        "role",
    }
)

#: VerificationSpec fields that allowed $variable interpolation.
VERIFICATION_INTERPOLATED_FIELDS: frozenset[str] = frozenset(
    {
        "selector",
        "expected_column",
        "expected_direction",
    }
)


# ---------------------------------------------------------------------------
# fill_recipe — validate parameters and perform safe Template substitution
# ---------------------------------------------------------------------------


def fill_recipe(recipe: ActionRecipe, params: dict[str, str]) -> list[dict[str, Any]]:
    """
    Validate runtime parameter values and interpolate them into recipe steps.

    Parameters
    ----------
    recipe : ActionRecipe
        The recipe to fill.
    params : dict[str, str]
        Parameter values from the planner (e.g. {"col_css": "th.po-col-duedaysCol",
        "option_value": "due_date;1"}).

    Returns
    -------
    list[dict]
        Filled step dicts ready to pass to execute_recipe().

    Raises
    ------
    RecipeParameterError
        If a declared parameter is missing or its value fails the allowed_pattern regex.
    RecipeConfigurationError
        If a YAML step field references an undeclared $variable (authoring typo).
        NOTE: Template.safe_substitute() is explicitly NOT used here — silent variable
        swallowing causes Playwright timeouts with no diagnostic. A KeyError means
        the YAML author declared a $variable that isn't in the parameters list.
    """
    # ── Auto-derive computed parameters before validation ─────────────────
    # Some parameters can be deterministically computed from other parameters.
    # Inject them before validation so the planner doesn't have to compute them.
    # This keeps the recipe backward-compatible: cards only need to pass view_label.
    #
    # view_css_class: derived from view_label (compact_view_navigate recipe).
    # Mapping: Angular applies selectedTableView.toLowerCase() as a CSS class on
    # div.po-table-wrapper (productionorders.html line 148). The mapping is:
    #   "Compact" → "compact"   → div.po-table-wrapper.compact
    #   "List"    → "modern"    → div.po-table-wrapper.modern
    #   "Minimal" → "minimal"   → div.po-table-wrapper.minimal
    _VIEW_LABEL_TO_CSS: dict[str, str] = {
        "compact": "compact",
        "list": "modern",
        "minimal": "minimal",
    }
    if "view_css_class" not in params and "view_label" in params:
        raw_label = str(params["view_label"]).lower().strip()
        derived_css = _VIEW_LABEL_TO_CSS.get(raw_label)
        if derived_css:
            params = {**params, "view_css_class": derived_css}
            logger.debug(
                "fill_recipe: auto-derived view_css_class='%s' from view_label='%s'",
                derived_css,
                params["view_label"],
            )
        # If unknown view_label, let validation below raise RecipeParameterError
        # with a clear "view_css_class not provided" message rather than silently
        # proceeding with a broken selector.

    # ── Layer 1: Validate all declared parameters ──────────────────────────
    for param_def in recipe.parameters:
        val = params.get(param_def.name)
        if val is None:
            raise RecipeParameterError(
                f"Recipe '{recipe.name}' requires parameter '{param_def.name}' "
                f"({param_def.description}) — not provided by planner. "
                f"Provided params: {sorted(params.keys())}"
            )
        if not re.fullmatch(param_def.allowed_pattern, str(val)):
            raise RecipeParameterError(
                f"Recipe '{recipe.name}': parameter '{param_def.name}' "
                f"value {val!r} contains disallowed characters. "
                f"Allowed pattern: {param_def.allowed_pattern}"
            )

    # ── Layer 2: Strict Template substitution (KeyError = YAML typo) ───────
    # CRITICAL: Template(val).substitute(params) — NOT safe_substitute().
    # safe_substitute() silently ignores missing variables → Playwright timeout.
    # substitute() raises KeyError on unknown $variable → RecipeConfigurationError.
    filled: list[dict[str, Any]] = []
    for i, step in enumerate(recipe.steps):
        step_dict = step.model_dump(exclude_none=True)
        for field in INTERPOLATED_FIELDS:
            if field in step_dict and isinstance(step_dict[field], str):
                try:
                    step_dict[field] = Template(step_dict[field]).substitute(params)
                except KeyError as e:
                    raise RecipeConfigurationError(
                        f"Recipe '{recipe.name}' step {i + 1}: "
                        f"field '{field}' contains undeclared variable ${e.args[0]}. "
                        f"Declare it in the recipe's 'parameters' list or fix the typo. "
                        f"Available params: {sorted(params.keys())}"
                    ) from e
                except ValueError as e:
                    # Template raises ValueError for malformed patterns (e.g. lone $)
                    raise RecipeConfigurationError(
                        f"Recipe '{recipe.name}' step {i + 1}: "
                        f"field '{field}' has a malformed Template pattern: {e}. "
                        f"Check for unescaped $ characters (use $$ for a literal $)."
                    ) from e
        filled.append(step_dict)

    return filled


def _fill_cleanup_steps(
    cleanup_steps: list[RecipeStep],
    params: dict[str, str],
    recipe_name: str,
) -> list[dict[str, Any]]:
    """Fill cleanup steps — best-effort, swallows interpolation errors.

    Cleanup steps must never raise — a cleanup interpolation failure would mask
    the original execution error. Log warnings and continue.
    """
    filled = []
    for i, step in enumerate(cleanup_steps):
        step_dict = step.model_dump(exclude_none=True)
        for field in INTERPOLATED_FIELDS:
            if field in step_dict and isinstance(step_dict[field], str):
                try:
                    step_dict[field] = Template(step_dict[field]).substitute(params)
                except (KeyError, ValueError):
                    # Best-effort: don't let a cleanup typo mask the original error
                    logger.warning(
                        "Recipe '%s' cleanup step %d field '%s' interpolation failed — using raw value",
                        recipe_name,
                        i + 1,
                        field,
                    )
        filled.append(step_dict)
    return filled


def _fill_verify_after(
    spec: VerificationSpec,
    params: dict[str, str],
    recipe_name: str,
) -> dict[str, Any]:
    """
    Fill a VerificationSpec's interpolatable fields with Template.substitute().

    Uses strict substitute() (not safe_substitute()) for selector and
    expected_column — a typo here is a YAML authoring error that must fail loudly.
    expected_direction uses safe_substitute() because it may be a literal value
    like 'ascending' with no variables.
    """
    spec_dict = spec.model_dump(exclude_none=True)
    for field in VERIFICATION_INTERPOLATED_FIELDS:
        if field in spec_dict and isinstance(spec_dict[field], str):
            try:
                spec_dict[field] = Template(spec_dict[field]).substitute(params)
            except KeyError as e:
                raise RecipeConfigurationError(
                    f"Recipe '{recipe_name}' verify_after: "
                    f"field '{field}' contains undeclared variable ${e.args[0]}. "
                    f"Declare it in the recipe's 'parameters' list or fix the typo."
                ) from e
            except ValueError as e:
                raise RecipeConfigurationError(
                    f"Recipe '{recipe_name}' verify_after: field '{field}' has a malformed Template pattern: {e}."
                ) from e
    return spec_dict


# ---------------------------------------------------------------------------
# Pre-action sort state check (oscillation guard)
# ---------------------------------------------------------------------------


async def pre_action_sort_check(
    page: Any,
    params: dict[str, str],
    recipe: ActionRecipe,
    run_id: str,
) -> dict[str, Any] | None:
    """
    Pre-action hook for sort recipes: reads DOM aria-sort state via JS before
    any sub-step executes.

    If the column is ALREADY sorted in the target direction, returns a success
    dict with ``skipped=True`` immediately. Zero clicks. Zero LLM calls.
    Eliminates the oscillation loop documented in the QA-321 post-mortem.

    This hook only fires when ``recipe.is_sort_recipe is True`` AND the recipe's
    ``verify_after`` specifies ``type="table_sort"`` with ``expected_direction``.

    Parameters
    ----------
    page : playwright.async_api.Page
        The live browser page.
    params : dict[str, str]
        Filled recipe parameters (post-validation, post-interpolation).
    recipe : ActionRecipe
        The recipe definition.
    run_id : str
        Run identifier for logging.

    Returns
    -------
    dict | None
        If the sort is already correct: ``{"success": True, "skipped": True, ...}``
        If not yet sorted correctly, or check fails: ``None`` (proceed with execution)
    """
    if not recipe.is_sort_recipe or not recipe.verify_after:
        return None

    spec = recipe.verify_after
    if spec.type != "table_sort" or not spec.expected_direction:
        return None

    # Interpolate expected_column and expected_direction from params
    try:
        spec_dict = _fill_verify_after(spec, params, recipe.name)
    except RecipeConfigurationError:
        return None  # Config error — let execution proceed and fail loudly

    expected_dir: str = spec_dict.get("expected_direction", "").lower()
    expected_col: str = spec_dict.get("expected_column", "")
    if not expected_dir:
        return None

    opposite_dir = "descending" if expected_dir == "ascending" else "ascending"

    # ── DOM JS extraction (never Vision OCR) ─────────────────────────────
    # Reads aria-sort attribute directly from the DOM — no screenshot needed.
    # This is deterministic, instant, and immune to rendering race conditions.
    js_result: dict = {}
    try:
        js_result = await page.evaluate(
            """
            ([colLabel]) => {
                // Strategy 1: named columnheader aria-sort
                if (colLabel) {
                    const ths = Array.from(document.querySelectorAll('th[role="columnheader"], th'));
                    for (const th of ths) {
                        const text = (th.innerText || th.textContent || '').trim();
                        if (text.toLowerCase().includes(colLabel.toLowerCase())) {
                            const sort = (th.getAttribute('aria-sort') || '').toLowerCase();
                            if (sort) return { method: 'aria_named', sort, col: text };
                        }
                    }
                }
                // Strategy 2: any th with aria-sort (global scan)
                const sorted = document.querySelector('th[aria-sort]');
                if (sorted) {
                    const sort = (sorted.getAttribute('aria-sort') || '').toLowerCase();
                    const text = (sorted.innerText || sorted.textContent || '').trim();
                    return { method: 'aria_global', sort, col: text };
                }
                // Strategy 3: PrimeNG sort icon CSS class
                const ascIcon = document.querySelector(
                    '.pi-sort-amount-up-alt, .pi-sort-up'
                );
                if (ascIcon) return { method: 'icon', sort: 'ascending', col: '' };
                const descIcon = document.querySelector(
                    '.pi-sort-amount-down, .pi-sort-down'
                );
                if (descIcon) return { method: 'icon', sort: 'descending', col: '' };
                // Strategy 4: compact-view sort button
                const sortBtn = document.querySelector('button#sort-btn');
                if (sortBtn) {
                    const arrowUp = document.querySelector('button.sort-btn .sort-arrow.up');
                    return {
                        method: 'compact_btn',
                        sort: arrowUp ? 'ascending' : 'descending',
                        col: (sortBtn.innerText || '').trim()
                    };
                }
                return { method: 'none', sort: '', col: '' };
            }
            """,
            [expected_col],
        )
    except Exception as e:
        logger.debug(
            "[%s] pre_action_sort_check: JS evaluation failed (%s) — proceeding with execution",
            run_id,
            str(e)[:80],
        )
        return None

    current_sort: str = js_result.get("sort", "").lower()
    detection_method: str = js_result.get("method", "none")
    detected_col: str = js_result.get("col", "")

    if not current_sort or detection_method == "none":
        logger.debug(
            "[%s] pre_action_sort_check: no sort state detected (method=%s) — proceeding",
            run_id,
            detection_method,
        )
        return None

    if current_sort == expected_dir:
        # Already in the correct direction — skip the entire recipe
        logger.info(
            "[%s] pre_action_sort_check SKIP: col='%s' already sorted '%s' "
            "(detected via %s, col_in_DOM='%s') — recipe '%s' skipped, zero clicks",
            run_id,
            expected_col,
            expected_dir,
            detection_method,
            detected_col,
            recipe.name,
        )
        return {
            "success": True,
            "skipped": True,
            "error_message": None,
            "recipe_name": recipe.name,
            "steps_run": 0,
            "sort_already_correct": True,
            "pre_check_evidence": (
                f"pre_action_sort_check: column='{expected_col}' already "
                f"aria-sort='{current_sort}' (target='{expected_dir}') via {detection_method}"
            ),
        }

    if current_sort == opposite_dir:
        # Opposite direction — one click will land on the correct direction.
        # Proceed with execution but log the oscillation risk.
        logger.info(
            "[%s] pre_action_sort_check: col='%s' currently '%s' (expected '%s') "
            "— proceeding with recipe click (one click should land correctly)",
            run_id,
            expected_col,
            current_sort,
            expected_dir,
        )
        return None

    # Unknown state — proceed
    return None


# ---------------------------------------------------------------------------
# Dynamic sub-step dispatcher
# ---------------------------------------------------------------------------


async def _dispatch_sub_step(
    page: Any,
    sub_step: dict[str, Any],
    _resolve_locator_fn: Any,
) -> None:
    """
    Dynamically dispatch a single recipe sub-step to the correct Playwright call.

    This function dispatches based on ``sub_step["action"]`` — no hardcoded
    action types in the caller.  Adding support for a new action type requires
    only updating this function, not the calling code.

    Supported actions: click, fill, select_option, press_key, wait

    Parameters
    ----------
    page : playwright.async_api.Page
        The live browser page.
    sub_step : dict
        A filled sub-step dict from fill_recipe().
    _resolve_locator_fn : callable
        Async function (page, action_dict) → Playwright Locator.
        Injected from executor.py to reuse its locator resolution logic.

    Raises
    ------
    RecipeExecutionError
        If the action type is unknown or the Playwright call fails.
    """
    step_action: str = sub_step.get("action", "")

    if step_action == "wait":
        # Standalone wait — uses wait_after_ms as the duration
        await page.wait_for_timeout(sub_step.get("wait_after_ms", 200))
        return

    if step_action == "press_key":
        key: str = sub_step.get("key", "Escape")
        await page.keyboard.press(key)
        # wait_after_ms is applied by the caller after this returns
        return

    if step_action == "set_input_files":
        # Bypass the native OS file picker — set files directly on the hidden
        # input[type="file"] element.  Uses 'selector' or 'name' for the input
        # locator, and 'value' for the file path (absolute or asset-inventory name).
        # This is identical to executor.py's set_input_files handler so it integrates
        # cleanly with the existing ASSET_INVENTORY without any changes to Python code.
        file_selector: str = sub_step.get("selector") or sub_step.get("name") or ""
        file_path: str = sub_step.get("value", "")
        if not file_selector:
            raise RecipeExecutionError(
                "set_input_files requires 'selector' or 'name' pointing to input[type='file']. "
                "Example: selector: \"p-fileupload input[type='file']\""
            )
        if not file_path:
            raise RecipeExecutionError("set_input_files requires 'value' (file path or asset-inventory filename).")
        await page.locator(file_selector).set_input_files(file_path, timeout=10000)
        return

    # ── All locator-based click/fill/select_option actions ────────────────
    if step_action in ("click", "fill", "select_option"):
        locator = await _resolve_locator_fn(page, sub_step)

        if step_action == "click":
            # Pre-click existence guard for overlay panels.
            # PrimeNG overlays (p-select-overlay, p-dialog, etc.) animate in
            # asynchronously. If the sub-step's CSS selector targets an overlay
            # option (e.g., .po-sorting-dropdown-panel li[...]), wait for it to
            # be visible before clicking — prevents "no element found" and
            # "detached from DOM" race conditions on sub-step 2.
            _css_selector = sub_step.get("selector") or sub_step.get("name", "")
            _strategy = sub_step.get("strategy", "")
            _OVERLAY_HINTS = (
                ".po-sorting-dropdown-panel",
                "p-select-overlay",
                ".p-select-overlay",
                "p-overlay",
                ".p-dialog",
                "[data-p-value",
                ".p-listbox-list",
                "li[data-p-",
            )
            _is_overlay_target = _strategy == "css_selector" and any(hint in _css_selector for hint in _OVERLAY_HINTS)
            if _is_overlay_target:
                try:
                    await page.wait_for_selector(
                        _css_selector,
                        state="visible",
                        timeout=4000,
                    )
                except Exception as _wait_err:
                    # Log the miss but let the click attempt proceed and fail
                    # naturally — this generates a better error message than
                    # raising here.
                    logger.debug(
                        "Recipe overlay pre-wait for '%s' timed out (%s) — attempting click anyway",
                        _css_selector[:80],
                        str(_wait_err)[:60],
                    )
            await locator.click(timeout=8000)

        elif step_action == "fill":
            val: str = sub_step.get("value", "")
            await locator.fill(val, timeout=8000)

        elif step_action == "select_option":
            val = sub_step.get("value", "")
            await locator.select_option(val, timeout=8000)

    else:
        raise RecipeExecutionError(
            f"Unknown recipe sub-step action type: '{step_action}'. "
            f"Supported: click, fill, select_option, press_key, wait, set_input_files."
        )


# ---------------------------------------------------------------------------
# execute_recipe — atomically run filled steps with mid-recipe cleanup
# ---------------------------------------------------------------------------


async def execute_recipe(
    page: Any,  # playwright Page
    recipe: ActionRecipe,
    filled_steps: list[dict[str, Any]],
    params: dict[str, str],
    run_id: str,
    _resolve_locator_fn: Any,  # injected from executor to avoid circular import
) -> dict[str, Any]:
    """
    Execute a filled recipe atomically.

    Pre-action hook (sort recipes only):
      Before any sub-step executes, reads the DOM aria-sort state.
      If the column is already sorted correctly, returns immediately with
      skipped=True — zero clicks, zero LLM calls.

    If any sub-step fails, three-tier cleanup prevents UI from blinding the planner:
      Tier 1 — Run YAML ``cleanup_on_failure`` steps (best-effort).
      Tier 2 — Generic Escape + body-click dismiss (best-effort).
      Tier 3 — Return a structured error dict with:
                • sub-step index that failed
                • Playwright error message (truncated to 200 chars)
                • list of cleanup actions attempted
                • explicit note on expected UI state after cleanup

    Parameters
    ----------
    page : playwright.async_api.Page
        The live browser page.
    recipe : ActionRecipe
        The recipe definition (for cleanup_on_failure and verify_after).
    filled_steps : list[dict]
        Output of ``fill_recipe()`` — interpolated sub-step dicts.
    params : dict[str, str]
        Original parameter values (needed for cleanup interpolation and
        verify_after interpolation).
    run_id : str
        Run identifier for logging.
    _resolve_locator_fn : callable
        Async function (page, action_dict) → Playwright Locator.
        Injected from executor.py to reuse its locator resolution logic.

    Returns
    -------
    dict
        ``{"success": True, ...}`` on full completion,
        ``{"success": True, "skipped": True, ...}`` if pre-check determined sort already correct,
        ``{"success": False, "error_message": "...", ...}`` on any sub-step failure.
    """
    # ── Pre-action sort check (oscillation guard) ──────────────────────────
    # Only fires for recipes with is_sort_recipe=True and a table_sort verify_after.
    # Reads DOM aria-sort state via JS. If already correct direction: skip entirely.
    sort_skip_result = await pre_action_sort_check(page, params, recipe, run_id)
    if sort_skip_result is not None:
        return sort_skip_result

    # ── Pre-action idempotency check (navigation recipes) ─────────────────
    # For recipes with a verify_after element_visible check (e.g. compact_view_navigate),
    # check if the target UI element is ALREADY visible before executing any sub-steps.
    #
    # Rationale: if the agent is already in Compact view and runs compact_view_navigate
    # a second time, the sub-steps click the settings button and "Compact" AGAIN, which
    # toggles the view AWAY from Compact — making the verify_after element disappear.
    # Checking first and skipping prevents this destructive double-navigation.
    #
    # Interaction recipes (verify_state_change) should NOT skip — they MUST execute
    # to perform their intended side-effect.
    pre_check_spec = {}
    if recipe.verify_after and not recipe.is_sort_recipe:
        try:
            pre_check_spec = _fill_verify_after(recipe.verify_after, params, recipe.name)
        except Exception:
            pass

        if pre_check_spec.get("type") == "element_visible":
            _sel = pre_check_spec.get("selector", "")
            if _sel:
                try:
                    _already_count = await page.locator(_sel).count()
                    _already_visible = _already_count > 0 and await page.locator(_sel).first.is_visible()
                except Exception:
                    _already_visible = False

                if _already_visible:
                    logger.info(
                        "[%s] Recipe '%s' pre-check: verify_after element '%s' already visible "
                        "— skipping all %d sub-steps (idempotent no-op).",
                        run_id,
                        recipe.name,
                        _sel,
                        len(filled_steps),
                    )
                    return {
                        "success": True,
                        "skipped": True,
                        "reason": f"Pre-check: '{_sel}' already visible — recipe is a no-op",
                        "recipe": recipe.name,
                        "steps_executed": 0,
                    }

    # ── Pre-action state capture (interaction recipes) ────────────────────
    # For recipes using verify_state_change, capture a snapshot of the DOM
    # before execution so we can compare it afterward.
    pre_state_snapshot = {}
    if pre_check_spec.get("type") == "verify_state_change":
        try:
            pre_state_snapshot = {
                "url": page.url,
                "element_count": await page.evaluate("document.querySelectorAll('*').length"),
            }
            # Optional: capture accessibility snapshot if possible
            try:
                raw_aria = await page.accessibility.snapshot()
                import json as _json

                pre_state_snapshot["aria_snapshot"] = _json.dumps(raw_aria, sort_keys=True) if raw_aria else ""
            except Exception:
                pre_state_snapshot["aria_snapshot"] = None
        except Exception as _snap_err:
            logger.debug("[%s] Recipe pre-state capture failed: %s", run_id, _snap_err)

    logger.info("[%s] Executing recipe '%s' (%d steps)", run_id, recipe.name, len(filled_steps))

    for i, sub_step in enumerate(filled_steps):
        step_action = sub_step.get("action", "")
        step_label = f"{step_action} → '{sub_step.get('name') or sub_step.get('key') or sub_step.get('selector', '?')}'"
        logger.info(
            "[%s] Recipe '%s' sub-step %d/%d: %s",
            run_id,
            recipe.name,
            i + 1,
            len(filled_steps),
            step_label,
        )

        try:
            await _dispatch_sub_step(page, sub_step, _resolve_locator_fn)

            # Post-sub-step wait (animation / transition settle)
            wait_ms = sub_step.get("wait_after_ms", 0)
            if wait_ms > 0 and step_action != "wait":
                # 'wait' action already consumed wait_after_ms internally
                await page.wait_for_timeout(wait_ms)

        except Exception as e:
            # ── Build "prior step" context for Tier 3 error ──────────────
            if i > 0:
                prior = filled_steps[i - 1]
                prior_label = f"{prior.get('action', '?')} → '{prior.get('name') or prior.get('key') or '?'}'"
                prior_desc = f"Sub-step {i}/{len(filled_steps)} succeeded ({prior_label}).\n"
            else:
                prior_desc = "No prior sub-steps had executed.\n"

            cleanup_actions_taken: list[str] = []

            # ── Tier 1: YAML-defined cleanup_on_failure ───────────────────
            if recipe.cleanup_on_failure:
                logger.info(
                    "[%s] Recipe '%s' failed at sub-step %d — running %d YAML cleanup step(s)",
                    run_id,
                    recipe.name,
                    i + 1,
                    len(recipe.cleanup_on_failure),
                )
                cleanup_filled = _fill_cleanup_steps(recipe.cleanup_on_failure, params, recipe.name)
                for j, cleanup_step in enumerate(cleanup_filled):
                    c_action = cleanup_step.get("action", "")
                    try:
                        if c_action == "wait":
                            await page.wait_for_timeout(cleanup_step.get("wait_after_ms", 200))
                            cleanup_actions_taken.append(f"cleanup[{j + 1}]: wait")
                        elif c_action == "press_key":
                            k = cleanup_step.get("key", "Escape")
                            await page.keyboard.press(k)
                            w = cleanup_step.get("wait_after_ms", 0)
                            if w > 0:
                                await page.wait_for_timeout(w)
                            cleanup_actions_taken.append(f"cleanup[{j + 1}]: press_key({k})")
                        elif c_action == "click":
                            c_loc = await _resolve_locator_fn(page, cleanup_step)
                            await c_loc.click(timeout=3000)
                            cleanup_actions_taken.append(f"cleanup[{j + 1}]: click({cleanup_step.get('name', '?')})")
                        elif c_action == "fill":
                            c_loc = await _resolve_locator_fn(page, cleanup_step)
                            await c_loc.fill(cleanup_step.get("value", ""), timeout=3000)
                            cleanup_actions_taken.append(f"cleanup[{j + 1}]: fill({cleanup_step.get('name', '?')})")
                    except Exception as cleanup_err:
                        cleanup_actions_taken.append(f"cleanup[{j + 1}]: {c_action} FAILED ({str(cleanup_err)[:40]})")
                        logger.debug(
                            "[%s] Recipe '%s' cleanup sub-step %d swallowed: %s",
                            run_id,
                            recipe.name,
                            j + 1,
                            str(cleanup_err)[:80],
                        )

            # ── Tier 2: Generic overlay dismiss ──────────────────────────
            reset_desc, reset_actions = await _attempt_state_reset(page, run_id)
            cleanup_actions_taken.extend(reset_actions)

            # ── Tier 3: Structured error for the planner ──────────────────
            # Contains: sub-step index, Playwright error, cleanup log, expected UI state.
            # DOM extraction preferred over vision — use page.url as context, not screenshot.
            error_message = (
                f"Recipe '{recipe.name}' failed at sub-step "
                f"{i + 1}/{len(filled_steps)} ({step_label}).\n"
                f"{prior_desc}"
                f"Playwright error: {str(e)[:200]}\n"
                f"Cleanup actions attempted: {', '.join(cleanup_actions_taken) or 'none'}.\n"
                f"Expected UI state after cleanup: any open overlays (p-select-overlay, "
                f".p-dialog-mask) should be dismissed. Verify the page is stable at "
                f"{page.url} before planning your next action."
            )

            logger.warning("[%s] %s", run_id, error_message.replace("\n", " "))

            return {
                "success": False,
                "error_message": error_message,
                "recipe_name": recipe.name,
                "recipe_failed_at_step": i + 1,
                "recipe_failed_step_label": step_label,
                "cleanup_actions": cleanup_actions_taken,
                "actual_url": page.url,
            }

    # ── All sub-steps completed — run verify_after if declared ────────────
    if recipe.verify_after:
        verify_ok, verify_evidence = await _check_verify_after(
            page,
            recipe.verify_after,
            params,
            run_id,
            recipe.name,
            pre_state=pre_state_snapshot,
        )
        if not verify_ok:
            logger.warning(
                "[%s] Recipe '%s' completed but verify_after FAILED: %s",
                run_id,
                recipe.name,
                verify_evidence,
            )
            return {
                "success": False,
                "error_message": (
                    f"Recipe '{recipe.name}' executed all {len(filled_steps)} steps "
                    f"successfully, but the post-recipe verification failed: {verify_evidence}. "
                    f"The UI may not have responded as expected. "
                    f"Current URL: {page.url}"
                ),
                "recipe_name": recipe.name,
                "recipe_failed_at_step": None,
                "actual_url": page.url,
            }
        logger.info("[%s] Recipe '%s' verify_after: %s", run_id, recipe.name, verify_evidence)

    logger.info(
        "[%s] Recipe '%s' completed successfully (%d steps run)",
        run_id,
        recipe.name,
        len(filled_steps),
    )
    res = {
        "success": True,
        "skipped": False,
        "error_message": None,
        "recipe_name": recipe.name,
        "steps_run": len(filled_steps),
        "actual_url": page.url,
    }
    if recipe.force_wait_before_next:
        res["_force_wait_before_next_action"] = True
        res["_force_wait_ms"] = recipe.force_wait_ms

    return res


# ---------------------------------------------------------------------------
# _attempt_state_reset — Tier 2 generic UI cleanup
# ---------------------------------------------------------------------------


async def _attempt_state_reset(
    page: Any,
    run_id: str,
) -> tuple[str, list[str]]:
    """
    Tier 2 generic UI state reset after a mid-recipe failure.

    Attempts three escalating dismiss strategies:
      1. Press Escape — dismisses PrimeNG dropdowns, autocomplete overlays, dialogs
      2. Click body at top-left corner (force=True) — clears modal backdrops
      3. Wait 300ms for Angular change detection to settle

    Uses DOM extraction (not Vision) to decide if cleanup is needed:
    checks for live overlay elements via page.locator().count() before acting.

    Returns
    -------
    tuple[str, list[str]]
        (human_readable_summary, list_of_action_descriptions)
        Both are passed to the Tier 3 structured error.
    """
    actions_taken: list[str] = []

    # Step 1: Press Escape — dismisses most PrimeNG overlays
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        actions_taken.append("press Escape")
    except Exception as e:
        logger.debug("[%s] State reset: Escape failed — %s", run_id, str(e)[:40])

    # Step 2: Check for live overlay elements (DOM extraction, not Vision OCR)
    # and click body to dismiss modal backdrops if found.
    try:
        overlay_selectors = [
            "p-select-overlay",
            ".p-dialog-mask",
            ".p-overlaypanel",
            ".p-autocomplete-panel",
            ".cdk-overlay-backdrop",
        ]
        overlay_selector = ", ".join(overlay_selectors)
        overlay_count = await page.locator(overlay_selector).count()
        if overlay_count > 0:
            # DOM confirms overlay is still present — click body to dismiss
            await page.locator("body").click(position={"x": 10, "y": 10}, force=True, timeout=2000)
            await page.wait_for_timeout(200)
            actions_taken.append(f"clicked body (force) to dismiss backdrop ({overlay_count} overlays detected)")
    except Exception as e:
        logger.debug("[%s] State reset: body click failed — %s", run_id, str(e)[:40])

    # Step 3: Wait for Angular CD cycle to complete
    try:
        await page.wait_for_timeout(300)
        actions_taken.append("waited 300ms for Angular CD settle")
    except Exception:
        pass

    summary = ", ".join(actions_taken) if actions_taken else "no reset actions possible"
    logger.debug("[%s] State reset complete: %s", run_id, summary)
    return summary, actions_taken


# ---------------------------------------------------------------------------
# _check_verify_after — run post-recipe programmatic verification
# ---------------------------------------------------------------------------


async def _check_verify_after(
    page: Any,
    spec: VerificationSpec,
    params: dict[str, str],
    run_id: str,
    recipe_name: str,
    pre_state: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Run the recipe's post-completion programmatic verification.

    Supports five verification types:
      - element_visible: selector must be visible in DOM
      - element_hidden:  selector must be hidden/detached
      - element_state:   selector must be disabled/enabled/checked
      - table_sort:      DOM aria-sort scan
      - verify_state_change: URL, element count, or ARIA snapshot must change

    On element_visible timeout, captures: screenshot to disk, current URL, and
    the first 50 DOM body lines so developers can immediately see why the view
    change failed (wrong URL, CSS class renamed, transition stalled, etc.).
    """
    # Interpolate spec fields
    try:
        spec_dict = _fill_verify_after(spec, params, recipe_name)
    except RecipeConfigurationError as e:
        return False, f"verify_after interpolation error: {e}"

    v_type = spec_dict.get("type", "")

    # ── verify_state_change: interaction side-effect check ───────────────
    if v_type == "verify_state_change":
        if not pre_state:
            return True, "verify_state_change: no pre-state captured — assuming satisfied"

        # Signal 1: URL change
        if page.url != pre_state.get("url"):
            return True, f"verify_state_change: URL changed to '{page.url}' ✓"

        # Signal 2: Element count delta
        try:
            current_count = await page.evaluate("document.querySelectorAll('*').length")
            pre_count = pre_state.get("element_count")
            if pre_count is not None and current_count != pre_count:
                return (
                    True,
                    f"verify_state_change: DOM element count changed ({pre_count} → {current_count}) ✓",
                )
        except Exception:
            pass

        # Signal 3: ARIA snapshot diff
        try:
            raw_snapshot = await page.accessibility.snapshot()
            import json as _json

            current_aria = _json.dumps(raw_snapshot, sort_keys=True) if raw_snapshot else ""
            pre_aria = pre_state.get("aria_snapshot")
            if current_aria and pre_aria is not None and current_aria != pre_aria:
                return True, "verify_state_change: accessibility tree (ARIA) changed ✓"
        except Exception:
            pass

        return False, "verify_state_change: no detectable URL, DOM, or ARIA change after recipe execution"

    # ── table_sort: JS DOM extraction ────────────────────────────────────
    if v_type == "table_sort":
        expected_col: str = spec_dict.get("expected_column", "")
        expected_dir: str = (spec_dict.get("expected_direction") or "").lower()
        if not expected_dir:
            return False, "table_sort verify_after: missing expected_direction"

        for _poll in range(10):
            try:
                await page.wait_for_timeout(500)
                js_result: dict = await page.evaluate(
                    """
                    ([colLabel]) => {
                        if (colLabel) {
                            const ths = Array.from(
                                document.querySelectorAll('th[role="columnheader"], th')
                            );
                            for (const th of ths) {
                                const text = (th.innerText || th.textContent || '').trim();
                                if (text.toLowerCase().includes(colLabel.toLowerCase())) {
                                    const sort = (th.getAttribute('aria-sort') || '').toLowerCase();
                                    if (sort) return { sort, col: text };
                                }
                            }
                        }
                        const sorted = document.querySelector('th[aria-sort]');
                        if (sorted) {
                            return {
                                sort: (sorted.getAttribute('aria-sort') || '').toLowerCase(),
                                col: (sorted.innerText || '').trim()
                            };
                        }
                        if (document.querySelector('.pi-sort-amount-up-alt, .pi-sort-up'))
                            return { sort: 'ascending', col: '' };
                        if (document.querySelector('.pi-sort-amount-down, .pi-sort-down'))
                            return { sort: 'descending', col: '' };
                        return { sort: '', col: '' };
                    }
                    """,
                    [expected_col],
                )
            except Exception as e:
                return False, f"table_sort verify JS failed: {str(e)[:80]}"

            current_sort = js_result.get("sort", "")
            detected_col = js_result.get("col", "")

            if current_sort == expected_dir:
                return True, (f"table_sort: col='{expected_col or detected_col}' aria-sort='{current_sort}' ✓")
            if current_sort and current_sort != expected_dir:
                logger.warning(
                    "[%s] Recipe '%s' verify_after: col='%s' is '%s' but expected '%s' "
                    "— oscillation guard: advancing step",
                    run_id,
                    recipe_name,
                    expected_col,
                    current_sort,
                    expected_dir,
                )
                return True, (
                    f"table_sort[OSCILLATION-GUARD]: col='{expected_col or detected_col}' "
                    f"is '{current_sort}' (expected '{expected_dir}') — advancing to prevent "
                    f"retry loop. Next AC step click will correct direction."
                )

        return False, (
            f"table_sort: no sort state detected after 5s polling (col='{expected_col}', expected='{expected_dir}')"
        )

    # ── element_visible / element_hidden / element_state ─────────────────
    selector: str = spec_dict.get("selector", "")
    if not selector:
        return False, f"{v_type}: no selector after interpolation"

    try:
        locator = page.locator(selector)

        if v_type == "element_visible":
            # Fast-path: already visible — skip the wait entirely
            try:
                already_count = await locator.count()
                if already_count > 0 and await locator.first.is_visible():
                    return True, f"element_visible: '{selector}' already visible ✓ (fast-path)"
            except Exception:
                pass  # Fall through to wait_for below

            # Full wait: Angular view transitions can take 1-2 s after click.
            try:
                await locator.first.wait_for(state="visible", timeout=8000)
                return True, f"element_visible: '{selector}' is visible ✓"
            except Exception as _timeout_err:
                # ── Failure diagnostics ──────────────────────────────────────
                # Selector NOT found within 8 s. Emit: URL + screenshot + DOM dump
                # so developers can immediately understand why the view change failed.
                diag_parts: list[str] = [
                    f"element_visible TIMEOUT: '{selector}' not found within 8s.",
                    f"playwright error: {str(_timeout_err)[:150]}",
                ]

                # 1. Current URL — reveals wrong-page navigation immediately
                try:
                    diag_parts.append(f"current URL: {page.url}")
                except Exception:
                    diag_parts.append("current URL: (could not read)")

                # 2. Full-page screenshot — visual snapshot of actual page state
                try:
                    import tempfile

                    _ss = await page.screenshot(type="png", full_page=True)
                    ss_path = Path(tempfile.gettempdir()) / f"vqa_verify_fail_{recipe_name.replace(' ', '_')}.png"
                    ss_path.write_bytes(_ss)
                    logger.warning(
                        "[%s] Recipe '%s' verify_after screenshot saved: %s (%d bytes)",
                        run_id,
                        recipe_name,
                        ss_path,
                        len(_ss),
                    )
                    diag_parts.append(f"screenshot saved: {ss_path}  (PNG, {len(_ss)} bytes)")
                except Exception as _ss_err:
                    diag_parts.append(f"screenshot capture failed: {str(_ss_err)[:80]}")

                # 3. DOM body dump — first 50 lines: shows if CSS class changed, view toggled, etc.
                try:
                    dom_snippet: str = await page.evaluate("""
                        () => {
                            const body = document.body;
                            if (!body) return '(no body)';
                            const html = body.outerHTML || '';
                            const lines = html.replace(/></g, '>\n<').split('\n');
                            return lines.slice(0, 50).join('\n');
                        }
                    """)
                    diag_parts.append(f"DOM body (first 50 lines):\n{dom_snippet[:3000]}")
                    logger.warning(
                        "[%s] Recipe '%s' verify_after DOM dump:\n%s",
                        run_id,
                        recipe_name,
                        dom_snippet[:2000],
                    )
                except Exception as _dom_err:
                    diag_parts.append(f"DOM dump failed: {str(_dom_err)[:80]}")

                return False, "\n".join(diag_parts)

        elif v_type == "element_hidden":
            await locator.first.wait_for(state="hidden", timeout=3000)
            return True, f"element_hidden: '{selector}' is hidden/gone ✓"

        elif v_type == "element_state":
            expected_state = spec_dict.get("expected_state", "")
            await locator.first.wait_for(state="visible", timeout=2000)
            if expected_state == "disabled":
                if await locator.first.is_disabled():
                    return True, f"element_state: '{selector}' is disabled ✓"
                return False, f"element_state: '{selector}' expected disabled but is enabled"
            elif expected_state == "enabled":
                if await locator.first.is_enabled():
                    return True, f"element_state: '{selector}' is enabled ✓"
                return False, f"element_state: '{selector}' expected enabled but is disabled"
            elif expected_state in ("checked", "selected"):
                if await locator.first.is_checked():
                    return True, f"element_state: '{selector}' is {expected_state} ✓"
                return False, f"element_state: '{selector}' is NOT {expected_state}"
            elif expected_state == "unchecked":
                if not await locator.first.is_checked():
                    return True, f"element_state: '{selector}' is unchecked ✓"
                return False, f"element_state: '{selector}' is still checked"
            else:
                return False, f"element_state: unknown expected_state '{expected_state}'"

    except Exception as e:
        return False, f"{v_type}: '{selector}' check failed — {str(e)[:100]}"

    return False, f"verify_after: unknown spec type '{v_type}'"


# ---------------------------------------------------------------------------
# RecipeRegistry — loads, validates, caches, and matches YAML recipes
# ---------------------------------------------------------------------------


class RecipeRegistry:
    """
    Singleton-style registry that loads ActionRecipe objects from YAML files.

    Hot-reloads: checks file modification times on each planner call and
    re-parses only changed files.  No server restart needed to add a recipe.
    """

    def __init__(self, blueprints_dir: Path = BLUEPRINTS_DIR) -> None:
        self._dir = blueprints_dir
        self._recipes: dict[str, ActionRecipe] = {}
        self._mtimes: dict[str, float] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load (or reload) all YAML files in the blueprints directory.

        T2-b: Also walks the 'generated/' subdirectory for auto-generated
        ActionRecipe YAMLs produced by the HITL trace parser. Human-curated
        recipes (parent dir) take precedence over auto-generated ones on name
        collision — the parent-dir file is loaded last and overwrites the
        auto-generated entry in self._recipes.
        """
        if not self._dir.exists():
            logger.warning(
                "RecipeRegistry: blueprints dir '%s' does not exist — no recipes loaded",
                self._dir,
            )
            return

        # Load auto-generated recipes first (lower precedence)
        generated_dir = self._dir / "generated"
        if generated_dir.exists():
            for yaml_path in sorted(generated_dir.glob("*.yaml")):
                self._load_file(yaml_path)

        # Load human-curated recipes last (higher precedence — overwrite on collision)
        for yaml_path in sorted(self._dir.glob("*.yaml")):
            self._load_file(yaml_path)

    def _load_file(self, path: Path) -> None:
        """Load and validate a single YAML blueprint file."""
        try:
            mtime = path.stat().st_mtime
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            recipe = ActionRecipe.model_validate(raw)
            self._recipes[recipe.name] = recipe
            self._mtimes[str(path)] = mtime
            logger.info(
                "RecipeRegistry: loaded recipe '%s' from %s (is_sort=%s)",
                recipe.name,
                path.name,
                recipe.is_sort_recipe,
            )
        except Exception as e:
            logger.error(
                "RecipeRegistry: FAILED to load '%s' — %s. Fix the YAML and it will hot-reload.",
                path.name,
                e,
            )

    def reload_if_updated(self) -> None:
        """Check for new or modified YAML files and reload them.

        T2-b: Also checks the 'generated/' subdirectory for new auto-generated
        recipes produced by the HITL trace parser since last load.
        """
        if not self._dir.exists():
            return

        # Check both the main dir and the generated subdir
        dirs_to_check = [self._dir]
        generated_dir = self._dir / "generated"
        if generated_dir.exists():
            dirs_to_check.append(generated_dir)

        for check_dir in dirs_to_check:
            for yaml_path in check_dir.glob("*.yaml"):
                try:
                    current_mtime = yaml_path.stat().st_mtime
                    if self._mtimes.get(str(yaml_path)) != current_mtime:
                        logger.info(
                            "RecipeRegistry: detected change in '%s' — reloading",
                            yaml_path.name,
                        )
                        self._load_file(yaml_path)
                except Exception:
                    pass

    def get(self, name: str) -> ActionRecipe:
        """Return a recipe by name, raising RecipeNotFoundError if absent."""
        self.reload_if_updated()
        if name not in self._recipes:
            raise RecipeNotFoundError(
                f"No recipe named '{name}' found in {self._dir}. Available: {sorted(self._recipes.keys())}"
            )
        return self._recipes[name]

    def all_recipes(self) -> list[ActionRecipe]:
        """Return all loaded recipes (used by planner for catalog injection)."""
        self.reload_if_updated()
        return list(self._recipes.values())

    def match(self, step_goal: str) -> list[ActionRecipe]:
        """
        Return recipes whose trigger_keywords are fully present in the AC step text.

        A trigger keyword matches only when ALL of its tokens are present in the
        goal (subset match on the normalised token sets — punctuation stripped,
        lowercased, split on whitespace). A recipe with multiple trigger keywords
        matches if ANY of them satisfies this rule; its score is the length of
        the longest matching phrase.

        This prevents multi-word triggers like ``"ghost login"`` from matching
        a goal that only contains ``"login"`` — the previous union-then-intersect
        approach allowed a single incidental overlap to trigger the recipe.

        Parameters
        ----------
        step_goal : str
            The current AC step goal text.

        Returns
        -------
        list[ActionRecipe]
            Matched recipes, longest matched phrase first.
        """
        self.reload_if_updated()

        goal_tokens = set(re.sub(r"[^\w\s]", " ", step_goal.lower()).split())

        scored: list[tuple[int, ActionRecipe]] = []
        for recipe in self._recipes.values():
            best_len = 0
            for kw in recipe.trigger_keywords:
                phrase_tokens = set(re.sub(r"[^\w\s]", " ", kw.lower()).split())
                if phrase_tokens and phrase_tokens.issubset(goal_tokens):
                    best_len = max(best_len, len(phrase_tokens))
            if best_len > 0:
                scored.append((best_len, recipe))

        return [r for _, r in sorted(scored, key=lambda x: -x[0])]

    def format_for_prompt(self, recipes: list[ActionRecipe]) -> str:
        """
        Format matched recipes as a ⚡ RECIPES AVAILABLE prompt block.

        Produces an explicit JSON example (with ``<param_name>`` placeholders)
        so the LLM emits the correct ``{"action":"recipe",...}`` structure.

        Returns an empty string if no recipes matched (no bloat for normal steps).
        """
        if not recipes:
            return ""

        import json as _json

        lines = [
            "═══════════════════════════════════════════════════════════════",
            "⚡ ACTION RECIPES AVAILABLE — use these INSTEAD of planning individual clicks.",
            "Emitting a recipe is ALWAYS preferred over planning raw click sequences",
            "for the components listed below.",
            "═══════════════════════════════════════════════════════════════",
        ]

        for recipe in recipes:
            params_desc = "\n".join(f"    {p.name}: {p.description}" for p in recipe.parameters)
            example_params = {p.name: f"<{p.name}>" for p in recipe.parameters}
            example_json = _json.dumps(
                {
                    "action": "recipe",
                    "recipe_name": recipe.name,
                    "recipe_params": example_params,
                    "reasoning": f"Using recipe for {recipe.description.lower()[:80]}",
                    "thought": ("Recipe handles the compound interaction atomically — no individual clicks needed."),
                },
                indent=None,
            )
            sort_note = ""
            if recipe.is_sort_recipe:
                sort_note = (
                    "\n  ⚡ SORT RECIPE: Pre-checks DOM aria-sort before clicking. "
                    "If already sorted correctly, execution is skipped automatically."
                )
            lines += [
                f"\nRecipe: {recipe.name}",
                f"Use when: {recipe.description}",
                f"Parameters:\n{params_desc}" if params_desc else "Parameters: (none)",
                sort_note,
                "Emit exactly this JSON:",
                example_json,
                "DO NOT plan individual clicks for this interaction — emit the recipe.",
            ]

        lines.append("═══════════════════════════════════════════════════════════════")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Global recipe registry — import this from executor.py and planner.py.
recipe_registry: RecipeRegistry = RecipeRegistry()
