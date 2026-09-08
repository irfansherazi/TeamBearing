# Archive: Natural Language Translation Engine Upgrade

## Metadata
- **Task ID**: natural-language-translation-engine-upgrade
- **Feature**: FEAT-034
- **Complexity**: Level 4
- **Started**: 2026-05-15
- **Completed**: 2026-05-15
- **Duration**: ~2 hours (single session)
- **Branch**: main (committed directly per project convention)
- **Reflection**: `memory-bank/reflection/reflection-natural-language-translation-engine-upgrade.md`

---

## Executive Summary

natural-language-translation-engine-upgrade delivered the Natural Language Translation Engine Upgrade across three phases. The goal was to make the vQA engine natively understand complex Jira ADF test specifications, resist "lost-in-the-middle" context decay during long sessions, and cut off unproductive automation paths faster.

**Key outcomes:**
1. **ADF Parser** — Validated that `backend/jira/client.py` already handles all required rich-text node types (`strong`, `code`, `inlineCard`, `mediaSingle`). No code change needed; test coverage added.
2. **Context Optimization** — Confirmed that the failure diary (FIFO cap at 5) and windowed action history (`action_history_buffer`, 5-entry FIFO) were already implemented by FEAT-035 (vqa-engine-robustness-and-streamlining). Validated via tests.
3. **Decision Loop Streamlining** — Fixed a latent `NameError` crash in the DOM_HIDDEN fast-path (`next_node` undefined variable). Added a 32-test suite formally specifying all decision-loop routing behaviors.

**Total tests added**: 33 (1 ADF parser + 32 decision loop)  
**Critical bug fixed**: 1 (DOM_HIDDEN `next_node` NameError)  
**Regressions introduced**: 0

---

## System Overview

### Purpose
Upgrade the vQA engine's ability to:
1. Parse complex Jira ADF test specifications without text corruption
2. Prevent context amnesia in long test sessions via failure diary + windowed history
3. Aggressively terminate unproductive action loops via circuit breakers

### Scope
**Included:**
- `backend/engine/evaluator.py` — decision loop streamlining and bug fix
- `backend/jira/client.py` — ADF parser validation (pre-existing implementation)
- `backend/engine/planner.py` — context optimization validation (pre-existing implementation)
- Test files for all three phases

**Excluded:**
- Changes to the LangGraph graph topology
- Changes to `executor.py` or `verifier.py`
- UI/frontend changes

### Key Capabilities Delivered

| Capability | Mechanism | File |
|-----------|-----------|------|
| Rich ADF parsing | Recursive `_extract_text_from_adf()` (pre-existing) | `backend/jira/client.py` |
| Failure diary (anti-context-bloat) | FIFO list capped at 5 entries (pre-existing from FEAT-035) | `backend/engine/evaluator.py` |
| Windowed action history | `action_history_buffer` FIFO at 5 (pre-existing from FEAT-035) | `backend/engine/evaluator.py` |
| Locator circuit breaker | `locator_fail_count >= 3` → debugger → human_takeover | `backend/engine/evaluator.py` |
| Sort action circuit breaker | `sort_action_failure >= 5` → human_takeover | `backend/engine/evaluator.py` |
| Content-level block key | `__content__:{name}` on 0-visible STRICT_MODE violations | `backend/engine/evaluator.py` |
| DOM_HIDDEN crash fix | `next_node` → `"planner"` on line 1147 | `backend/engine/evaluator.py` |

---

## Architecture

### Overview
The vQA engine uses a LangGraph state machine with nodes: `ac_parser → planner → executor → evaluator → verifier → reporter`. natural-language-translation-engine-upgrade targeted:
- **`ac_parser` node** (Phase 1): ADF-to-structured-plan translation
- **`planner` node** (Phase 2): prompt assembly with failure context injection
- **`evaluator` node** (Phase 3): decision routing with aggressive path pruning

### Evaluator Decision Cascade (Phase 3)

```
evaluator_node receives state
  │
  ├── success=True, action="done" → verifier (if had failures) or advance step
  ├── success=True, action≠"done" → verifier
  └── success=False → failure branch:
        │
        ├── 1. Diary append (ALWAYS first)
        ├── 2. Diary size cap (> 5 → keep last 5)
        ├── 3. Content-level block (0-visible STRICT_MODE)
        ├── 4. Locator circuit breaker (count >= 3)
        │     ├── debugger_attempted=False → debugger
        │     └── debugger_attempted=True → human_takeover
        ├── 5. "Invalid User" fast-path → human_takeover
        ├── 6. OPTION_NOT_FOUND → planner (with available options)
        ├── 7. INTERCEPTOR_BLOCKED → planner (with fix guidance)
        ├── 8. File picker → human_takeover
        ├── 9. Step total fail >= 10 → reporter
        ├── 10. Recovery Router (one-shot) → planner
        ├── 11. Vision mode auto-escalation (DOM fail >= 2) → vision mode
        ├── 12. HITL threshold → debugger → human_takeover
        └── 13. DOM_HIDDEN fast-path → "planner" (FIXED: was undefined `next_node`)
```

