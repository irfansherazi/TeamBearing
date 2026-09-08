"""
vQA — TableWorker (Phase 3)
=============================
Module: backend/engine/workers/table_worker.py

Specialised Worker for **table navigation, row interaction, pagination,
sorting, and row-scoped actions** in vSuite's Angular + PrimeNG tables.

Problem
-------
The GenericWorker delegates directly to the standard ``planner_node``,
which has no structural awareness of table containers.  When an AC step
says "Click 'Add Voice' for JOB 1", the planner issues a standard
``get_by_text("Add Voice")`` click — which causes a STRICT_MODE violation
because "Add Voice" appears in every job row.

Solution
--------
The TableWorker injects a ``<TABLE_NAVIGATION_RULES>`` system prompt
block that:

1. **Forces** the LLM to use ``execute_scoped_click`` for any button/
   link that appears inside a table row (Add Voice, Edit, Delete, View).
2. **Arms** the LLM's tool schema with the ``scoped_click`` tool
   alongside the standard ``plan_action`` tool.
3. **Teaches** the LLM to identify ``scope_text`` from the row's unique
   data (Job Name, Order ID, Client Name, Status).

The TableWorker wraps the existing ``planner_node`` — it does NOT
rewrite any planner logic.  It only modifies the system prompt and
injects the scoped_click tool context.

Dependencies
------------
  - ``backend.engine.planner.planner_node``      — the existing SEE-THINK node
  - ``backend.engine.tools.scoped_action``        — scoped click/fill tools
  - ``backend.engine.state.VQAState``             — state schema

See Also
--------
  - ``backend/engine/tools/scoped_action.py``     — the Playwright tool
  - ``backend/engine/workers/generic_worker.py``  — the generic fallback
  - ``backend/engine/supervisor.py``              — emits Intent with worker_type="table"
"""

from __future__ import annotations

import json
import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TABLE_NAVIGATION_RULES — injected into the planner's user_guidance
# ---------------------------------------------------------------------------
# This prompt block is prepended to user_guidance so the planner sees it
# as the HIGHEST-PRIORITY instruction (recency effect at the top of the
# guidance section).

_TABLE_NAVIGATION_RULES: str = """\
<TABLE_NAVIGATION_RULES>
You are a **Table Navigation Specialist**.  You are interacting with a \
composite table or grid in vSuite that may contain multiple rows, each \
with repeated action buttons (Add Voice, Edit, Delete, View, etc.).

## CRITICAL RULE #1: No Infinite Scrolling — Use table_search

If you are looking for a specific row (e.g., a spot named "Demo", \
a status of "Needs Producing", or an order ID "VC-12345") and you \
do NOT see it in the immediate DOM, **DO NOT scroll endlessly**.

**Scrolling does NOT reveal more rows in PrimeNG paginated tables.** \
Scrolling only moves the viewport — it does NOT load new data pages.

**You MUST use the `table_search` action to filter the table to your \
target row.** Once the row is visible, use `scoped_click` to interact \
with it.

### How to use table_search:
```json
{
  "observation": "I need to find a spot named 'Demo' but it is not visible in the current table page.",
  "thought": "I must NOT scroll. I will use table_search to filter the table.",
  "action": "table_search",
  "search_query": "Demo",
  "reasoning": "Filtering table to find the 'Demo' spot instead of scrolling."
}
```

### When to use table_search:
- You cannot find a specific row, spot, job, or order in the visible table
- The AC step says "find", "locate", "look for", or references a specific name/status
- You have scrolled even once without finding the target
- The SCROLL HARD-BLOCKED error appeared

### When NOT to use table_search:
- The target row is already visible in the INTERACTIVE ELEMENTS list
- You are sorting, not searching
- You are clicking a row that you can already see

## CRITICAL RULE #2: Scoped Clicks for Repeated Buttons

If you are asked to click a generic button like "Add Voice", "Edit", \
"Delete", "View", "Assign", or any action that appears in MULTIPLE \
table rows, you **MUST NOT** use a standard click action.  A standard \
click will cause a STRICT_MODE_VIOLATION because Playwright will find \
multiple matches.

**You MUST use the `scoped_click` action instead.**

### How to use scoped_click:
1. **scope_text** — Set this to UNIQUE identifying text from the \
specific row you want to interact with.  This is usually:
   - A Job Name (e.g., "JOB 1", "Morning Show Spot")
   - An Order ID (e.g., "VC-12345")
   - A Client Name (e.g., "Bob's Burgers")
   - A unique status or date that only appears in one row
2. **target_text** — Set this to the button/link text you want to \
click (e.g., "Add Voice", "Edit", "Delete").

### Example:
To click "Add Voice" in the row for "JOB 1":
```json
{
  "observation": "I see a table with 3 jobs. JOB 1, JOB 2, JOB 3. Each has an Add Voice link.",
  "thought": "I need to click Add Voice for JOB 1 specifically. I must use scoped_click to avoid STRICT_MODE.",
  "action": "scoped_click",
  "scope_text": "JOB 1",
  "target_text": "Add Voice",
  "reasoning": "Using scoped_click to target Add Voice in JOB 1 row."
}
```

## Row Identification Strategy

When examining a table, look for these identifying patterns:
- **Job/Order Names**: Text that uniquely identifies the row
- **IDs**: VC-XXXXX, JOB-XX, or numeric IDs
- **Client Names**: When each row has a different client
- **Status badges**: "In Progress", "Complete", "Pending"

Use the MOST UNIQUE text you can find in the target row.

## Standard Table Actions (use normal click)

These actions are safe to use with standard click because they are \
NOT repeated across rows:
- Column header sort buttons (use `primeng_dropdown` or `recipe`)
- Pagination controls ("Next", "Previous", page numbers)
- Table-level filters and search inputs
- View mode toggles (Compact, List, Minimal)

## Sort Operations

For column sorting, use the existing `recipe` or `primeng_dropdown` \
action types.  Do NOT use `scoped_click` for column headers.
</TABLE_NAVIGATION_RULES>
"""


