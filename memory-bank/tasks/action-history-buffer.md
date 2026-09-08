---
legacy_id: action-history-buffer
---
# action-history-buffer: Action History Buffer

**Complexity**: Level 3
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: high
**Branch**: feature/action-history-buffer-action-history-buffer
**Worktree**: ../vQA-action-history-buffer
**Roadmap**: FEAT-020 (v2.0.0)

---

## Task Description

Implement a structured rolling window of the last N **failed** actions (with outcomes) injected as a `<past_actions>` XML block into the planner system prompt. The buffer enforces a hard constraint: **"NEVER repeat a strategy that appears in `<past_actions>` with outcome=FAILED."**

### Problem (FM-1: Amnesic Retry Loops)

The planner currently forgets what it already tried on previous iterations. When an action fails, the evaluator writes the failure to `ac_step_failure_diary` and `agent_critique`, but these are formatted as free-text suggestions — the LLM can and does ignore them, re-trying the same broken locator with minor cosmetic changes (e.g., switching from `get_by_role` to `get_by_text` but targeting the same non-existent element name). This wastes 3-5 iterations before human_takeover triggers.

### Solution

Add a **structured, rolling buffer** of the last 5 failed actions to VQAState. The evaluator appends to it on every `success=False` action. The planner injects it as a `<past_actions>` XML block at **priority 2** (immediately after FAILURE DIARY) in the system prompt. Each entry contains:

- `action`: the action type (click, fill, etc.)
- `strategy`: locator strategy used
- `target`: the element name/role
- `error_type`: classified error (STRICT_MODE, TIMEOUT, etc.)
- `iteration`: which planner iteration this occurred on

The buffer is **capped at 5 entries** (oldest evicted on overflow) and **cleared when `ac_step_index` advances** (new step = fresh buffer).

### Key Differences from Existing `ac_step_failure_diary`

The existing `ac_step_failure_diary` is a free-text suggestion mechanism. The Action History Buffer is:
1. **Structured XML** — machine-parseable, not prose
2. **Hard constraint** — the prompt says "NEVER repeat", not "try something different"
3. **Rolling window** — fixed size, doesn't grow unboundedly
4. **Focused on strategy deduplication** — tracks (action, strategy, target) tuples to detect same-target retries even when the agent changes the strategy name

---

## Acceptance Criteria

- AC-HAPPY-1: A new `action_history_buffer` field exists in `VQAState` as a plain `list[dict]` (not annotated with `operator.add` — the evaluator overwrites the full list on each update)
- AC-HAPPY-2: The evaluator appends a structured entry to `action_history_buffer` on every `success=False` action, containing keys: `action`, `strategy`, `target`, `error_type`, `iteration`
- AC-HAPPY-3: The buffer is capped at 5 entries; when a 6th entry is added, the oldest is evicted (FIFO)
- AC-HAPPY-4: The buffer is cleared to `[]` when `ac_step_index` advances (evaluator done/satisfied paths)
- AC-HAPPY-5: The planner injects a `<past_actions>` XML block into the system prompt when the buffer is non-empty, positioned after the failure diary in the `<context>` section
- AC-HAPPY-6: The `<past_actions>` block includes a hard constraint: "NEVER repeat an action+strategy+target combination that appears below with outcome=FAILED"
- AC-ERROR-1: When `action_history_buffer` is empty (first action on a new step), no `<past_actions>` block is injected (no empty XML tags)
- AC-REGRESS-1: No regressions in existing tests (`pytest tests/ -v` passes)
- AC-REGRESS-2: The existing `ac_step_failure_diary` mechanism continues to work unchanged — the buffer supplements, not replaces, the diary
- AC-REGRESS-3: All evaluator routing decisions (planner, verifier, human_takeover, reporter) remain unchanged

---

## Open Questions

None — task is well-defined.

---

## Affected Components

Based on the codebase analysis:

- `backend/engine/state.py` — Add `action_history_buffer: list[dict]` field to `VQAState` TypedDict (plain field, no reducer annotation — evaluator overwrites full list)
- `backend/engine/evaluator.py` — Append structured entry on `success=False` path (Case 1); clear buffer on AC step advance (Case 2 done paths and Case 3→verifier→satisfied paths)
- `backend/engine/planner.py` — New `_build_past_actions_block(state)` function; inject into `SYSTEM_PROMPT_TEMPLATE` in the `<context>` section; wire into both `_build_system_prompt` (v1) and `_build_system_prompt_v2` (v2) codepaths

---

## Test Strategy

### Approach
- **Emphasis**: unit-heavy (state manipulation + prompt injection are pure functions)
- **Target test count**: 8-10 tests

