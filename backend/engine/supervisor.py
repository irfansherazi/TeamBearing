"""
vQA — Supervisor Node (Intent Classifier)
============================================
Module: backend/engine/supervisor.py

Implements the **Supervisor** layer of the Supervisor-Worker hierarchy.

The Supervisor is a lightweight orchestration node that sits above the
existing planner→executor→evaluator loop.  It does NOT interact with
the DOM or take screenshots.  Its sole job is:

    1. Read the current AC step text
    2. Interpolate any ``<TOKEN>`` placeholders from ``global_variables``
    3. Call Claude 3.5 Haiku to classify the step into a structured Intent
    4. Write the Intent to ``supervisor_intents`` for the dispatcher

The Intent is an abstract JSON object that tells the dispatcher WHICH
Worker sub-graph should handle this step.  The Worker then uses the
existing planner (Sonnet-powered, vision-capable) to figure out HOW
to physically execute it on the DOM.

Design Decisions
----------------
  - **Haiku, not Sonnet** — The Supervisor does zero visual processing.
    Haiku is 5x faster and ~80% cheaper than Sonnet for pure text→JSON
    classification.  Sonnet is reserved for Workers who need vision.

  - **Tool-use for structured output** — Uses Bedrock ``toolConfig``
    with a ``classify_intent`` tool schema to force Claude to return
    valid JSON.  No regex parsing, no prompt-engineering fragility.

  - **Graceful degradation** — If the Supervisor LLM call fails, it
    emits a fallback "generic" intent that routes to the GenericWorker,
    which wraps the existing planner loop.  The run never crashes due
    to a Supervisor classification error.

  - **Token interpolation** — The Supervisor replaces ``<ORDER_ID>``
    etc. with values from ``global_variables`` BEFORE classification.
    This means the Worker sees concrete values, not abstract tokens.

Dependencies
------------
  - ``langchain_aws.ChatBedrockConverse`` — Haiku LLM calls
  - ``backend.config.settings``           — AWS region, model overrides
  - ``backend.engine.state.VQAState``     — state schema

See Also
--------
  - ``backend/engine/workers/generic_worker.py`` — receives and executes Intents
  - ``backend/engine/graph.py``                  — ``build_supervisor_graph()``
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from backend.engine.state import VQAState
from backend.engine.prompt_fragments import GOLDEN_RULES

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# LLM factory — delegates to centralized provider
# ---------------------------------------------------------------------------


def _get_supervisor_llm():
    """
    Create an LLM client for the Supervisor.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Uses the ``supervisor`` purpose preset (1024 max_tokens, temp=0).
    """
    from backend.llm import get_llm

    return get_llm("supervisor")


# ---------------------------------------------------------------------------
# Token interpolation
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"<(\w+)>")


def interpolate_tokens(step_text: str, global_vars: dict[str, str]) -> str:
    """
    Replace ``<TOKEN_NAME>`` placeholders with actual values from global memory.

    Tokens that are NOT present in ``global_vars`` are left unchanged
    (the ``<TOKEN>`` placeholder is preserved in the output).

    Args
    ----
    step_text : str
        The AC step text potentially containing ``<TOKEN>`` placeholders.
    global_vars : dict[str, str]
        The current ``global_variables`` from VQAState.

    Returns
    -------
    str
        The step text with known tokens replaced.

    Example
    -------
    >>> interpolate_tokens("Click order <ORDER_ID>", {"ORDER_ID": "VC-123"})
    'Click order VC-123'
    >>> interpolate_tokens("Click <MISSING>", {})
    'Click <MISSING>'
    """
    if not global_vars:
        return step_text

    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        return global_vars.get(key, match.group(0))  # Keep placeholder if not found

    return _TOKEN_PATTERN.sub(_replacer, step_text)


# ---------------------------------------------------------------------------
# Intent classification prompt + tool schema
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    GOLDEN_RULES
    + """\
<IDENTITY>
You are the Supervisor of the vQA multi-agent browser testing system for vSuite
(a media production management platform built with Angular + PrimeNG).
Your ONLY job: classify ONE AC step into a structured Intent for the Worker dispatcher.
You do NOT interact with the DOM, take screenshots, or execute actions.
</IDENTITY>

<WORKER_TYPES>
  - "form"      — Fill fields, submit forms, interact with dropdowns, \
checkboxes, date pickers, or any form control.
  - "table"     — Click rows, paginate, sort columns, filter table data, \