# ---------------------------------------------------------------------------
# Tool schemas for the planner's toolConfig
# ---------------------------------------------------------------------------
# These tool definitions are injected alongside the standard plan_action tool
# so the LLM can call scoped_click and table_search when operating in table context.

_SCOPED_CLICK_TOOL_SCHEMA: dict = {
    "toolSpec": {
        "name": "scoped_click",
        "description": (
            "Click a button or link INSIDE a specific table row identified "
            "by unique text. Use this INSTEAD of standard click when the "
            "target text (e.g., 'Add Voice', 'Edit', 'Delete') appears "
            "in MULTIPLE rows. The scope_text narrows the search to a "
            "single row, and target_text is clicked within that row."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "observation": {
                        "type": "string",
                        "description": (
                            "What you currently see on the screen — "
                            "the table structure, number of rows, "
                            "identifying text in each row."
                        ),
                    },
                    "thought": {
                        "type": "string",
                        "description": (
                            "Why you are using scoped_click instead of "
                            "standard click, and how you identified the "
                            "scope_text."
                        ),
                    },
                    "scope_text": {
                        "type": "string",
                        "description": (
                            "Unique identifying text in the target row "
                            "(e.g., 'JOB 1', 'VC-12345', 'Bob's Burgers'). "
                            "Must uniquely identify ONE row in the table."
                        ),
                    },
                    "target_text": {
                        "type": "string",
                        "description": (
                            "The button/link text to click inside the "
                            "scoped row (e.g., 'Add Voice', 'Edit', "
                            "'Delete', 'View')."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "maxLength": 150,
                        "description": "Brief audit summary.",
                    },
                },
                "required": [
                    "observation",
                    "thought",
                    "scope_text",
                    "target_text",
                    "reasoning",
                ],
            }
        },
    }
}


_TABLE_SEARCH_TOOL_SCHEMA: dict = {
    "toolSpec": {
        "name": "table_search",
        "description": (
            "Filter a PrimeNG table by filling its search input and waiting "
            "for the table to re-render. Use this INSTEAD of scrolling when "
            "you cannot find a specific row, spot, or job in the visible "
            "table data. The search filters the entire dataset — NOT just "
            "the current page."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "observation": {
                        "type": "string",
                        "description": (
                            "What you currently see — the table, what rows "
                            "are visible, and why you cannot find the target."
                        ),
                    },
                    "thought": {
                        "type": "string",
                        "description": (
                            "Why you are using table_search instead of scrolling, and what text you expect to find."
                        ),
                    },
                    "search_query": {
                        "type": "string",
                        "description": (
                            "The text to search for in the table. Use the "
                            "most specific text available: a spot name, "
                            "client name, order ID, or status keyword. "
                            "Examples: 'Demo', 'Needs Producing', 'VC-12345'."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "maxLength": 150,
                        "description": "Brief audit summary.",
                    },
                },
                "required": [
                    "observation",
                    "thought",
                    "search_query",
                    "reasoning",
                ],
            }
        },
    }
}