### Test Targets
- `_build_past_actions_block()` — empty buffer → empty string; non-empty → correct XML
- Buffer capping logic — verify 6th entry evicts oldest
- Buffer clearing on AC step advance
- Evaluator appends correct structured entry on failure
- Integration: full evaluator_node failure path populates buffer correctly

### What NOT to Test
- LLM behavior change (can't unit test whether the LLM actually respects the constraint)
- Playwright interactions
- AWS/S3 integrations

---

## Creative Phases

- [x] Architecture Design → `memory-bank/creative/action-history-buffer-action-history-buffer-architecture.md`
- [x] Algorithm Design → `memory-bank/creative/action-history-buffer-action-history-buffer-algorithm.md`
- [ ] ~~User Journey~~ — N/A (internal backend feature, no user-facing journey)
- [ ] ~~UI/UX~~ — N/A (no UI components involved)

---

## Implementation Roadmap
- [x] Phase 1: Add `action_history_buffer` field to `VQAState` in `state.py`
- [x] Phase 2: Update evaluator failure path to append structured entries + cap at 5
- [x] Phase 3: Update evaluator advance paths to clear buffer on AC step change
- [x] Phase 4: Implement `_build_past_actions_block()` in `planner.py`
- [x] Phase 5: Wire into prompt template and both `_build_system_prompt` variants
- [x] Phase 6: Write unit tests in `tests/test_action_history_buffer.py`

---

## Execution State

**Build Status**: ARCHIVED
**Current Build**: N/A — archived
**Current Phase**: BUILD → REFLECT
**Build Started**: 2026-05-11T10:51:00-05:00
**Gemini CLI**: unavailable — single-agent mode
**Branch**: feature/action-history-buffer-action-history-buffer
**Worktree**: ../vQA-action-history-buffer

### Current Build Step
**Step**: Step 11 - Update Task Status
**Status**: COMPLETE
**Started**: 2026-05-11T11:12:00-05:00

### Sub-Agents
| Agent | Status | Command ID | Output |
|-------|--------|------------|--------|
| (inline) | COMPLETE | — | 10 tests, all passing |

### Completed Steps
- [Architecture] Creative Design: COMPLETE (2026-05-11T10:42:00-05:00)
  Output: memory-bank/creative/action-history-buffer-action-history-buffer-architecture.md
- [Algorithm] Creative Design: COMPLETE (2026-05-11T10:43:00-05:00)
  Output: memory-bank/creative/action-history-buffer-action-history-buffer-algorithm.md
- Step -1 Resolve PROJECT_ROOT: COMPLETE (2026-05-11T10:51:00-05:00)
- Step 0 Parse Input: COMPLETE (2026-05-11T10:51:00-05:00)
- Step 0.1 Resumption Check: COMPLETE (2026-05-11T10:51:00-05:00) — NEW build
- Step 0.2 Load Project Context: COMPLETE (2026-05-11T10:51:00-05:00)
- Step 0.5 Gemini CLI: COMPLETE (2026-05-11T10:51:00-05:00) — unavailable, single-agent mode
- Step 1 Git Setup: COMPLETE (2026-05-11T10:52:00-05:00) — worktree ../vQA-action-history-buffer
- Step 1.5 Phase Gate: COMPLETE (2026-05-11T10:52:00-05:00) — all checks passed
- Step 2 Load Context: COMPLETE (2026-05-11T10:52:00-05:00) — Level 3, multi-phase
- Phase 1 (state.py): COMPLETE (2026-05-11T10:53:00-05:00) — `action_history_buffer: list[dict]` added
- Phase 2 (evaluator failure): COMPLETE (2026-05-11T10:55:00-05:00) — append+cap at L984-995
- Phase 3 (evaluator advance): COMPLETE (2026-05-11T10:57:00-05:00) — 6 clear paths
- Phase 4 (planner function): COMPLETE (2026-05-11T10:59:00-05:00) — `_build_past_actions_block()`
- Phase 5 (prompt injection): COMPLETE (2026-05-11T11:01:00-05:00) — v1 template + v2 budget
- Phase 6 (tests): COMPLETE (2026-05-11T11:03:00-05:00) — 10 tests, all passing
- Step 5 Test Execution: COMPLETE (2026-05-11T11:05:00-05:00) — 29/29 passed (10 buffer + 19 budget)
- Step 10 Commit: COMPLETE (2026-05-11T11:06:00-05:00) — 2 commits on feature branch
- Step 11 Task Status: COMPLETE (2026-05-11T11:12:00-05:00)

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A — ARCHIVED
**⚠️ Merge Required**: Changes exist only in worktree `../vQA-action-history-buffer` on branch `feature/action-history-buffer-action-history-buffer`. Run `/vc-archive action-history-buffer` or merge manually to bring changes into main.