### Integration Points
- **Jira ADF parser**: `backend/jira/client.py` → `ac_parser.py` → `VQAState.jira_ticket.acceptance_criteria_steps`
- **Failure diary**: `VQAState.ac_step_failure_diary` (list) — written by evaluator, read by planner for prompt injection
- **Action history buffer**: `VQAState.action_history_buffer` (list, max 5) — written by evaluator, read by planner
- **KB self-heal**: `backend/kb/` — queried inside evaluator before planner retry

---

## Design Decisions

### Decision 1: ADF Parser — Use Existing Implementation
- **Decision**: Phase 1 pivot to test-coverage only; the recursive ADF extraction was already complete from FEAT-030.
- **Rationale**: The parser already handled `strong`, `code`, `inlineCard`, `mediaSingle`. Re-implementing would duplicate code and introduce risk.
- **Alternatives Considered**: Rewrite parser with explicit node type dispatch table (rejected — existing recursive approach is more maintainable).
- **Reference**: `memory-bank/creative/natural-language-translation-engine-upgrade-ADF-Context-algorithm.md`

### Decision 2: Failure Diary — FIFO Cap at 5 (Option 1 / Option C)
- **Decision**: Cap the failure diary at 5 entries using Python slice `existing_diary[-5:]`
- **Rationale**: 5 entries covers the recent failure history the planner needs without bloating the context window. Earlier entries are stale and counterproductive.
- **Alternatives Considered**: Summarization (rejected — adds LLM latency); unlimited diary (rejected — causes context bloat); cap at 3 (rejected — too aggressive for multi-strategy recovery).
- **Reference**: `memory-bank/creative/natural-language-translation-engine-upgrade-ADF-Context-algorithm.md`

### Decision 3: DOM_HIDDEN Routing — Literal "planner"
- **Decision**: Replace `next_node` (undefined) with the literal string `"planner"` in the DOM_HIDDEN fast-path return dict.
- **Rationale**: The DOM_HIDDEN path is a timing-issue recovery directive that routes back to the planner for a wait+retry. No ambiguity about the target.
- **Alternatives Considered**: None — this was a bug fix, not a design choice.

---

## Implementation

### Phases

| Phase | Duration | Approach | Outcome |
|-------|----------|----------|---------|
| Phase 1: ADF Parser Enhancement | ~15 min | Validation | Parser already correct; 1 test added |
| Phase 2: Context Optimization | ~15 min | Validation | Diary/buffer already implemented by FEAT-035; supplementary tests |
| Phase 3: Decision Loop Streamlining | ~30 min | Bug fix + 32 tests | `next_node` crash fixed; decision loop formally specified |

### Key Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/engine/evaluator.py` | Bug fix (1 line) | `next_node` → `"planner"` at DOM_HIDDEN fast-path |
| `backend/engine/test_evaluator_decision_loop.py` | New file | 32 tests for decision loop routing behaviors |
| `tests/engine/test_task_024_ac_parser_adf.py` | New file | ADF parser integration test |

### Technical Specifications

**Failure Diary State Field:**
```python
# In VQAState
ac_step_failure_diary: Annotated[list, operator.add]  # FIFO, capped at 5

# In evaluator_node (failure branch):
existing_diary.append({
    "attempt": retry_count + 1,
    "action": action_type,
    "locator": locator_key,
    "error": error_msg[:200],
    "timestamp": datetime.datetime.utcnow().isoformat(),
})
if len(existing_diary) > 5:
    existing_diary = existing_diary[-5:]  # Keep newest 5
```

**Locator Circuit Breaker:**
```python
# Key: f"{planned_strategy}:{planned_role}:{planned_name}"
locator_fail_count = fail_counts.get(locator_key, 0) + 1
fail_counts[locator_key] = locator_fail_count

if locator_fail_count >= 3:
    if not state.get("debugger_attempted", False):
        return {"_next_node": "debugger", ...}
    else:
        return {"_next_node": "human_takeover", "awaiting_human_takeover": True, ...}
```

**DOM_HIDDEN Fix:**
```python
# BEFORE (bug): "_next_node": next_node  # NameError: next_node undefined
# AFTER (fix):  "_next_node": "planner"  # Correct routing target
```

---

## Testing

### Strategy
TDD was used for Phase 3. Tests were written to formally specify the decision-loop routing behaviors — not to drive new implementation (since implementation already existed). Phase 1 and 2 used validation-first testing.

