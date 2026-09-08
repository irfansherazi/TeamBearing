"""
vQA — Standalone Debugger Node (Main Graph Compatible)
========================================================
Module: backend/engine/debugger.py

Extracts the Debugger logic from ``graph_orchestrator.py`` into a
standalone node that works with the main graph's ``VQAState``.

The orchestrator's original ``debugger_node`` is typed for
``OrchestratorState`` and tightly coupled to SQLite memory logging.
This module provides a ``main_graph_debugger_node`` that:

1. Takes ``last_error`` and ``agent_critique`` from VQAState
2. Calls RAG ``query_knowledge_base()`` for semantic context
3. Calls the Commander LLM to produce a structured fix recommendation
4. Writes the result to ``debug_fix_recommendation`` in VQAState
5. Routes back to the planner for a retry with the fix injected

See Also
--------
  - ``backend/engine/graph_orchestrator.py`` — original orchestrator debugger
  - ``backend/engine/evaluator.py``          — routes here before human_takeover
"""

from __future__ import annotations

import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


async def main_graph_debugger_node(state: VQAState) -> dict:
    """
    LangGraph node: Debugger — diagnose a failure and inject a fix
    recommendation back into the planner's context.

    This node fires when the evaluator detects persistent failures
    (``retry_count >= human_takeover_threshold``) and ``debugger_attempted``
    is ``False``.  It gets one shot at diagnosing the issue before the
    system falls back to human takeover.

    Processing:
    1. Collect error context from ``last_error``, ``agent_critique``
    2. Call RAG ``query_knowledge_base()`` for semantic code/doc matches
    3. Call Commander LLM for structured fix recommendation
    4. Write recommendation to ``debug_fix_recommendation``
    5. Set ``debugger_attempted = True``
    6. Reset ``retry_count`` to give the planner a fresh attempt

    Args
    ----
    state : VQAState
        Must contain ``last_error`` and/or ``agent_critique``.

    Returns
    -------
    dict
        Partial state update with ``debug_fix_recommendation``,
        ``debugger_attempted``, and reset ``retry_count``.
    """
    run_id = state.get("run_id", "?")
    last_error = state.get("last_error", "")
    critique = state.get("agent_critique", "")
    ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)

    current_step = ""
    if ac_steps and ac_index < len(ac_steps):
        current_step = ac_steps[ac_index]

    error_context = f"Error: {last_error}\nCritique: {critique}\nAC Step: {current_step}"

    logger.info(
        "[%s] Debugger: analysing failure for AC step %d — %.120s",
        run_id,
        ac_index + 1,
        current_step,
    )

    # ── Step 1: Semantic RAG lookup ─────────────────────────────────────
    rag_context = ""
    try:
        from backend.engine.rag_debugger import query_knowledge_base

        rag_context = query_knowledge_base(error_context, top_k=4)
    except Exception as exc:
        logger.warning("[%s] Debugger: RAG query failed — %s", run_id, exc)

    if not rag_context:
        rag_context = "(No matching code snippets found in the knowledge base.)"

    # ── Step 2: LLM fix recommendation ──────────────────────────────────
    fix_recommendation = ""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from backend.llm import get_llm

        system_prompt = (
            "You are the Debugger node of a multi-agent browser testing pipeline. "
            "A test step has failed repeatedly. Your job is to analyse the error "
            "and produce an ACTIONABLE fix that the planner can use on its next "
            "retry attempt.\n\n"
            "Output Format — use EXACTLY these sections:\n\n"
            "## Root Cause\n"
            "The EXACT reason the test step is failing.\n\n"
            "## Fix Strategy\n"
            "A CONCRETE alternative approach the planner should try. "
            "Be specific: name the exact selector, action type, wait strategy, "
            "or interaction pattern to use instead.\n\n"
            "## Confidence\n"
            "HIGH / MEDIUM / LOW"
        )

        user_msg = (
            f"AC Step: {current_step}\n\n"
            f"Error: {last_error}\n\n"
            f"Critique: {critique}\n\n"
            f"RAG Context:\n{rag_context}\n\n"
            f"Produce the fix recommendation now:"
        )

        llm = get_llm("commander")
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )
        fix_recommendation = (response.content or "").strip()

        logger.info(
            "[%s] Debugger: fix recommendation generated (%.120s …)",
            run_id,
            fix_recommendation,
        )
    except Exception as exc:
        fix_recommendation = (
            f"## Root Cause\nDebugger LLM call failed: {exc}\n\n"
            f"## Fix Strategy\nRetry with a different approach.\n\n"
            f"## Confidence\nLOW"
        )
        logger.error("[%s] Debugger: LLM call failed: %s", run_id, exc)

    # ── Inject recommendation into planner context ──────────────────────
    guidance_injection = (
        f"[DEBUGGER FIX RECOMMENDATION]\n"
        f"The previous approach has failed repeatedly. "
        f"The Debugger has analysed the error and suggests:\n\n"
        f"{fix_recommendation}\n\n"
        f"APPLY this recommendation in your next action. "
        f"Do NOT repeat the same failing approach."
    )

    existing_guidance = state.get("user_guidance", "")
    new_guidance = f"{guidance_injection}\n\n{existing_guidance}" if existing_guidance else guidance_injection

    return {
        "debug_fix_recommendation": fix_recommendation,
        "debugger_attempted": True,
        "retry_count": 0,  # Reset to give planner a fresh attempt
        "user_guidance": new_guidance,
        "_next_node": "planner",  # Route back to planner
    }
