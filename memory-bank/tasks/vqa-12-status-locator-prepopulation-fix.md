---
slug: vqa-12-status-locator-prepopulation-fix
legacy_id:
feature:
status: COMPLETE
jira: VQA-12
---

# vqa-12-status-locator-prepopulation-fix: Fix vc2-9267-recorded.test Status locator

**Complexity**: Level 1
**Status**: COMPLETE
**Completed**: 2026-08-17
**Roadmap**: N/A
**Branch**: task/vqa-12-status-locator-prepopulation-fix
**Worktree**: N/A (Level 1 uses direct branch, not worktree)
**Jira**: [VQA-12](https://vcreative.atlassian.net/browse/VQA-12) — AI Stage: Diagnosed (Confidence: High)
**Reflection**: memory-bank/reflection/vqa-12-status-locator-prepopulation-fix-reflection.md
**Archived**: memory-bank/archive/vqa-12-status-locator-prepopulation-fix-archive.md
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/79

## Task Description

Fix the `vc2-9267-recorded.test.ts` Status locator failure that surfaced in nightly-cb1b83e6. The test uses a raw `page.getByLabel('Select Status')` + manual click sequence at lines 29–34, which does not survive the three possible QO Status render states (empty placeholder / prepopulated target / prepopulated non-target) documented at `playwright/utils/OrderHelper.ts:1133-1141`.

Swap the hand-rolled locator for the canonical `selectQOStatus()` helper (`playwright/utils/OrderHelper.ts:1106`), which is the shared, hardened Status handler used by `createBasicOrder` and `createOrderWithNewClient`.

Same anti-pattern exists at `playwright/tests/vpromedia/qa-192-recorded.test.ts:86` — apply the same swap there so it doesn't fail identically on the next nightly run.

## Implementation Notes

Per the AI Diagnosis on VQA-12:

**File 1** — `playwright/tests/vpromedia/vc2-9267-recorded.test.ts:29-34`:
- Add `import { selectQOStatus } from '../../utils/OrderHelper';`
- Replace the raw locator + click + text-click block with `await selectQOStatus(page, 'Needs Producing');`
- Test continues to the script polish button check at line 40 — the real VC2-9267 verification only becomes reachable after this fix

**File 2 (piggyback)** — `playwright/tests/vpromedia/qa-192-recorded.test.ts:86`:
- Same swap: replace `page.getByLabel('Select Status')` with `selectQOStatus(page, <target-status>)`
- Confirm the desired target status matches what the test expects post-selection

**Do NOT edit** `playwright/utils/OrderHelper.ts` — it is the canonical helper (hardened through PR #65) and is reference-only for this task.

**Risk**: Low. Swap-in of an existing, exercised helper. No product code touched.

**Deferred**: Whether the underlying VC2-9267 product bug (missing script polish option) has regressed cannot be determined until this locator fix lets the test reach line 40. That is a follow-up if line 40 then fails.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Step 1 Read Task Context: COMPLETE — Level 1, single phase, 2 files
- Step 3 TDD (mechanical swap): COMPLETE — import + call replaced in both files; tsc clean
- Step 11 Git Completion: COMPLETE — committed + pushed to task branch
- Reflection Agent: COMPLETE — Output: memory-bank/reflection/vqa-12-status-locator-prepopulation-fix-reflection.md (commit 517df36)
- Archive: COMPLETE — Output: memory-bank/archive/vqa-12-status-locator-prepopulation-fix-archive.md; learning consolidation appended 1 additive bullet to _learned/testing-patterns.md (evidence_count 6→7)

### Guard & Recovery Log
(none — no production source changed; test-only fix; C2 not triggered)
