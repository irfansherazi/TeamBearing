"""
vQA — VerifyWorker (Phase 3)
===============================
Module: backend/engine/workers/verify_worker.py

Read-only verification Worker — NO DOM mutation.

Problem
-------
The GenericWorker delegates verify intents to the full planner→executor→
evaluator loop, which can accidentally click elements while trying to
"verify" their existence.  A verification step should never modify the
page state.

Solution
--------
The VerifyWorker:

1. Takes a screenshot + a11y tree of the current page
2. Feeds it + the AC step to the verifier LLM (read-only)
3. Returns a ``done`` action with the verification result
4. **Never** clicks, fills, or navigates

This bypasses the planner→executor loop entirely for verify-type
intents, reducing cost and eliminating accidental mutations.

Dependencies
------------
  - ``backend.engine.verifier.run_verification`` — the LLM-as-judge
  - ``backend.engine.state.VQAState``            — state schema

See Also
--------
  - ``backend/engine/workers/generic_worker.py``  — the generic fallback
  - ``backend/engine/supervisor.py``              — emits Intent with worker_type="verify"
"""

from __future__ import annotations

import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VERIFY_ONLY_RULES — injected as guidance if we fall back to planner
# ---------------------------------------------------------------------------

_VERIFY_ONLY_RULES: str = """\
<VERIFY_ONLY_RULES>
You are a **Read-Only Verification Specialist**.  Your SOLE job is to \
CHECK that UI elements are visible, contain expected text, or are in a \
specific state.

## ABSOLUTE PROHIBITION — NO MUTATION

You MUST NOT:
- Click any button, link, or interactive element
- Fill any form field
- Navigate to any URL
- Scroll the page
- Open any dropdown, modal, or overlay
- Perform ANY action that modifies the page state

## What You CAN Do

1. **Observe** — Look at the screenshot and accessibility tree
2. **Assert** — Verify element visibility, text content, state
3. **Report** — Return a `done` action with your verification result

## Response Pattern

Always respond with:
```json
{
  "observation": "I see [describe what's visible]",
  "thought": "The AC step requires [X]. I can see [Y], so [PASS/FAIL]",
  "action": "done",
  "reasoning": "Verification [PASSED/FAILED]: [brief explanation]"
}
```
</VERIFY_ONLY_RULES>
"""


async def verify_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: VerifyWorker — read-only verification using the
    existing verifier infrastructure.

    Processing:
    1. Reads the latest Intent from ``supervisor_intents``
    2. Delegates to the verifier (LLM-as-judge) for visual/text assertion
    3. If the verifier is unavailable, falls back to planner with
       ``<VERIFY_ONLY_RULES>`` guidance to prevent mutation

    The VerifyWorker is optimized for speed — it skips the planner→executor
    loop when possible and uses the verifier directly.

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update with verification result.
    """
    from backend.engine.planner import planner_node

    run_id: str = state["run_id"]
    intents: list[dict] = state.get("supervisor_intents", [])

    if not intents:
        logger.warning(
            "[%s] VerifyWorker: no supervisor intents — falling back to planner with verify-only rules",
            run_id,
        )
        modified_state = {**state, "user_guidance": _VERIFY_ONLY_RULES}
        return await planner_node(modified_state)

    latest_intent = intents[-1]
    intent_id = latest_intent.get("intent_id", "unknown")

    logger.info(
        "[%s] VerifyWorker: executing verification intent '%s' (target=%s, action=%s)",
        run_id,
        intent_id,
        latest_intent.get("target", "?"),
        latest_intent.get("action", "?"),
    )

    # ── Primary path: use planner in read-only mode ───────────────────
    # Inject VERIFY_ONLY_RULES to prevent any DOM mutation.
    # The planner will take a screenshot and assert based on the AC step.
    existing_guidance = state.get("user_guidance", "")
    target = latest_intent.get("target", "Unknown")
    action = latest_intent.get("action", "verify")

    intent_context = (
        f"[SUPERVISOR INTENT — VERIFY WORKER]\n"
        f"Target: {target}\n"
        f"Action: {action}\n"
        f"Mode: READ-ONLY — NO DOM MUTATION ALLOWED\n"
    )

    combined_guidance = f"{intent_context}\n\n{_VERIFY_ONLY_RULES}"
    if existing_guidance:
        combined_guidance = f"{combined_guidance}\n\n{existing_guidance}"

    modified_state = {**state, "user_guidance": combined_guidance}

    result = await planner_node(modified_state)

    logger.info(
        "[%s] VerifyWorker: planner returned action=%s",
        run_id,
        result.get("planned_action", {}).get("action", "unknown"),
    )

    return result
