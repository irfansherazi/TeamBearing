"""
vQA — Input Validators
========================
Module: backend/engine/validators.py

Pydantic-based validators for:
  1. AC step quality — catches vague, compound, or untestable steps
  2. Planned action schema — catches invalid JSON actions before executor

These are used as programmatic guardrails that intercept bad data before
it reaches the LLM or the browser, reducing flakiness caused by vague
requirements or malformed LLM output.

Architecture Context
--------------------
  ac_parser_node (graph.py)
      └─▶ validate_ac_steps()       ← catches vague/compound steps

  planner_node (planner.py)
      └─▶ validate_planned_action() ← catches bad actions before executor

Dependencies
------------
  - ``backend/engine/state.py`` — VQAState for fail count checks
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AC step quality validation
# ---------------------------------------------------------------------------

# Patterns that indicate a step is too vague to be testable
_VAGUE_PATTERNS: list[str] = [
    "works correctly",
    "functions properly",
    "as expected",
    "verify it works",
    "should work",
    "is working",
    "works fine",
    "behaves correctly",
    "operates normally",
    "is functional",
    "test the feature",
    "check functionality",
]

# Maximum step length (chars) — longer steps likely need splitting
_MAX_STEP_LENGTH = 150

# Minimum word count — shorter steps aren't actionable
_MIN_WORD_COUNT = 3

# Action verbs — if a step contains 2+ of these joined by "and", it's compound
_ACTION_VERBS: list[str] = [
    "click",
    "fill",
    "select",
    "enter",
    "type",
    "navigate",
    "open",
    "close",
    "check",
    "uncheck",
    "submit",
    "upload",
    "download",
    "verify",
    "confirm",
    "assert",
    "ensure",
    "validate",
]


def validate_ac_steps(steps: list[str]) -> tuple[list[str], list[str], list[str]]:
    """
    Validate a list of AC steps for quality and testability.

    Checks each step against vagueness patterns, length limits,
    minimum word count, and FEAT-001 semantic quality gates
    (component-specificity and observable-outcome).

    Args
    ----
    steps : list[str]
        The parsed AC steps to validate.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        (valid_steps, error_messages, warning_messages).
        valid_steps: steps that passed all hard checks.
        error_messages: human-readable descriptions of rejected steps.
        warning_messages: FEAT-001 semantic quality warnings (step is
            kept but flagged for the reporter).
        If error_messages is non-empty, the caller should retry with
        error feedback.

    Example
    -------
    >>> valid, errors, warnings = validate_ac_steps([
    ...     "Verify it works correctly",
    ...     "Click the Submit button",
    ...     "Click the button",
    ... ])
    >>> len(errors) == 1  # first step is too vague
    True
    >>> len(warnings) >= 1  # third step lacks specificity
    True
    """
    valid: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    # ── FEAT-001: Semantic quality patterns ─────────────────────────
    # Interaction verbs that require a specific target component
    _INTERACTION_VERBS = [
        "click",
        "fill",
        "type",
        "enter",
        "select",
        "choose",
        "toggle",
        "check",
        "uncheck",
        "open",
        "close",
    ]
    # Generic component references (trigger a specificity warning)
    _GENERIC_TARGETS = [
        "the button",
        "the dropdown",
        "the table",
        "the form",
        "the modal",
        "the dialog",
        "the input",
        "the field",
        "the link",
        "the menu",
        "the panel",
        "a button",
        "a dropdown",
        "a table",
        "a form",
    ]
    # Verify verbs that require a specific observable
    _VERIFY_VERBS = ["verify", "confirm", "assert", "check", "ensure", "validate"]
    # Specific observable markers (if present, no warning)
    _OBSERVABLE_MARKERS = [
        "toast",
        "url",
        "visible",
        "hidden",
        "disabled",
        "enabled",
        "appears",
        "disappears",
        "shows",
        "displays",
        "contains",
        "sorted",
        "ascending",
        "descending",
        "redirected",
        "error message",
        "success message",
        "field value",
    ]

    for i, step in enumerate(steps):
        step = step.strip()
        if not step:
            continue

        step_num = i + 1

        # Check vagueness
        step_lower = step.lower()
        for pattern in _VAGUE_PATTERNS:
            if pattern in step_lower:
                errors.append(
                    f"Step {step_num} is too vague ('{pattern}'): '{step}'. "
                    f"Rewrite with a specific observable outcome "
                    f"(e.g., 'Verify the success toast appears')."
                )
                break
        else:
            # Check length
            if len(step) > _MAX_STEP_LENGTH:
                errors.append(
                    f"Step {step_num} is too long ({len(step)} chars): '{step[:80]}...'. "
                    f"Split into multiple atomic actions."
                )
            # Check minimum word count
            elif len(step.split()) < _MIN_WORD_COUNT:
                errors.append(
                    f"Step {step_num} is too short to be actionable: '{step}'. Add specific details about what to do."
                )
            # Check for compound steps — two action verbs joined by "and"
            elif " and " in step_lower:
                parts = step_lower.split(" and ")
                verbs_per_part = [sum(1 for v in _ACTION_VERBS if v in p) for p in parts]
                if sum(1 for c in verbs_per_part if c > 0) >= 2:
                    errors.append(
                        f"Step {step_num} is compound (multiple actions joined by 'and'): "
                        f"'{step[:100]}'. "
                        f"Split into one atomic action per step so failures can be pinpointed."
                    )
                else:
                    valid.append(step)
            else:
                valid.append(step)

            # ── FEAT-001: Component-Specificity Gate (warning) ─────────
            # If the step has an interaction verb but only a generic target,
            # flag it so the reporter can show a quality badge.
            has_interaction_verb = any(v in step_lower for v in _INTERACTION_VERBS)
            has_generic_target = any(t in step_lower for t in _GENERIC_TARGETS)
            if has_interaction_verb and has_generic_target:
                warnings.append(
                    f"Step {step_num} lacks component specificity: '{step[:80]}'. "
                    f"Which {[t for t in _GENERIC_TARGETS if t in step_lower][0]}? "
                    f"Name the specific element (e.g., 'Click the Submit All button')."
                )

            # ── FEAT-001: Observable-Outcome Gate (warning) ────────────
            # If the step is a "verify" step but lacks a specific observable,
            # flag it so the reporter can show a quality badge.
            has_verify_verb = any(v in step_lower for v in _VERIFY_VERBS)
            has_specific_observable = any(m in step_lower for m in _OBSERVABLE_MARKERS)
            if has_verify_verb and not has_specific_observable:
                warnings.append(
                    f"Step {step_num} lacks observable outcome: '{step[:80]}'. "
                    f"What proves success? Specify: URL, toast text, element "
                    f"visibility, or field value."
                )

    if errors:
        logger.warning(
            "AC step validation: %d passed, %d rejected, %d warnings",
            len(valid),
            len(errors),
            len(warnings),
        )
    elif warnings:
        logger.info(
            "AC step validation: %d passed, %d warnings",
            len(valid),
            len(warnings),
        )

    return valid, errors, warnings


# ---------------------------------------------------------------------------
# Planned action schema validation
# ---------------------------------------------------------------------------

# Required fields per action type
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "click": ["strategy", "name"],
    "fill": ["strategy", "name", "value"],
    "navigate": ["value"],
    "verify": ["strategy", "name"],
    "select_option": ["strategy", "name", "value"],
    "check": ["strategy", "name"],
    "uncheck": ["strategy", "name"],
    "done": ["reasoning"],
    "wait": [],  # value is optional (defaults to 2000ms)
    "wait_for_response": [],  # value is URL pattern (optional, waits 2s if omitted)
    "scroll": [],  # value is optional (defaults to "down")
    "press_key": ["value"],  # value is the key name (e.g., 'Enter', 'Escape', 'Tab')
    "verify_table_sort": [],  # requires 'column' and 'order' — checked in executor
    "set_input_files": [],  # requires 'value' (filename) — checked in executor
    # ── Recipe — atomic compound interaction via YAML blueprint ───────────────
    # recipe_name and recipe_params are validated in executor via Pydantic.
    # Validator only checks that recipe_name is present.
    "recipe": ["recipe_name"],
    # ── PrimeNG Dropdown — atomic trigger+portal+option sequence ─────────────
    # Handles p-select, p-popover sort panels, and any PrimeNG overlay portal.
    # trigger_selector OR trigger_mark_id is validated cross-field in PlannerAction.
    "primeng_dropdown": ["target_text", "portal_class"],
    # ── Coordinate Action — vision-mode coordinate-based click/fill ───────────
    # mark_id is required — cross-field validation is in PlannerAction schema.
    "coordinate_action": ["mark_id"],
    # ── FEAT-007: Composite action types ──────────────────────────────────────
    # Combine two sequential Playwright interactions into one atomic action.
    # Cross-field validation (submit_strategy, wait_for_selector, verify_text)
    # is handled in PlannerAction schema validators.
    "fill_and_submit": ["strategy", "name", "value"],
    "click_and_wait": ["strategy", "name"],
    "select_and_verify": ["strategy", "name", "value"],
}


def validate_planned_action(action: dict[str, Any], state: dict) -> list[str]:
    """
    Validate a planned action dict for schema correctness.

    Checks:
    1. Required fields are present for each action type
    2. Forbidden patterns (e.g., get_by_role('button') without name)
    3. Blocked locators from ac_step_fail_counts
    4. Invalid URLs for navigate actions

    Args
    ----
    action : dict
        The planned action JSON from the LLM.
    state : dict
        The current VQAState (for fail count checks).

    Returns
    -------
    list[str]
        List of error strings. Empty = valid.

    Example
    -------
    >>> errors = validate_planned_action(
    ...     {"action": "click", "strategy": "get_by_role", "role": "button"},
    ...     {}
    ... )
    >>> len(errors) > 0  # missing 'name' field
    True
    """
    errors: list[str] = []
    action_type = action.get("action", "")

    if not action_type:
        errors.append("Missing 'action' field")
        return errors

    if action_type not in _REQUIRED_FIELDS:
        errors.append(f"Unknown action type: '{action_type}'. Valid types: {', '.join(_REQUIRED_FIELDS.keys())}")
        return errors

    # ── Check required fields ────────────────────────────────────────
    for field in _REQUIRED_FIELDS[action_type]:
        if not action.get(field):
            errors.append(f"Missing required field '{field}' for action '{action_type}'")

    # ── Banned patterns ──────────────────────────────────────────────

    # FORBIDDEN: get_by_role('button') without a name resolves to every button
    strategy = action.get("strategy", "")
    role = action.get("role", "")
    name = action.get("name", "")

    if strategy == "get_by_role" and not name:
        errors.append(
            f"FORBIDDEN: get_by_role('{role}') without 'name' will match EVERY "
            f"'{role}' element on the page and either crash (Playwright: Role must not "
            f"be empty) or time out. You MUST provide the element's visible text in 'name'. "
            f'Example: {{"strategy": "get_by_role", "role": "{role}", "name": "<visible text>"}}'
        )

    # FORBIDDEN: navigate with non-HTTP URL
    if action_type == "navigate":
        url = action.get("value", "")
        if url and not url.startswith("http"):
            errors.append(f"Invalid navigate URL: '{url}'. Must be a full HTTP/HTTPS URL.")

    # ── Check against forbidden locators (previously failed) ─────────
    fail_counts: dict = state.get("ac_step_fail_counts", {})
    if strategy and name:
        locator_key = f"{strategy}:{role}:{name}"
        fail_count = fail_counts.get(locator_key, 0)
        if fail_count >= 2:
            errors.append(
                f"BLOCKED: locator '{locator_key}' has already failed {fail_count}x "
                f"on this AC step. Use a different strategy (e.g., get_by_text)."
            )

        # ── Content-level block check ─────────────────────────────────────
        # If a STRICT_MODE_VIOLATION with 0-visible returned for this element
        # NAME, ALL locator strategies targeting this name are blocked
        # regardless of strategy/role. Catch it here before Playwright fires.
        content_block_key = f"__content__:{name}"
        content_block_count = fail_counts.get(content_block_key, 0)
        if content_block_count >= 1:
            errors.append(
                f"CONTENT-LEVEL BLOCK: '{name}' has {content_block_count}x STRICT_MODE_VIOLATION "
                f"with 0 visible elements — every unscoped locator targeting this text is forbidden. "
                f"You MUST add a container_selector to scope to a visible ancestor, "
                f"OR use the vqa_id from the INTERACTIVE ELEMENTS list."
            )

    # ── Block excessive consecutive scrolls ──────────────────────────
    # The LLM consistently plans "scroll" despite rules saying NEVER scroll.
    # This is a hard programmatic block — if the last 2+ actions were scrolls,
    # reject the scroll and force the LLM to try something else.
    if action_type == "scroll":
        action_history = state.get("detailed_execution_log", [])
        consecutive_scrolls = 0
        for step in reversed(action_history):
            if step.get("action_type") == "scroll":
                consecutive_scrolls += 1
            else:
                break
        if consecutive_scrolls >= 2:
            errors.append(
                f"BLOCKED: {consecutive_scrolls} consecutive scrolls detected. "
                f"Scrolling does NOT reveal more table data — vSuite tables use PrimeNG pagination. "
                f"You MUST use table_search to filter the table to your target row, "
                f"OR click the 'Next Page' button at the bottom of the table. "
                f"NEVER scroll again until you have tried table_search or pagination."
            )

    # ── Block consecutive identical (action, locator) repeats ────────
    # Pure Python enforcement — the LLM saw the INFINITE LOOP banner in the prompt
    # and still repeated the action. Hard-block it at the validator tier.
    # Threshold: block on 3rd identical consecutive action (above 2 is loop territory).
    _HARD_REPEAT_LIMIT = 3
    if action_type not in ("done", "wait", "wait_for_response"):
        action_history = state.get("detailed_execution_log", [])
        if action_history:
            planned_fp = f"{action_type}|{action.get('name', '')}"
            consecutive_repeats = 0
            for step in reversed(action_history):
                step_fp = f"{step.get('action_type', '')}|{step.get('locator_value', '')}"
                if step_fp == planned_fp and planned_fp != "|":
                    consecutive_repeats += 1
                else:
                    break
            if consecutive_repeats >= _HARD_REPEAT_LIMIT:
                errors.append(
                    f"HARD BLOCKED (Python-level): action '{action_type}' on '{action.get('name', '')}' "
                    f"has been attempted {consecutive_repeats} consecutive times and NEVER succeeded. "
                    f"This exact action is permanently forbidden until you try a different approach. "
                    f"You MUST choose a structurally different action — different action type, "
                    f"different target, or emit 'done' if the goal is already achieved."
                )

    if errors:
        logger.warning(
            "Action validation failed: %s → %s",
            action_type,
            "; ".join(errors),
        )

    return errors
