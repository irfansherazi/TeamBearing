"""
vQA — FormWorker (Phase 3)
============================
Module: backend/engine/workers/form_worker.py

Specialised Worker for **form filling, dropdown selection, date pickers,
and form submission** in vSuite's Angular + PrimeNG forms.

Problem
-------
The GenericWorker delegates directly to the standard ``planner_node``,
which has no awareness of PrimeNG composite component hierarchy.  When
an AC step says "Select 'Radio Commercial' from Ad Type", the planner
may click the wrong element (the label vs. the dropdown trigger vs.
the overlay panel) because PrimeNG components have deeply nested DOM
structures.

Solution
--------
The FormWorker injects a ``<FORM_INTERACTION_RULES>`` system prompt
block that:

1. **Teaches** PrimeNG component recognition (``p-select``, ``p-calendar``,
   ``p-multiselect``, ``p-autocomplete``)
2. **Enforces** child-input fallback: click label → find child ``<input>``
3. **Adds** batch fill guidance for consecutive fill actions
4. **Prioritizes** ``primeng_dropdown`` action for any dropdown/select

Dependencies
------------
  - ``backend.engine.planner.planner_node`` — the existing SEE-THINK node
  - ``backend.engine.state.VQAState``       — state schema

See Also
--------
  - ``backend/engine/workers/generic_worker.py``  — the generic fallback
  - ``backend/engine/supervisor.py``              — emits Intent with worker_type="form"
"""

from __future__ import annotations

import json
import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FORM_INTERACTION_RULES — injected into the planner's user_guidance
# ---------------------------------------------------------------------------

_FORM_INTERACTION_RULES: str = """\
<FORM_INTERACTION_RULES>
You are a **Form Interaction Specialist** operating on vSuite's Angular + \
PrimeNG forms.

## PrimeNG Component Hierarchy

PrimeNG form components have deeply nested DOM structures.  The visible \
label, the trigger button, and the actual input are DIFFERENT elements:

| Component | Visible Text | Actual Target | Action |
|-----------|-------------|---------------|--------|
| p-select (dropdown) | Label text | The `<p-select>` or its trigger | `primeng_dropdown` |
| p-calendar (date) | Date text | The `<input>` inside p-calendar | `fill` on the input |
| p-multiselect | Chip labels | The `<p-multiselect>` trigger | `primeng_dropdown` |
| p-autocomplete | Suggestion text | The `<input>` inside p-autocomplete | `fill` then select |
| p-inputtext | Placeholder | The `<input>` element | `fill` |
| p-checkbox | Label text | The checkbox input | `click` |

## CRITICAL RULE #1: Use primeng_dropdown for ALL Dropdowns

When the AC step says "select X from Y dropdown" or "choose X":
1. **DO NOT** use standard `click` on dropdown options
2. **USE** the `primeng_dropdown` action type
3. **Set** `dropdown_label` to the field label (e.g., "Ad Type")
4. **Set** `option_text` to the option to select (e.g., "Radio Commercial")

## CRITICAL RULE #2: Child-Input Fallback

If a `fill` action fails because the target is a label/wrapper:
1. Look for a child `<input>`, `<textarea>`, or editable element
2. Use `get_by_role('textbox')` or `get_by_role('combobox')` scoped to \
the field container
3. Never try to `fill` a `<div>` or `<span>` — find the actual input

## CRITICAL RULE #3: Batch Awareness

When multiple consecutive AC sub-steps fill fields in the same form:
- Fill fields in the order given
- Do NOT submit between fills
- Wait for any async validation after each fill
- Submit only when the AC step explicitly says "submit", "save", or "click Submit"

## Form Submission Patterns

- "Submit" / "Save" / "Create" → click the primary action button
- "Cancel" → click the Cancel/Close button
- "Reset" → click Reset or clear all fields
</FORM_INTERACTION_RULES>
"""


def _format_form_intent_context(intent: dict) -> str:
    """
    Format a SupervisorIntent as a FormWorker-specific context block.

    Includes ``<FORM_INTERACTION_RULES>`` for PrimeNG awareness.
    """
    target = intent.get("target", "Unknown Form")
    action = intent.get("action", "fill")
    data = intent.get("data", {})

    lines = [
        "[SUPERVISOR INTENT — FORM WORKER]",
        f"Target: {target}",
        f"Action: {action}",
    ]
    if data:
        lines.append(f"Data: {json.dumps(data, indent=2)}")

    intent_header = "\n".join(lines)
    return f"{intent_header}\n\n{_FORM_INTERACTION_RULES}"


async def form_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: FormWorker — execute form-related Intents with
    PrimeNG component awareness.

    This specialised Worker:

    1. Reads the latest Intent from ``supervisor_intents``
    2. Injects ``<FORM_INTERACTION_RULES>`` into the planner's guidance
    3. Delegates to ``planner_node`` for DOM-level execution

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update from planner_node.
    """
    from backend.engine.planner import planner_node

    run_id: str = state["run_id"]
    intents: list[dict] = state.get("supervisor_intents", [])

    if not intents:
        logger.warning(
            "[%s] FormWorker: no supervisor intents — falling back to generic planner",
            run_id,
        )
        return await planner_node(state)

    latest_intent = intents[-1]
    intent_id = latest_intent.get("intent_id", "unknown")

    logger.info(
        "[%s] FormWorker: executing intent '%s' (target=%s, action=%s)",
        run_id,
        intent_id,
        latest_intent.get("target", "?"),
        latest_intent.get("action", "?"),
    )

    # Inject FORM_INTERACTION_RULES into user_guidance
    form_context = _format_form_intent_context(latest_intent)
    existing_guidance = state.get("user_guidance", "")

    if existing_guidance:
        combined_guidance = f"{form_context}\n\n{existing_guidance}"
    else:
        combined_guidance = form_context

    modified_state = {**state, "user_guidance": combined_guidance}

    result = await planner_node(modified_state)

    logger.info(
        "[%s] FormWorker: planner_node returned action=%s",
        run_id,
        result.get("planned_action", {}).get("action", "unknown"),
    )

    return result
