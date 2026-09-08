# Archive: Fix PageStateTracker XML Duplication in Prompt

## Metadata
- **Task ID**: fix-pagestatetracker-xml-duplication-in-prompt
- **Complexity**: Level 1
- **Completed**: 2026-05-15
- **Reflection**: `memory-bank/reflection/reflection-fix-pagestatetracker-xml-duplication-in-prompt.md`
- **Branch**: feature/fix-pagestatetracker-xml-duplication-in-prompt-fix-page-state-duplication (committed to main)
- **Roadmap Link**: N/A

---

## Summary

fix-pagestatetracker-xml-duplication-in-prompt was a Level 1 surgical bug fix targeting context window bloat in the vQA agent. During long execution sessions (70+ iterations), the planner's prompt was growing uncontrollably because `verifier.py` was injecting the full `dom_snapshot` XML (produced by `PageStateTracker.format_for_prompt()`) into every failure diary entry. Since the planner already includes a master `_page_state_directive` at the top of every prompt, each retry effectively doubled the XML present in the context — an O(n·k) blowup that pushed critical constraints out of the LLM's attention window ("lost-in-the-middle").

---

## Root Cause

`verifier.py` populated the `error` field of `ac_step_failure_diary` entries using a format string that included `{dom_snapshot}`. This was appropriate for debugging but contextually hostile in production, since the full XML (potentially 4–8KB per entry) was repeated for every failed attempt at a given AC step.

---

## Solution

**One-line fix** in `backend/engine/verifier.py`: replaced the `{dom_snapshot}` string interpolation with the static reference:

```
DOM state: (see <page_state> at top of prompt)
```

This preserves the agent's access to live DOM ground truth (via the master directive already at position 0 of the prompt) without duplicating it into the diary. The failure diary now captures all other relevant metadata — action type, locator strategy, exact error message — at a fraction of the cost (~50 bytes per entry vs. 4–8KB).

**Fix was proactively applied** before the task was formally registered; Phase 2 delivered the confirming unit test.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/engine/verifier.py` | Replaced `{dom_snapshot}` with reference string in failure diary error population |
| `tests/test_task_025_verifier_xml_deduplication.py` | New unit test — asserts no raw XML in failure diary, reference string present, other metadata intact |

---

## Test Results

| Suite | Result |
|-------|--------|
| `test_task_025_verifier_xml_deduplication.py` | 1/1 passed |
| Full regression suite | 275/275 passed, 0 failed |

---

## Acceptance Criteria

| AC | Status |
|----|--------|
| AC-HAPPY-1: Failure diary contains no raw `<page_state>` XML | ✅ PASS |
| AC-HAPPY-2: Context window size reduced on retries | ✅ PASS (per-entry savings: ~4–8KB → ~50 bytes) |
| AC-REGRESS-1: Agent retains `<page_state>` access via master directive | ✅ PASS |
| AC-REGRESS-2: Failure diary still captures action type, locator, error | ✅ PASS |

---

## Learned Rules Created

- **`agent-rules/_learned/context-budget.md`** (new file, 2 rules)
  - Never inline large computed artifacts into failure diary error strings — use reference strings
  - Keep a single authoritative location for each large prompt artifact; downstream components reference, not copy

---

## Notes

- Fix-first TDD (apply obvious patch → write confirming test) is an appropriate Level 1 pattern when root cause is unambiguous from log inspection. The formal task lifecycle still provides value by ensuring the test is committed and the change is documented before closure.
- This fix is a prerequisite for effective context-window management in deep sessions. The `context-budget` learned rule generalizes this pattern to all verifier/evaluator critique strings that currently reference contextual state objects.
- No worktree cleanup needed — fix-pagestatetracker-xml-duplication-in-prompt was developed directly on `main`.