verify row content.
  - "verify"    — Check that UI elements are visible, contain expected text, \
or are in a specific state. Read-only — no mutation.
  - "navigate"  — Go to a URL, click navigation links/buttons, switch pages, \
open side panels. Pure navigation with no data entry.
  - "auth"      — Login, logout, switch user roles, verify authentication state.
</WORKER_TYPES>

<CLASSIFICATION_RULES>
1. Each AC step maps to EXACTLY ONE worker_type.
2. If the step mentions filling fields AND clicking submit, use "form".
3. If the step mentions verifying visible text or element presence, use "verify".
4. If the step mentions switching roles or logging in as a different user, use "auth".
5. If unsure, default to "form" — it is the most capable worker.
6. The "target" should name the UI surface (e.g., "Quick Order Form", \
"Production Orders Table", "Login Page").
7. The "action" should be an abstract verb: "fill", "submit", "click_row", \
"sort", "verify_visible", "verify_text", "navigate", "login", "switch_role".
8. Put field-value pairs in "data" for form steps.
9. List any <TOKEN> placeholders in "preconditions" that the step requires.
</CLASSIFICATION_RULES>

<CRITICAL_REMINDER>
Respond by calling the classify_intent tool with ONE structured JSON object.
Do NOT output free text. Call the tool — do not describe what you would do.
Map the AC step to EXACTLY ONE worker_type from the list above.
</CRITICAL_REMINDER>
"""
)


# Bedrock toolConfig schema for structured output
_CLASSIFY_TOOL_SCHEMA: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "classify_intent",
                "description": ("Classify an AC step into a structured Intent for the Worker dispatcher."),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "worker_type": {
                                "type": "string",
                                "enum": ["form", "table", "verify", "navigate", "auth"],
                                "description": "Which specialised Worker should handle this step.",
                            },
                            "target": {
                                "type": "string",
                                "description": (
                                    "The UI surface or component this step targets. "
                                    "E.g., 'Quick Order Form', 'Production Orders Table'."
                                ),
                            },
                            "action": {
                                "type": "string",
                                "description": (
                                    "Abstract verb: fill, submit, click_row, sort, "
                                    "verify_visible, verify_text, navigate, login, switch_role."
                                ),
                            },
                            "data": {
                                "type": "object",
                                "description": (
                                    "Worker-specific payload. Field-value pairs for forms, "
                                    "row criteria for tables, URL for navigation, etc."
                                ),
                            },
                            "preconditions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "global_variables keys that must exist before dispatch. "
                                    "E.g., ['ORDER_ID'] if the step references <ORDER_ID>."
                                ),
                            },
                        },
                        "required": ["worker_type", "target", "action"],
                    }
                },
            }
        }
    ],
    "toolChoice": {"tool": {"name": "classify_intent"}},
}


# ---------------------------------------------------------------------------
# Intent classification (LLM call)
# ---------------------------------------------------------------------------


async def _classify_intent(
    ac_step: str,
    global_vars: dict[str, str],
    run_id: str = "",
) -> dict[str, Any]:
    """
    Call Haiku to classify an AC step into a structured Intent.

    Uses Bedrock toolConfig to force structured JSON output.
    Falls back to a generic "form" intent if the LLM call fails.

    Args
    ----
    ac_step : str
        The (interpolated) AC step text.
    global_vars : dict[str, str]
        Current global variables — used to list available tokens.
    run_id : str
        Run ID for log correlation.

    Returns
    -------
    dict
        SupervisorIntent dict with keys: intent_id, worker_type,
        target, action, data, preconditions.
    """
    intent_id = f"intent-{uuid.uuid4().hex[:8]}"

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _get_supervisor_llm()

        # Build user message — wrap ac_step in XML tag for clear context boundary
        available_vars = f"\n<GLOBAL_VARIABLES>{json.dumps(global_vars)}</GLOBAL_VARIABLES>" if global_vars else ""
        user_msg = f"<AC_STEP>{ac_step}</AC_STEP>{available_vars}"


        response = await llm.ainvoke(
            [
                SystemMessage(content=_CLASSIFY_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ],
            config={"configurable": {}},
            **_CLASSIFY_TOOL_SCHEMA,
        )

        # Extract tool call result from response
        tool_input = _extract_tool_input(response)

        intent = {
            "intent_id": intent_id,
            "worker_type": tool_input.get("worker_type", "form"),
            "target": tool_input.get("target", "Unknown"),
            "action": tool_input.get("action", "interact"),
            "data": tool_input.get("data", {}),
            "preconditions": tool_input.get("preconditions", []),
        }

        logger.info(
            "[%s] Supervisor: classified '%s' → worker=%s, target=%s, action=%s",
            run_id,
            ac_step[:80],
            intent["worker_type"],
            intent["target"],
            intent["action"],
        )
        return intent

    except Exception as exc:
        logger.warning(
            "[%s] Supervisor: LLM classification failed (%s) — emitting fallback 'form' intent",
            run_id,
            str(exc)[:120],
        )
        return {
            "intent_id": intent_id,
            "worker_type": "form",
            "target": "Unknown",
            "action": "interact",
            "data": {},
            "preconditions": [],
        }


def _extract_tool_input(response) -> dict[str, Any]:
    """
    Extract the tool call input JSON from a ChatBedrockConverse response.

    Handles both LangChain's ``tool_calls`` attribute and the raw Bedrock
    response format with ``content[].toolUse``.

    Args
    ----
    response : AIMessage
        The response from ChatBedrockConverse.

    Returns
    -------
    dict
        The parsed tool input JSON.
    """
    # LangChain tool_calls attribute (preferred path)
    if hasattr(response, "tool_calls") and response.tool_calls:
        return response.tool_calls[0].get("args", {})

    # Raw content blocks fallback
    content = getattr(response, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and "toolUse" in block:
                return block["toolUse"].get("input", {})
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("input", {})

    # Last resort: try to parse the text content as JSON
    text = str(content) if content else ""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    logger.warning("supervisor: could not extract tool input from response")
    return {}


# ---------------------------------------------------------------------------
# LangGraph Node
# ---------------------------------------------------------------------------


async def supervisor_node(state: VQAState) -> dict:
    """
    LangGraph node: Supervisor — classify the current AC step into a
    structured Intent and dispatch it to the appropriate Worker.

    This node is the entry point of the Supervisor-Worker hierarchy.
    It replaces the direct ``login → planner`` edge with
    ``login → supervisor → [worker routing]``.

    Processing:
    1. Read the current AC step from ``jira_ticket.acceptance_criteria_steps``
    2. Interpolate ``<TOKEN>`` placeholders from ``global_variables``
    3. Call Haiku to classify the step into a SupervisorIntent
    4. Check preconditions (all required tokens must exist in global_variables)
    5. Write the Intent to ``supervisor_intents``

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update:
        - ``supervisor_intents``: list with the new Intent dict (appended)
    """
    run_id: str = state["run_id"]
    ac_steps: list[str] = state["jira_ticket"].get("acceptance_criteria_steps", [])
    ac_index: int = state.get("ac_step_index", 0)
    global_vars: dict = state.get("global_variables", {})

    # Guard: no AC steps parsed yet
    if not ac_steps:
        logger.warning(
            "[%s] Supervisor: no AC steps available — emitting no-op intent",
            run_id,
        )
        return {"supervisor_intents": []}

    # Guard: index out of range (all steps complete)
    if ac_index >= len(ac_steps):
        logger.info(
            "[%s] Supervisor: ac_step_index (%d) >= total steps (%d) — all steps complete",
            run_id,
            ac_index,
            len(ac_steps),
        )
        return {"supervisor_intents": []}

    current_step: str = ac_steps[ac_index]

    logger.info(
        "[%s] Supervisor: classifying AC step %d/%d — '%.100s'",
        run_id,
        ac_index + 1,
        len(ac_steps),
        current_step,
    )

    # 1. Token interpolation
    interpolated_step = interpolate_tokens(current_step, global_vars)
    if interpolated_step != current_step:
        logger.info(
            "[%s] Supervisor: token interpolation applied — '%.100s'",
            run_id,
            interpolated_step,
        )

    # 2. Classify into Intent
    intent = await _classify_intent(interpolated_step, global_vars, run_id)

    # 3. Check preconditions
    missing = [k for k in intent.get("preconditions", []) if k not in global_vars]
    if missing:
        logger.warning(
            "[%s] Supervisor: preconditions not met — missing tokens: %s. "
            "Proceeding anyway (Worker may need to extract them first).",
            run_id,
            missing,
        )

    return {"supervisor_intents": [intent]}
