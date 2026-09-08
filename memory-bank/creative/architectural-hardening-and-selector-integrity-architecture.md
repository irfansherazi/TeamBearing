# Creative Design: architectural-hardening-and-selector-integrity Architecture — Model Escalation & State Propagation

## Problem Statement
The current model escalation logic is fragmented. While `ModelRouter` has a placeholder for `is_verifier_rejected`, the state is not effectively passed from the `verifier_node` to the `planner_node` in a way that triggers immediate escalation. This causes the agent to waste attempts with Haiku on complex recoveries that require Sonnet's reasoning.

## Proposed Architecture: Option A — State-Aware Escalation (Selected)

### 1. State Schema Enhancement
Update `VQAState` in `backend/engine/state.py` to explicitly track `last_verifier_rejected` (bool).
- `verifier_node`: Sets `last_verifier_rejected = True` when returning a `NOT_YET` or `FAILED` verdict due to visual mismatch.
- `evaluator_node`: Resets `last_verifier_rejected = False` when a step is successfully advanced.

### 2. ModelRouter Protocol Update
Update `ModelRouter.get_model_id` and `get_tier` to accept and enforce the `is_verifier_rejected` signal.
- If `is_verifier_rejected == True` AND `retry_count >= 1`, force `TIER_2` (Sonnet).
- This ensures that if the verifier says "No, you didn't do it right," the next attempt immediately uses the heavy model.

### 3. Planner Integration
Update `_invoke_planner_with_tools` in `backend/engine/planner.py` to retrieve `is_verifier_rejected` from the `VQAState` and pass it to the router.

## Alternative: Option B — Heuristic Escalation
Escalate to Sonnet based purely on `retry_count >= 2`.
- **Pros**: Simpler, no state changes needed.
- **Cons**: Still wastes one Haiku attempt on complex visual errors that we *know* need better reasoning.

## Decision: Option A
State-aware escalation is more precise and minimizes wasted tokens/time on low-probability Haiku attempts.

## Impact on System Patterns
- Follows the "Model Routing" pattern established in FEAT-060.
- Strengthens the "Verifier-as-Judge" loop.
