---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: evaluator-routing

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **evaluator-cascade** (`backend/engine/evaluator.py`): The evaluator's routing logic follows a strict priority cascade: global cap → per-step budget → failure classification → verifier routing → success advancement. New circuit breakers must be inserted at the correct position based on scope (global before per-step before per-action). Breaking this ordering causes higher-priority caps to be bypassed.
  - _Source_: reflection-TASK-003 (2026-05-11)
  - _Reinforced_: 1x

- **counter-reset-exhaustiveness** (`backend/engine/evaluator.py`, `backend/engine/state.py`): Any new per-step counter in VQAState MUST be reset in ALL step-advancement paths in the evaluator — not just the most common one. Grep for `ac_step_index` assignments in evaluator.py to find all 5+ advancement code paths. Missing one reset path causes counter leakage across AC steps.
  - _Source_: reflection-TASK-003 (2026-05-11)
  - _Reinforced_: 1x

- **tri-state-completion** (`backend/engine/evaluator.py`, `backend/engine/reporter.py`): Use separate tracking lists (e.g., `ac_steps_completed` vs `ac_steps_skipped`) rather than overloading a single list when a third completion status (SKIPPED) is needed. This preserves semantic distinction ("app broken" vs "agent timed out") for reporter rendering and downstream analytics.
  - _Source_: reflection-TASK-003 (2026-05-11)
  - _Reinforced_: 1x

- **state-management** (`backend/engine/evaluator.py`): Symmetrically mirror complex state reset blocks across all terminal branching paths (e.g., skip-step vs standard path) to prevent state bleed between runs.
  - _Source_: reflection-TASK-018 (2026-05-13)
  - _Reinforced_: 1x

- **diary-append-before-escalation** (`backend/engine/evaluator.py`): When inserting a new circuit breaker, place it *after* the failure diary append — not before. Escalating before appending creates a silent gap: the triggering failure is never recorded, making the failure diary in the escalated node incomplete and unreliable for root-cause analysis.
  - _Source_: reflection-TASK-026 (2026-05-15)
  - _Reinforced_: 1x

- **undefined-variable-lint-gate** (`backend/engine/evaluator.py`): Before any evaluator.py change is committed, run `python -m py_compile backend/engine/evaluator.py` (syntax) AND `python -m pyflakes backend/engine/evaluator.py` (F821 undefined-name check). The DOM_HIDDEN `next_node` bug was an undefined-name error that static analysis catches in under 1 second but that code review missed across multiple task cycles.
  - _Source_: reflection-TASK-024 (2026-05-15)
  - _Reinforced_: 1x

- **executor-side-recovery** (`backend/engine/executor.py`): Post-failure recovery paths for the vQA engine should be implemented inside `_dispatch_action()` — not as new LangGraph nodes — to preserve graph recursion budget and enable instant feature-flag rollback. The pattern: `if <resolver>.should_activate(state, action, ...): result = await <resolver>.resolve(...); if result: return success_dict; else: return failure_with_context_dict`. Adding a new LangGraph node requires routing table changes and risks increasing graph recursion depth (see TASK-027: GraphRecursionError).
  - _Source_: reflection-TASK-028 (2026-05-17)
  - _Reinforced_: 1x

- **evaluator-recovery-import** (`backend/engine/evaluator.py`): Recovery-tier class imports (`ExplorationRunner`, `CvFallbackResolver`, future resolvers) must be placed as **local imports inside the branch block** — NOT at module level. Module-level imports break test portability because tests import `evaluator` without the full `backend` package prefix, raising `ModuleNotFoundError`. Established by both TASK-028 (CvFallbackResolver) and TASK-029 (ExplorationRunner).
  - _Source_: reflection-TASK-029 (2026-05-18)
  - _Reinforced_: 0x

