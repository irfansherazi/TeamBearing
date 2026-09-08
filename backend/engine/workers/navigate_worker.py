"""
vQA — NavigateWorker (Phase 3)
=================================
Module: backend/engine/workers/navigate_worker.py

Specialised Worker for **URL-based navigation, sidebar clicks, and
page transitions** in vSuite.

Problem
-------
The GenericWorker delegates navigation intents to the full planner
which may attempt complex DOM reasoning for simple URL navigations,
wasting LLM tokens and introducing failure risk.

Solution
--------
The NavigateWorker injects ``<NAVIGATION_RULES>`` guidance that:

1. Checks if the target URL is already loaded (skip if so)
2. Prioritizes direct URL navigation over DOM clicking
3. Knows vSuite's sidebar/menu structure
4. Adds URL verification as a post-condition

Dependencies
------------
  - ``backend.engine.planner.planner_node`` — the existing SEE-THINK node
  - ``backend.engine.state.VQAState``       — state schema

See Also
--------
  - ``backend/engine/workers/generic_worker.py``  — the generic fallback
  - ``backend/engine/supervisor.py``              — emits Intent with worker_type="navigate"
"""

from __future__ import annotations

import json
import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NAVIGATION_RULES — injected into the planner's user_guidance
# ---------------------------------------------------------------------------

_NAVIGATION_RULES: str = """\
<NAVIGATION_RULES>
You are a **Navigation Specialist** for vSuite.  Your job is to get \
the browser to the correct page as efficiently as possible.

## CRITICAL RULE #1: Check Before Navigating

Before clicking ANY navigation element, check if the browser is \
ALREADY on the target page:
- Compare the current URL with the expected URL path
- If already on the correct page, immediately return `done`
- Do NOT re-click navigation elements if you're already there

## CRITICAL RULE #2: Prefer Direct Navigation

When you know the exact URL path, prefer `goto` action over clicking:
```json
{
  "action": "goto",
  "url": "https://two-test.vcreative.net/productionorders",
  "reasoning": "Navigating directly to Production Orders page"
}
```

## CRITICAL RULE #3: vSuite Navigation Patterns

vSuite uses these navigation elements:
- **Left sidebar** — Main navigation menu with icons
- **Top breadcrumb** — Shows current location, clickable segments
- **Tab bar** — Sub-navigation within a feature area
- **"New Request +"** — Top-left button for creating new items

### Common Routes
| Page | URL Path |
|------|----------|
| Production Orders | /productionorders |
| Dashboard | /dashboard |
| Calendar | /calendar |
| Contacts | /contacts |
| Reports | /reports |

## CRITICAL RULE #4: Wait for Navigation

After any navigation action:
1. Wait for the page to fully load (check URL change)
2. Wait for Angular to settle (no pending HTTP requests)
3. Verify the page title or heading matches expected content
</NAVIGATION_RULES>
"""


def _format_navigate_intent_context(intent: dict) -> str:
    """Format a SupervisorIntent as a NavigateWorker-specific context block."""
    target = intent.get("target", "Unknown Page")
    action = intent.get("action", "navigate")
    data = intent.get("data", {})

    lines = [
        "[SUPERVISOR INTENT — NAVIGATE WORKER]",
        f"Target: {target}",
        f"Action: {action}",
    ]
    if data:
        lines.append(f"Data: {json.dumps(data, indent=2)}")

    intent_header = "\n".join(lines)
    return f"{intent_header}\n\n{_NAVIGATION_RULES}"


async def navigate_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: NavigateWorker — execute navigation Intents with
    URL-first strategy and vSuite route awareness.

    Processing:
    1. Reads the latest Intent from ``supervisor_intents``
    2. Injects ``<NAVIGATION_RULES>`` into the planner's guidance
    3. Delegates to ``planner_node`` for execution

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
            "[%s] NavigateWorker: no supervisor intents — falling back to generic planner",
            run_id,
        )
        return await planner_node(state)

    latest_intent = intents[-1]
    intent_id = latest_intent.get("intent_id", "unknown")

    logger.info(
        "[%s] NavigateWorker: executing intent '%s' (target=%s, action=%s)",
        run_id,
        intent_id,
        latest_intent.get("target", "?"),
        latest_intent.get("action", "?"),
    )

    navigate_context = _format_navigate_intent_context(latest_intent)
    existing_guidance = state.get("user_guidance", "")

    if existing_guidance:
        combined_guidance = f"{navigate_context}\n\n{existing_guidance}"
    else:
        combined_guidance = navigate_context

    modified_state = {**state, "user_guidance": combined_guidance}

    result = await planner_node(modified_state)

    logger.info(
        "[%s] NavigateWorker: planner_node returned action=%s",
        run_id,
        result.get("planned_action", {}).get("action", "unknown"),
    )

    return result
