"""
T3-c Reflex Layer — hard-coded failure-signature recovery (FEAT-118).

Provides a deterministic short-circuit before LLM-backed recovery.
Runs BEFORE recovery_router.attempt_recovery() in the evaluator retry path.

Usage (in evaluator.py, before the FEAT-022 recovery_router block):

    from backend.engine.reflex import attempt_short_circuit, ReflexResult
    _reflex_result = attempt_short_circuit(state, error_msg, planned_action)
    if _reflex_result is not None:
        # handle hit — return early, skip Bedrock
        ...
"""

from backend.engine.reflex.dispatcher import ReflexResult, attempt_short_circuit

__all__ = ["attempt_short_circuit", "ReflexResult"]
