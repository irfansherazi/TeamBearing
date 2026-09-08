# Reflection: fix-pagestatetracker-xml-duplication-in-prompt — Fix PageStateTracker XML Duplication in Prompt

**Completed**: 2026-05-15  
**Complexity**: Level 1  
**Task**: Fix PageStateTracker XML Duplication in Prompt  
**Branch**: feature/fix-pagestatetracker-xml-duplication-in-prompt-fix-page-state-duplication (committed to main)

---

## 1. What Was the Issue?

The vQA agent's context window was bloating during long execution sessions. Prompt history analysis (e.g., `run-ff0b9a00_iter72_ac19_vision.txt`) revealed that `verifier.py` was injecting the full `dom_snapshot` XML produced by `PageStateTracker.format_for_prompt()` directly into the `error` string of the `ac_step_failure_diary` on every `NOT_YET` or rejected verdict.

Because `planner.py` already includes a master `_page_state_directive` at the top of every prompt, the diary was doubling the XML on each retry — an O(n·k) blow-up where n = retry count and k = DOM snapshot size. In deep sessions (70+ iterations) this pushed critical constraints out of the LLM attention window ("lost-in-the-middle").

---

## 2. How Was It Resolved?

**Phase 1 (Proactively applied):** `verifier.py` failure diary error strings were modified to replace `{dom_snapshot}` interpolation with the lightweight reference string: `DOM state: (see <page_state> at top of prompt)`.

**Phase 2 (Verified this task):** A targeted unit test `test_task_025_verifier_xml_deduplication.py` was created to assert that the failure diary on a `NOT_YET` verdict:
- Does **not** contain any raw `<page_state>` or `<dom_state>` XML.
- Does **contain** the reference string `(see <page_state> at top of prompt)`.
- Still captures all other relevant metadata (action type, locator, error message).

The test passed (1/1). Full regression suite: **275 passed, 0 failed**.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `backend/engine/verifier.py` | Replaced `{dom_snapshot}` with reference string in failure diary population |
| `tests/test_task_025_verifier_xml_deduplication.py` | New unit test (1 test case) |

---

## 4. Acceptance Criteria Verification

| AC | Status | Evidence |
|----|--------|----------|
| AC-HAPPY-1: Failure diary no longer contains raw `<page_state>` XML | ✅ PASS | Test assertion `assert "<page_state>" not in error_str` |
| AC-HAPPY-2: System prompt context window size reduced on retries | ✅ PASS | By eliminating XML re-injection, diary entries shrink from ~4–8KB each to ~50 bytes |
| AC-REGRESS-1: Agent retains access to `<page_state>` via master directive | ✅ PASS | `planner.py` master directive unchanged; reference string points agent there |
| AC-REGRESS-2: Failure diary still tracks action type, locator, error | ✅ PASS | Test asserts `action_type`, `locator`, and `error_message` present in diary |

---

## 5. Key Learnings

- **context-budget** (`backend/engine/verifier.py`): When a verifier builds failure diary entries, never inline large computed artifacts (DOM snapshots, full page XML) directly into error strings. Instead, use a reference like `(see <X> at top of prompt)` — the artifact is already present in the prompt's master directive and duplicating it is context-hostile.
  - _Scope_: `verifier.py`, `planner.py`

---

## 6. Ecosystem Notes

**No friction.** This was a clean Level 1 task — the fix was proactively applied before the task was even formally registered. The unit test confirmed correctness in a single TDD pass. The workflow overhead (task file, reflection, progress update) is proportionate.

**Observation**: The pattern of "proactively fix, then write the test" (fix-first TDD) is appropriate for 1-line surgical changes where the root cause is unambiguous from log inspection. The formal `/vc-task` + `/vc-build` loop still provides value by ensuring the test is written and committed before the task is closed.

---

## 7. Completed Bug Fix Entry

- [X] [Level 1] Fixed: PageStateTracker XML duplication in verifier failure diary
  - **Issue**: `verifier.py` injected full `dom_snapshot` XML into failure diary error strings on every retry, bloating the context window O(n·k).
  - **Solution**: Replaced `{dom_snapshot}` string interpolation with static reference `DOM state: (see <page_state> at top of prompt)`. No information loss — master directive in planner carries the live snapshot.
  - **Files**: `backend/engine/verifier.py`, `tests/test_task_025_verifier_xml_deduplication.py`
  - **Completed**: 2026-05-15
  - **Ecosystem Note**: Fix-first TDD (patch → test) is appropriate for single-line root-cause-obvious bugs. Reference strings in failure diaries are the correct pattern for all verifier critique strings that mention contextual state.

---

## 8. Level 1 Reflection Checkpoint

```
✓ LEVEL 1 REFLECTION COMPLETE
- tasks/fix-pagestatetracker-xml-duplication-in-prompt.md updated? YES
- Solution documented? YES
- Ecosystem issues noted? YES (observation, not friction)
- Learnings extractable? YES (1 — context-budget rule)
```
