# Reflection: per-step-iteration-budget — Per-Step Iteration Budget

**Date**: 2026-05-11
**Complexity**: Level 2
**Duration**: ~7 minutes (11:55 → 12:02 CDT)

## Quality Assessment

| Dimension | Score (1-5) | Notes |
|-----------|------------|-------|
| Code Quality | 5 | Clean separation of budget computation, SKIPPED routing, and counter resets. Consistent inline comments with `# FEAT-021:` prefix make changes grep-discoverable. No DRY violations — the budget formula appears once; all step-advancement paths share the same reset pattern. |
| Test Coverage | 4 | 21 unit tests covering all 12 acceptance criteria (AC-HAPPY-1 through AC-HAPPY-6, AC-ERROR-1/2, AC-REGRESS-1/2/3). Tests are well-structured across 8 logical test classes. Deduction: `TestPlannerIncrement.test_planner_return_includes_incremented_counter` tests arithmetic rather than calling the actual `planner_node` — it's a formula-level test, not an integration test. Also, the budget computation tests (TestBudgetComputation) are pure-math assertions that don't exercise the evaluator's actual code path. |
| Architecture | 5 | The feature fits cleanly into the existing evaluator-centric routing pattern. Budget computation is placed between the global cap check and the per-step circuit breakers, which is the correct position in the evaluator's decision cascade. State fields follow the existing TypedDict + reducer convention. The `_deduplicated_add` reducer is a bonus bug fix (BUG-003) that emerged from this work. |
| Documentation | 5 | Every new state field has a docstring-style comment block. The config field has a comprehensive `description` parameter. The evaluator's FEAT-021 block has a leading comment explaining the formula. The task file's Implementation Roadmap was fully checked off with all 8 phases marked complete. |
| Error Handling | 5 | Division-by-zero guard (`remaining_steps <= 0 → use cap`), `max(1, ...)` floor to prevent zero-budget allocation, and clean separation of SKIPPED vs FAILED semantics. The budget-exhausted path resets all per-step counters identically to the normal step-advancement path, preventing state leakage. |

**Average Score: 4.8/5**

## What Went Well

1. **Surgical implementation with minimal blast radius.** Only 5 core files changed (`config.py`, `state.py`, `planner.py`, `evaluator.py`, `reporter.py`) — exactly the files listed in the task spec's Affected Components section. No unexpected side effects or cascading changes.

2. **Budget placement in evaluator decision cascade is correct.** The per-step budget check runs after the global `max_planner_iterations` cap but before the failure/success routing logic. This means:
   - Global cap still short-circuits when hit (AC-REGRESS-2 preserved)
   - Per-step budget fires before the evaluator wastes time on verifier/failure classification
   - The existing `current_ac_step_action_count` circuit breaker fires independently (AC-REGRESS-3 preserved)

3. **SKIPPED vs FAILED semantic distinction is well-enforced.** Skipped steps are added to `ac_steps_skipped` but NOT to `ac_steps_completed`. The reporter renders them with a distinct visual class (`skip`) and icon (`⊘`), making it easy for humans to distinguish "the app is broken" from "the agent ran out of time."

4. **Counter reset consistency.** The `ac_step_iterations_used = 0` reset was added to ALL step-advancement paths in the evaluator — normal advancement, role rotation, ALREADY_IN_VIEW fast-path, and the new SKIPPED path. This is exactly the right approach; missing any one reset path would cause budget leakage across steps.

5. **Bonus bug fix: `_deduplicated_add` reducer (BUG-003).** While adding state fields, the developer discovered that `operator.add` on `ac_steps_completed` could produce duplicate indices when both the verifier and evaluator append the same step. The new `_deduplicated_add` reducer fixes this pre-existing data integrity issue at no additional cost.

6. **Config field validation constraints.** `per_step_budget_max` has `ge=5, le=100` bounds, preventing operators from setting the cap to absurd values (0 or 1000) that would either skip every step or provide no protection.

## What Was Challenging

1. **Identifying all step-advancement paths in the evaluator.** The evaluator has 5+ distinct code paths that advance `ac_step_index`: normal verification success, role rotation, last-step completion, the new SKIPPED path, and the ALREADY_IN_VIEW fast-path. Each path needed `ac_step_iterations_used = 0` added. Missing one would silently cause the budget counter to bleed across steps. The implementation correctly identified and patched all paths.

2. **SKIPPED routing on the last step.** When the last AC step exhausts its budget, the evaluator must route to `reporter` (not `planner`). This is a distinct code path from mid-run SKIPPED routing (which advances to the next step via `planner`). The implementation handles this correctly with an explicit `_new_ac_index >= len(ac_steps)` check.

3. **State field interaction with LangGraph reducers.** `ac_steps_skipped` uses a plain list (no reducer) because the evaluator overwrites the full list on each skip. This is correct — the SKIPPED list is not append-merged across parallel branches because the evaluator is the sole writer. `ac_steps_completed` uses the new `_deduplicated_add` reducer because both the verifier and evaluator can write to it.

## Patterns Discovered

1. **Evaluator Decision Cascade Pattern**: The evaluator's routing logic follows a strict priority cascade: global cap → per-step budget → failure classification → verifier routing → success advancement. New circuit breakers should be inserted at the correct position in this cascade based on their scope (global before per-step before per-action).

2. **Counter Reset Exhaustiveness**: Any new per-step counter in `VQAState` must be reset in ALL step-advancement paths, not just the most common one. The evaluator has 5+ advancement paths. A grep for `ac_step_index` in the evaluator identifies them all. This pattern was also followed for `ac_step_action_fail_count`, `current_ac_step_action_count`, `verifier_not_yet_count`, and `ac_step_failure_diary`.

3. **SKIPPED as Distinct Semantic Status**: Using a third completion state (PASS / FAIL / SKIPPED) with a separate tracking list (`ac_steps_skipped`) rather than overloading `ac_steps_completed` preserves the semantic distinction between "app is broken" and "agent ran out of time." This is important for reporter accuracy and for downstream analytics.

## Recommendations for Future Tasks

1. **FEAT-021 follow-up — observable budget in WebSocket stream.** The `ac_step_iteration_budget` and `ac_step_iterations_used` fields are in state but not currently streamed via the WebSocket to the React dashboard. Adding a progress bar (e.g., "Step 2: 15/30 iterations") would give operators real-time visibility into budget consumption.

2. **FEAT-021 follow-up — adaptive cap escalation.** The current `per_step_budget_max=30` is a fixed cap. A smarter approach would use the step's historical pass rate (from past runs on the same ticket) to allocate more budget to historically-difficult steps. This is a Level 3 feature and should be tracked separately.

3. **Test improvement — mock the actual evaluator_node for budget tests.** Several tests in `TestBudgetComputation` test the formula in isolation (pure math) rather than through the evaluator. While the integration tests in `TestBudgetExhaustion` do call `evaluator_node`, the computation tests could be strengthened by verifying the evaluator's actual `_step_budget` calculation via state output.
