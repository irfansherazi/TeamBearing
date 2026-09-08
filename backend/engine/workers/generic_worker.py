"""
vQA — GenericWorker (Phase 1)
===============================
Module: backend/engine/workers/generic_worker.py

The GenericWorker is the Phase 1 implementation of the Worker layer in
the Supervisor-Worker hierarchy.  It wraps the existing, battle-tested
``planner_node`` without rewriting any of its internal logic.

Architecture
------------
The Supervisor emits a structured Intent (e.g., ``worker_type="form"``).
The graph's ``route_to_worker`` conditional edge dispatches the Intent
to the appropriate Worker node.  In Phase 1, ALL worker_types route
to this single GenericWorker, which:

    1. Reads the latest Intent from ``supervisor_intents``
    2. Injects intent-specific context into the existing prompt pipeline
       (via the ``user_guidance`` state field — the lowest-risk injection
       point that the planner already respects)
    3. Delegates to the existing ``planner_node`` for DOM-level execution

This design follows the golden rule: **never rewrite the routing logic
and the execution logic at the same time**.  The GenericWorker proves
that Supervisor routing, token interpolation, and multi-actor context
switching work end-to-end before any specialisation begins.

Phase 2 (future)
----------------
Once multi-actor tickets pass reliably through the GenericWorker:
  - ``FormWorker``     — batch form fills, PrimeNG field type awareness
  - ``TableWorker``    — pagination-aware row search, sort verification
  - ``VerifyWorker``   — screenshot-only verification, no DOM interaction
  - ``NavigateWorker`` — URL-based navigation, no DOM reasoning
  - ``AuthWorker``     — login/logout/switch_actor orchestration

Dependencies
------------
  - ``backend.engine.planner.planner_node`` — the existing SEE-THINK node
  - ``backend.engine.state.VQAState``       — state schema

See Also
--------
  - ``backend/engine/supervisor.py`` — emits the Intent consumed here
  - ``backend/engine/graph.py``      — ``route_to_worker`` edge
"""

from __future__ import annotations

import json
import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


def _format_intent_context(intent: dict) -> str:
    """
    Format a SupervisorIntent as a human-readable context block for
    injection into the planner's prompt.

    This text is prepended to the existing ``user_guidance`` field so
    the planner sees the Supervisor's classification as high-priority
    context without modifying the planner's own prompt assembly logic.

    Args
    ----
    intent : dict
        The SupervisorIntent dict from ``supervisor_intents``.

    Returns
    -------
    str
        A formatted context block string.

    Example
    -------
    >>> _format_intent_context({
    ...     "intent_id": "intent-abc123",
    ...     "worker_type": "form",
    ...     "target": "Quick Order Form",
    ...     "action": "fill",
    ...     "data": {"client": "Bob"},
    ... })
    '[SUPERVISOR INTENT] ...'
    """
    worker_type = intent.get("worker_type", "generic")
    target = intent.get("target", "Unknown")
    action = intent.get("action", "interact")
    data = intent.get("data", {})
    preconditions = intent.get("preconditions", [])

    lines = [
        f"[SUPERVISOR INTENT — {worker_type.upper()} WORKER]",
        f"Target: {target}",
        f"Action: {action}",
    ]
    if data:
        lines.append(f"Data: {json.dumps(data, indent=2)}")
    if preconditions:
        lines.append(f"Preconditions: {', '.join(preconditions)}")

    return "\n".join(lines)


async def generic_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: GenericWorker — execute the Supervisor's Intent
    using the existing planner→executor→evaluator inner loop.

    This is the Phase 1 Worker implementation.  It does NOT rewrite
    any planner logic.  Instead, it:

    1. Reads the latest Intent from ``supervisor_intents``
    2. Formats intent context as a guidance prefix
    3. Prepends it to the existing ``user_guidance`` field
    4. Delegates to ``planner_node`` — the battle-tested SEE-THINK node

    The planner sees the Supervisor's Intent as high-priority context
    at the top of its ``user_guidance`` section, which influences its
    action selection without changing any of its internal prompting.

    Args
    ----
    state : VQAState
        The current LangGraph state.  Must contain:
        - ``supervisor_intents``: list with at least one Intent dict
        - All fields required by ``planner_node``

    Returns
    -------
    dict
        The same partial state update that ``planner_node`` returns:
        - ``planned_action``, ``current_screenshot_b64``,
          ``current_accessibility_tree``, ``planner_iteration``
    """
    # Lazy import to avoid circular dependency at module load time.
    # planner.py imports from state.py, roles.py, etc. — importing it
    # at the top level from a workers/ subpackage can create import loops
    # depending on load order.  This is the standard LangGraph pattern.
    from backend.engine.planner import planner_node

    run_id: str = state["run_id"]
    intents: list[dict] = state.get("supervisor_intents", [])

    if not intents:
        logger.info(
            "[%s] GenericWorker: no supervisor intents — delegating to planner with no intent context",
            run_id,
        )
        return await planner_node(state)

    # Get the latest intent
    latest_intent = intents[-1]
    worker_type = latest_intent.get("worker_type", "generic")
    intent_id = latest_intent.get("intent_id", "unknown")

    logger.info(
        "[%s] GenericWorker: executing intent '%s' (worker_type=%s, target=%s, action=%s)",
        run_id,
        intent_id,
        worker_type,
        latest_intent.get("target", "?"),
        latest_intent.get("action", "?"),
    )

    # Format intent context and prepend to user_guidance
    intent_context = _format_intent_context(latest_intent)
    existing_guidance = state.get("user_guidance", "")

    if existing_guidance:
        combined_guidance = f"{intent_context}\n\n{existing_guidance}"
    else:
        combined_guidance = intent_context

    # Create a modified state copy with the intent context injected.
    # We use dict spread to avoid mutating the original state —
    # LangGraph state is treated as immutable by convention.
    modified_state = {**state, "user_guidance": combined_guidance}

    # Delegate to the existing planner_node
    result = await planner_node(modified_state)

    logger.info(
        "[%s] GenericWorker: planner_node returned action=%s",
        run_id,
        result.get("planned_action", {}).get("action", "unknown"),
    )

    return result