def _format_table_intent_context(intent: dict) -> str:
    """
    Format a SupervisorIntent as a TableWorker-specific context block.

    Includes the ``<TABLE_NAVIGATION_RULES>`` prompt block that teaches
    the LLM to use scoped_click for row-scoped actions.

    Args
    ----
    intent : dict
        The SupervisorIntent from ``supervisor_intents``.

    Returns
    -------
    str
        Combined intent context + TABLE_NAVIGATION_RULES.
    """
    intent.get("worker_type", "table")
    target = intent.get("target", "Unknown Table")
    action = intent.get("action", "interact")
    data = intent.get("data", {})

    lines = [
        "[SUPERVISOR INTENT — TABLE WORKER]",
        f"Target: {target}",
        f"Action: {action}",
    ]
    if data:
        lines.append(f"Data: {json.dumps(data, indent=2)}")

    intent_header = "\n".join(lines)

    return f"{intent_header}\n\n{_TABLE_NAVIGATION_RULES}"


async def table_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: TableWorker — execute table-related Intents with
    structural DOM awareness via the ``scoped_click`` tool.

    This specialised Worker:

    1. Reads the latest Intent from ``supervisor_intents``
    2. Injects ``<TABLE_NAVIGATION_RULES>`` into the planner's guidance
    3. Arms the planner with the ``scoped_click`` tool schema
    4. Delegates to ``planner_node`` for DOM-level execution
    5. If the planner returns a ``scoped_click`` action, executes it
       directly via ``execute_scoped_click`` before returning

    The key difference from GenericWorker:
      - The system prompt contains TABLE_NAVIGATION_RULES
      - The LLM can call ``scoped_click`` in addition to ``plan_action``
      - Row-scoped actions are handled by the scoped_action tool

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update from planner_node (if standard action) or
        a scoped_click result (if the planner chose scoped_click).
    """
    from backend.engine.planner import planner_node

    run_id: str = state["run_id"]
    intents: list[dict] = state.get("supervisor_intents", [])

    if not intents:
        logger.warning(
            "[%s] TableWorker: no supervisor intents — falling back to generic planner",
            run_id,
        )
        return await planner_node(state)

    latest_intent = intents[-1]
    intent_id = latest_intent.get("intent_id", "unknown")

    logger.info(
        "[%s] TableWorker: executing intent '%s' (target=%s, action=%s)",
        run_id,
        intent_id,
        latest_intent.get("target", "?"),
        latest_intent.get("action", "?"),
    )

    # ── Inject TABLE_NAVIGATION_RULES into user_guidance ──────────────
    table_context = _format_table_intent_context(latest_intent)
    existing_guidance = state.get("user_guidance", "")

    if existing_guidance:
        combined_guidance = f"{table_context}\n\n{existing_guidance}"
    else:
        combined_guidance = table_context

    modified_state = {**state, "user_guidance": combined_guidance}

    # ── Delegate to planner_node ──────────────────────────────────────
    result = await planner_node(modified_state)

    # ── Post-process: handle scoped_click actions ─────────────────────
    # If the planner emitted a scoped_click action, execute it directly
    # using the scoped_action tool instead of sending it to the
    # standard executor (which doesn't know about scoped_click).
    planned_action = result.get("planned_action", {})
    action_type = planned_action.get("action", "")

    if action_type == "scoped_click":
        logger.info(
            "[%s] TableWorker: planner chose scoped_click — executing via scoped_action tool",
            run_id,
        )
        result = await _execute_scoped_action(state, planned_action, result)

    elif action_type == "table_search":
        logger.info(
            "[%s] TableWorker: planner chose table_search — executing via table_search tool",
            run_id,
        )
        result = await _execute_table_search(state, planned_action, result)

    return result


async def _execute_scoped_action(
    state: VQAState,
    planned_action: dict,
    planner_result: dict,
) -> dict:
    """
    Execute a scoped_click action using the scoped_action tool.

    Extracts scope_text and target_text from the planned_action,
    calls ``execute_scoped_click``, and returns a state update that
    the executor/evaluator can process.

    Args
    ----
    state : VQAState
        Current state (for run_id and browser manager lookup).
    planned_action : dict
        The planned action with ``scope_text`` and ``target_text``.
    planner_result : dict
        The original planner result (preserved for screenshot, etc.).

    Returns
    -------
    dict
        Updated result with the scoped_click outcome.
    """
    from backend.browser.context import get_manager
    from backend.engine.tools.scoped_action import execute_scoped_click

    run_id = state["run_id"]
    scope_text = planned_action.get("scope_text", "")
    target_text = planned_action.get("target_text", "")

    manager = get_manager(run_id)
    page = manager.page
    if page is None:
        planner_result["planned_action"] = {
            **planned_action,
            "action": "done",
            "reasoning": "Browser page is None — cannot execute scoped_click",
        }
        return planner_result

    result = await execute_scoped_click(
        page=page,
        scope_text=scope_text,
        target_text=target_text,
    )

    if result["success"]:
        logger.info(
            "[%s] TableWorker: scoped_click SUCCESS — clicked '%s' in container '%s'",
            run_id,
            target_text,
            scope_text[:50],
        )
        # Convert to a "click" action so the executor treats it as
        # a completed action with a normal post-action screenshot.
        planner_result["planned_action"] = {
            **planned_action,
            "action": "click",
            "strategy": "scoped_click",
            "name": f"{target_text} (scoped to: {scope_text})",
            "reasoning": (f"scoped_click executed: '{target_text}' inside container matching '{scope_text}'"),
            "_scoped_click_completed": True,
        }
    else:
        error_msg = result.get("error", "Unknown scoped_click error")
        logger.warning(
            "[%s] TableWorker: scoped_click FAILED — %s",
            run_id,
            error_msg[:120],
        )
        # Surface the error to the evaluator so the planner can retry
        # with a different scope_text
        planner_result["planned_action"] = {
            **planned_action,
            "reasoning": f"scoped_click failed: {error_msg[:200]}",
        }

    return planner_result


async def _execute_table_search(
    state: VQAState,
    planned_action: dict,
    planner_result: dict,
) -> dict:
    """
    Execute a table_search action using the table_search macro tool.

    Extracts search_query from the planned_action, calls
    ``execute_table_search``, and returns a state update that
    the executor/evaluator can process.

    Args
    ----
    state : VQAState
        Current state (for run_id and browser manager lookup).
    planned_action : dict
        The planned action with ``search_query``.
    planner_result : dict
        The original planner result.

    Returns
    -------
    dict
        Updated result with the table_search outcome.
    """
    from backend.browser.context import get_manager
    from backend.engine.tools.table_search import execute_table_search

    run_id = state["run_id"]
    search_query = planned_action.get("search_query", "")

    manager = get_manager(run_id)
    page = manager.page
    if page is None:
        planner_result["planned_action"] = {
            **planned_action,
            "action": "done",
            "reasoning": "Browser page is None — cannot execute table_search",
        }
        return planner_result

    result = await execute_table_search(
        page=page,
        search_query=search_query,
    )

    if result["success"]:
        logger.info(
            "[%s] TableWorker: table_search SUCCESS — searched for '%s' (refreshed=%s)",
            run_id,
            search_query[:50],
            result.get("table_refreshed", False),
        )
        # Convert to a "wait" action so the executor skips the action
        # (the search has already been performed) and returns for a
        # fresh screenshot of the filtered table.
        planner_result["planned_action"] = {
            **planned_action,
            "action": "wait",
            "value": "500",
            "strategy": "table_search",
            "name": f"table_search: '{search_query}'",
            "reasoning": (
                f"table_search executed: filtered table for "
                f"'{search_query}'. Table "
                f"{'refreshed' if result.get('table_refreshed') else 'may still be loading'}. "
                f"Now look for the target row in the filtered results."
            ),
            "_table_search_completed": True,
        }
    else:
        error_msg = result.get("error", "Unknown table_search error")
        logger.warning(
            "[%s] TableWorker: table_search FAILED — %s",
            run_id,
            error_msg[:120],
        )
        # Surface the error to the evaluator so the planner can retry
        # with pagination or a different approach
        planner_result["planned_action"] = {
            **planned_action,
            "action": "wait",
            "value": "500",
            "reasoning": (
                f"table_search failed: {error_msg[:200]}. "
                f"Try clicking 'Next Page' or '>' to navigate to "
                f"more rows instead."
            ),
        }

    return planner_result
