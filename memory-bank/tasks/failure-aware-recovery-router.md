---
legacy_id: failure-aware-recovery-router
---
# failure-aware-recovery-router: Failure-Aware Recovery Router

**Complexity**: Level 4
**Status**: COMPLETE
**Jira Issue**: N/A (internal roadmap FEAT-022)
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/failure-aware-recovery-router-failure-aware-recovery
**Worktree**: N/A
**Roadmap**: FEAT-022

---

## Task Description

Replace the current one-size-fits-all `retry→HITL→abort` pipeline in the evaluator with **type-specific recovery strategies** that automatically apply the correct fix before burning retry budget or escalating to a human.

### Current Behavior (Problem)

The evaluator currently classifies failures via `failure_classifier.py` (FEAT-013) and generates retry hints, but the **routing logic is still flat** — every failure type follows the same path:

1. Failure #1–2 → route to planner with `agent_critique` (including the hint)
2. Failure #2 → auto-escalate to `vision_mode=som_coordinates`
3. Failure #5 → route to debugger (one-shot)
4. Failure #5+ (debugger attempted) → human_takeover
5. Failure #10+ → reporter (terminate)

This means:
- **STRICT_MODE** failures waste 2+ retries before the planner *maybe* adds `container_selector` — the evaluator could inject it automatically from DOM context.
- **TIMEOUT** failures immediately retry the same action — the evaluator could increase the wait and check for a spinner first.
- **NOT_VISIBLE** failures get generic "try a different locator" advice — the evaluator could detect and open the parent accordion/tab/sidebar via DOM traversal.
- **DETACHED** failures retry immediately — the evaluator could wait 500ms for Angular re-render before the next attempt.
- **INTERCEPTED** failures get "press Escape" advice as text — the evaluator could auto-press Escape or click the overlay backdrop programmatically.

### Target Behavior

Each failure type triggers a **targeted, automatic recovery action** before routing back to the planner:

| Failure Type | Recovery Strategy | Auto-Action |
|---|---|---|
| `STRICT_MODE` | Container scoping | Auto-inject `container_selector` from DOM context into `planned_action` |
| `TIMEOUT` | Wait + spinner check | Increase wait to 3s, check for `.p-progress-spinner` or `app-loading` |
| `NOT_VISIBLE` | Parent reveal | DOM traversal to find nearest `p-accordion`, `p-tabview`, or sidebar toggle |
| `DETACHED` | Angular stabilization | Force 500ms wait before retry, no locator change |
| `INTERCEPTED` | Overlay dismissal | Auto-press Escape, or click `.p-dialog-mask` / `.cdk-overlay-backdrop` |

Each strategy is **feature-flagged** for safe rollout (`recovery_strict_mode_enabled`, `recovery_timeout_enabled`, etc. in `config.py`).