### Results

| Test File | Tests | Pass Rate | Coverage Area |
|-----------|-------|-----------|---------------|
| `test_evaluator_decision_loop.py` | 32 | 100% | Decision loop routing |
| `test_task_024_ac_parser_adf.py` | 1 | 100% | ADF parser integration |
| Engine suite (full) | 139/146 | 95.2% | Full engine (7 pre-existing failures) |

### Test Coverage Areas (Decision Loop Suite)
1. **FEAT-035 Locator Circuit Breaker** (5 tests): threshold=3, debugger-first routing, post-debugger escalation, below-threshold continuation, critique message format
2. **Failure Diary Size Cap** (5 tests): cap at 5, under-limit retention, exact-5 not truncated, newest preserved, cleared on step advance
3. **DOM_HIDDEN next_node Fix** (4 tests): routes to "planner", not applied at ≥7 failures, applied at <7, critique contains wait directive
4. **Sort Action Circuit Breaker** (4 tests): threshold=5, below-threshold, sort name recognition, non-sort exclusion
5. **Content-Level Block Key** (3 tests): key format, zero-visible-only trigger, independent increment
6. **Error Classification** (7 tests): STRICT_MODE, TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED, UNKNOWN fallback, count in label
7. **State Field Defaults** (4 tests): diary, action_repeat_counts, debugger_attempted, action_fail_count initialized correctly

---

## Deployment

### Procedures
This is a Python engine upgrade with no infrastructure changes. Deployment is automatic on push to `main`.

### Configuration
No new environment variables or configuration settings introduced.

### Rollback
Revert commit `2e8fbc3` (Phase 3) to restore the undefined `next_node` bug (not recommended). The bug fix is purely additive — it replaces a NameError crash with correct routing.

---

## Maintenance

### Monitoring
- **Decision loop regression**: Run `test_evaluator_decision_loop.py` before any `evaluator.py` changes
- **Diary size**: Monitor `ac_step_failure_diary` length in production state snapshots; should never exceed 5

### Common Issues

| Issue | Resolution |
|-------|------------|
| Agent stuck on DOM_HIDDEN indefinitely | Verify step_fail_count < 7 for fast-path; at ≥7, DOM_HIDDEN uses normal failure cascade |
| Circuit breaker fires too early | Confirm locator key format (`strategy:role:name`) — key mismatch causes false counter isolation |
| Failure diary not cleared between steps | Check all 5+ step-advance paths in evaluator for `"ac_step_failure_diary": []` in return dict |

### Operational Procedures
- **Adding a new circuit breaker to evaluator.py**: Follow `evaluator-cascade` rule — insert at correct priority level. Always append to diary BEFORE the circuit breaker check (see `diary-append-before-escalation` rule).
- **Lint gate**: Run `python -m pyflakes backend/engine/evaluator.py` before committing any evaluator change (see `undefined-variable-lint-gate` rule).

---

## Lessons Learned

*(Full details in `memory-bank/reflection/reflection-natural-language-translation-engine-upgrade.md`)*

1. **Validate, don't duplicate**: When planned implementation is already present from concurrent work, comprehensive test coverage is the correct deliverable — not re-implementation.
2. **Undefined variable lint gate**: `pyflakes` catches F821 undefined-name bugs in <1 second. The `next_node` crash had survived multiple task cycles without detection.
3. **Phase checkbox discipline**: All phase `[ ]` checkboxes must be updated to `[x]` at Step 11 (Git Completion) to prevent false phase-gate blocks at `/vc-reflect`.
4. **Cross-task dependency modeling**: When two tasks work on the same subsystem concurrently, declare explicit dependencies to prevent "already implemented" Phase N surprises.

---

## References
- Reflection: `memory-bank/reflection/reflection-natural-language-translation-engine-upgrade.md`
- Algorithm Creative: `memory-bank/creative/natural-language-translation-engine-upgrade-ADF-Context-algorithm.md`
- Progress Log: `memory-bank/progress.md`
- Feature: FEAT-034 in `memory-bank/roadmap.md`
- Evaluator Routing Rules: `memory-bank/agent-rules/_learned/evaluator-routing.md`
- Testing Patterns: `memory-bank/agent-rules/_learned/testing-patterns.md`

## Future Considerations
- **Fix 7 pre-existing test failures** in `test_evaluator_hardening.py` and `test_hitl_thresholds.md`: missing `vision_mode_fail_count` and `_force_wait_before_next_action` fields in `make_initial_state` (FEAT-004 technical debt)
- **Add `pyflakes` to dev dependencies** and integrate into Step 7 Integration Verification
- **Roadmap dependency graph**: Model FEAT-to-FEAT dependencies in `roadmap.md` to prevent concurrent task collisions