- **langgraph-node-insertion** (`backend/engine/graph.py`): To insert a pre-check node before an existing node in a LangGraph graph, call `graph.add_node(pre_check_fn)`, remove the existing direct edge to the target, and add conditional edges from the pre-check node with `add_conditional_edges(pre_check_fn, route_fn, {"shortcircuit": terminal_node, "continue": original_target})`. The `route_fn` returns a string key matching the conditional map. Follow the `route_after_*` naming convention for route functions already established in `graph.py`.
  - _Source_: reflection-TASK-031 (2026-05-19)
  - _Reinforced_: 0x

- **done-action-verification** (`backend/engine/evaluator.py`): A `done` action must never advance a step without a final verification check. If the agent fires `done` with zero failures, the evaluator MUST route to the `verifier` to confirm the AC is actually satisfied before marking it complete. This prevents "give-up" actions from being recorded as successful skills.
  - _Source_: reflection-TASK-051 (2026-05-26)
  - _Reinforced_: 1x

- **planned-steptype-node-pattern** (`backend/engine/graph.py`, `backend/engine/evaluator.py`): When adding a new `step_type` that the AC plan explicitly specifies (e.g., `PERSONA_SWITCH`), the correct implementation is a **dedicated LangGraph node** — NOT a new branch inside `executor_node`. The evaluator routes `_next_node = "<step_type>"` based on the current structured step, and the dedicated node advances `ac_step_index` itself after completing. This is additive — zero changes to executor, planner, or existing routing paths. **Contrast with `executor-side-recovery`**: recovery is unplanned fallback → executor-side; planned step-type dispatch → new LangGraph node. Mixing these boundary rules causes either graph recursion pressure (adding too many nodes) or executor bloat (adding too many branches).
  - _Source_: reflection-TASK-063 (2026-05-28)
  - _Reinforced_: 0x

- **sub-step-verification-gate** (`backend/engine/evaluator.py`): For compound AC steps containing `sub_steps`, the evaluator MUST defer routing to the `verifier` node until the final sub-step in the sequence is reached. Use `current_sub_step_index` to track progress and route back to `planner` for intermediate sub-steps. This prevents premature verification failures on incomplete multi-action sequences.
  - _Source_: reflection-TASK-076 (2026-05-29)
  - _Reinforced_: 0x

- **confidence-score-contract-propagation** (`backend/engine/verifier.py`, `backend/engine/state.py`, `backend/engine/evaluator.py`): When a LLM call result gains a new numeric field (e.g., `_verifier_confidence: float`), propagate it across ALL four points: (1) `state.py` type definition + default initialization, (2) the emitting node's initialization to 0.0, (3) ALL verdict return paths in the emitting node (not just the success path), (4) the consuming node's routing/branching logic. Missing any one point causes a silent `0.0` default that routes all medium-confidence results to the wrong branch. Write an explicit test that asserts the confidence field is non-zero after a non-trivial mock verifier call.
  - _Source_: reflection-TASK-080 (2026-05-31)
  - _Reinforced_: 0x

- **symmetric-state-reset-boundaries** (`backend/engine/evaluator.py`, `backend/engine/state.py`): When a state tracking variable is scoped to an individual AC step (e.g., `recovery_attempted_types`), it must be symmetrically reset to its empty/initial value across all 4 terminal transitions in `evaluator.py`: (1) step advance, (2) actor change, (3) persona switch, and (4) role change. Leaving even one transition unaligned leads to state leakage across steps.
  - _Source_: reflection-TASK-097 (2026-06-03)
  - _Reinforced_: 0x

- **dynamic-status-overrides-on-append-only-reducers** (`backend/engine/reporter.py`, `backend/engine/evaluator.py`): When working with state engines where core progress variables use append-only set/list merging reducers (e.g., `ac_steps_completed`), subtracting items from state is impossible without breaking graph determinism. Instead, record negation/failure signals to a separate state list (e.g., `failures`), and dynamically calculate the effective completed set (e.g., `completed - failures`) at report or rendering gates.
  - _Source_: reflection-TASK-101 (2026-06-03)
  - _Reinforced_: 0x