Recovery actions are **one-shot** — if the auto-recovery fails, fall through to the existing retry→escalation pipeline. Recovery does NOT consume from the retry budget (it's a free attempt).

---

## Acceptance Criteria

- AC-HAPPY-1: When a `STRICT_MODE` failure occurs and the DOM contains multiple matching elements, the recovery router auto-injects a `container_selector` into the planned_action and retries without incrementing `ac_step_action_fail_count`
- AC-HAPPY-2: When a `TIMEOUT` failure occurs, the recovery router waits 3s and checks for spinner presence before routing back to planner
- AC-HAPPY-3: When a `NOT_VISIBLE` failure occurs, the recovery router identifies the nearest parent accordion/tab and emits a click action on it
- AC-HAPPY-4: When a `DETACHED` failure occurs, the recovery router injects a 500ms stabilization wait and retries the same action
- AC-HAPPY-5: When an `INTERCEPTED` failure occurs, the recovery router auto-presses Escape or clicks the overlay backdrop before retrying
- AC-HAPPY-6: Each recovery strategy is gated by a feature flag in `config.py` (all default to `True`)
- AC-HAPPY-7: Recovery actions are one-shot — if recovery fails, the normal retry pipeline continues with `ac_step_action_fail_count` incrementing
- AC-HAPPY-8: Recovery actions do NOT count against the retry budget (free attempt)
- AC-ERROR-1: When all recovery feature flags are disabled, the evaluator falls through to the existing pipeline unchanged
- AC-ERROR-2: When DOM traversal for NOT_VISIBLE recovery finds no openable parent, the recovery is skipped and normal retry continues
- AC-ERROR-3: Recovery router handles None/empty `planned_action` gracefully without crashing
- AC-REGRESS-1: No regressions in existing evaluator tests
- AC-REGRESS-2: Existing fast-path routes (AUTH_GATE_BLOCKED, ALREADY_IN_VIEW, OPTION_NOT_FOUND, INTERCEPTOR_BLOCKED, file-picker) continue to work unchanged
- AC-REGRESS-3: Per-step iteration budget (FEAT-021) and action history buffer (FEAT-020) continue to work correctly
- AC-REGRESS-4: Vision-mode auto-escalation still triggers at the correct threshold after recovery attempts

---

## Open Questions

⚠️ **Review these before starting the build:**

- [ ] **Recovery ordering**: Should recovery run BEFORE or AFTER the existing fast-paths (#0, #0a, #1, #1a, #1b, #2)? Proposed: AFTER fast-paths but BEFORE the generic retry logic (line ~967 in evaluator.py). - Before
- [ ] **STRICT_MODE container inference**: How should the router determine the correct `container_selector`? Options: (a) nearest common ancestor of all matches, (b) pre-configured mapping from ARIA role to known containers, (c) use the `page_state_snapshot` to find the active panel/section. - (a) if within 500px of current view otherwise we need to do somthing else
- [ ] **NOT_VISIBLE DOM traversal depth**: How many levels up should the router search for an open  able parent? Proposed: max 5 levels (prevents traversing to `<body>`). - 3
- [ ] **INTERCEPTED auto-dismiss**: Should the router try Escape first, then overlay click, or the reverse? Proposed: Escape first (cheaper, works for most PrimeNG dialogs). - Escape first then click
- [ ] **Recovery telemetry**: Should recovery attempts be logged in the `ac_step_failure_diary` or a separate `recovery_diary`? Proposed: Add a `recovery_attempted` field to the existing diary entry.
- [ ] **Phased rollout**: Should all 5 recovery strategies ship in one build, or should they be phased (e.g. Phase 1: STRICT_MODE + DETACHED, Phase 2: TIMEOUT + INTERCEPTED, Phase 3: NOT_VISIBLE)? The feature description says "phased implementation needed." - One build

---

## Affected Components

Based on the description and codebase analysis, these files/areas are involved:

- `backend/engine/evaluator.py` — **Primary target.** The failure routing logic (Case 1: Action FAILED, lines ~589–1068) needs a new recovery dispatch layer between the fast-paths and the generic retry logic. The `_classify_error()` and `_generate_suggestion()` helpers already exist and will feed into the recovery router.
- `backend/engine/failure_classifier.py` — Already has `FailureCategory` enum and `classify_failure()`. May need new categories (e.g. `INTERCEPTED`, `NOT_VISIBLE`, `DETACHED` as distinct from `SELECTOR`/`TRANSIENT`) or a finer-grained sub-classification.
- `backend/engine/state.py` — `VQAState` needs new fields: `recovery_attempted` (bool, tracks one-shot gate per AC step), possibly `recovery_action_log` (list of recovery actions taken).
- `backend/config.py` — 5 new feature flags: `recovery_strict_mode_enabled`, `recovery_timeout_enabled`, `recovery_not_visible_enabled`, `recovery_detached_enabled`, `recovery_intercepted_enabled`.
- `backend/engine/executor.py` — Recovery hooks for NOT_VISIBLE (DOM traversal, parent click) and INTERCEPTED (auto-Escape, overlay click). These are browser actions that the recovery router needs to dispatch outside the normal planner→executor flow.
- `backend/engine/reporter.py` — Display recovery actions in the HTML audit report (recovery attempts should be visible in the step timeline).
- `tests/` — New test suite for recovery router logic.

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy — the recovery router is pure routing logic that can be tested with mock state dicts
- **Target test count**: 25–35 tests (5 per failure type × 5 categories + edge cases + regression)

### Test Targets
- Recovery dispatch per failure type (STRICT_MODE, TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED)
- Feature flag gate (each flag disabled → skip recovery)
- One-shot gate (recovery_attempted=True → skip recovery)
- Recovery does not increment fail counts
- Recovery failure → normal pipeline fallthrough
- Edge cases: empty planned_action, missing DOM context, all flags off
- Regression: existing fast-paths unchanged, vision-mode escalation threshold, FEAT-020/021 integration

### What NOT to Test
- Live Playwright browser interactions (recovery actions that need a real browser)
- LLM planner behavior after receiving recovery-modified state
- S3 upload / AWS integrations

---

## Implementation Roadmap
- [ ] Phase 1: Add feature flags to `config.py` and `recovery_attempted` field to `VQAState`
- [ ] Phase 2: Extract recovery dispatch logic into new `backend/engine/recovery_router.py` module
- [ ] Phase 3: Implement STRICT_MODE and DETACHED recovery handlers (simplest — no browser interaction needed)
- [ ] Phase 4: Implement TIMEOUT and INTERCEPTED recovery handlers (require executor hooks for wait/Escape)
- [ ] Phase 5: Implement NOT_VISIBLE recovery handler (requires DOM traversal helper)
- [ ] Phase 6: Integrate recovery router into evaluator.py Case 1 failure path
- [ ] Phase 7: Add recovery telemetry to failure diary + reporter display
- [ ] Phase 8: Write full test suite

---

## Creative Phases

- [x] Architecture Design → `memory-bank/creative/failure-aware-recovery-router-recovery-router-architecture.md`
- [x] Algorithm Design → `memory-bank/creative/failure-aware-recovery-router-recovery-dispatch-algorithm.md`
- [ ] User Journey — N/A (backend engine feature, no human UI)
- [ ] UI/UX — N/A (no UI design needed)

---

## Execution State

**Build Status**: ARCHIVED
**Last Completed**: Archive
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Architecture Creative Design: COMPLETE (2026-05-11T17:43:00Z)
  Output: memory-bank/creative/failure-aware-recovery-router-recovery-router-architecture.md
- Algorithm Creative Design: COMPLETE (2026-05-11T17:45:00Z)
  Output: memory-bank/creative/failure-aware-recovery-router-recovery-dispatch-algorithm.md
