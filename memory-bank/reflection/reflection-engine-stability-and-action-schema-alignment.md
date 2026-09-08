# Reflection: engine-stability-and-action-schema-alignment — Engine Stability and Action Schema Alignment

## Context
This task was initiated to resolve stability issues caused by "STAGNANT UI" false positives and schema desynchronization. Actions that didn't immediately mutate the DOM (like `scroll` or `coordinate_action`) were triggering circuit breaker loops, and new platform strategies were missing from the Pydantic validation layer.

## Key Changes
1.  **Stagnant UI Exemptions**: Updated `verifier.py` to exempt `scroll`, `press_key`, and `coordinate_action` from the delta check. This prevents the agent from incorrectly flagging successful non-mutating actions as failures.
2.  **Schema Alignment**: Synchronized `PlannerAction.strategy` in `schemas.py` with actual platform capabilities by adding `window` and `coordinate_action`.
3.  **Executor Robustness**: Hardened `_resolve_locator` in `executor.py` to return `None` for non-DOM strategies. This prevents `ValueError` crashes and allows downstream RAG validators to gracefully skip these actions.

## Learnings
- **Delta Check Granularity**: A binary DOM delta is an insufficient signal for "progress" when dealing with complex interactions. Exemptions for specialized action types are necessary to prevent the agent from getting stuck in re-verification loops.
- **Graceful Locator Failure**: Returning `None` from a locator resolution function is safer than raising a `ValueError` for strategies that are fundamentally not locator-based (like `window`). This allows the system to continue processing the action while skipping DOM-specific logic.
- **Pydantic Validation as Guardrail**: Explicitly defining new strategies in the `Literal` type ensures the agent stays within the bounds of what the executor can handle, while the `model_validator` handles the cross-field dependencies (like exempting `name` for `window`).

## Next Steps
- Implement a more sophisticated "Progress Detection" algorithm that goes beyond DOM hashing (e.g., visual delta checks or state-specific assertions).
- Extend `coordinate_action` to support multi-stage interactions beyond simple clicks and fills.
- Monitor the success rate of `scroll` actions to ensure they aren't being over-used now that they are exempted from stagnant UI checks.
