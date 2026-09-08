# Archive: Fix vc2-9267-recorded.test Status locator

## Metadata

- Task: vqa-12-status-locator-prepopulation-fix
- Complexity: Level 1
- Jira: [VQA-12](https://vcreative.atlassian.net/browse/VQA-12)
- Branch: task/vqa-12-status-locator-prepopulation-fix
- Completed: 2026-08-17

## Summary

Two Playwright recorded tests (`vc2-9267-recorded.test.ts` and `qa-192-recorded.test.ts`) used a raw `page.getByLabel('Select Status')` + hand-rolled click sequence that only survived a single QO Status render state. In practice the field has three variants — empty placeholder, prepopulated target, prepopulated non-target — documented in `playwright/utils/OrderHelper.ts:1133-1141` and already handled by the canonical `selectQOStatus()` helper (`OrderHelper.ts:1106`). The raw pattern broke on nightly-cb1b83e6 for VC2-9267 and would have broken identically on the next run for QA-192.

## Solution

Mechanical swap — no product source changed, no helper edits:

- Added `import { selectQOStatus } from '../../utils/OrderHelper'` to each test file.
- Replaced the 5-line `getByLabel('Select Status') / isVisible / click / getByText('…').click()` block with `await selectQOStatus(page, 'Needs Producing')`.
- The helper already waits for the field internally, so the explicit `waitFor` + `waitForTimeout(500)` were removed.

TypeScript compiles clean; C2 guard did not trigger (no production source touched). Live nightly confirmation is deferred — the fix lets `vc2-9267-recorded.test.ts` reach line 40, where the actual VC2-9267 script-polish assertion runs. If line 40 then fails, that surfaces the original product bug as a separate follow-up.

## Files Changed

- `playwright/tests/vpromedia/vc2-9267-recorded.test.ts` — helper swap at lines 29–34
- `playwright/tests/vpromedia/qa-192-recorded.test.ts` — same swap at line 86
- `memory-bank/tasks/vqa-12-status-locator-prepopulation-fix.md` — task lifecycle
- `memory-bank/reflection/vqa-12-status-locator-prepopulation-fix-reflection.md` — reflection doc
- `memory-bank/agent-rules/_learned/testing-patterns.md` — appended one bullet on the raw-locator-vs-helper pattern

## Commits

- `b4b2a1d` task(vqa-12-status-locator-prepopulation-fix): create Level 1 task file
- `db999d7` test(vqa-12): swap raw Status locator for selectQOStatus() helper
- `517df36` reflect(vqa-12): add Level 1 reflection document
- `244c3e1` vqa-12: mark task REFLECTION_COMPLETE

## Notes

- **Pattern to reuse**: any recorded test that hand-rolls a locator for a form field with known multi-state render behavior is fragile by construction. If a canonical helper exists in `OrderHelper.ts`, prefer the helper at import time.
- **Deferred verification**: live CI confirmation on the next nightly run. If the fixed test now reaches line 40 and fails there, open a separate ticket for the underlying VC2-9267 product bug (missing script polish option in QO).
- **Recurring anti-pattern**: worth a broader sweep of `playwright/tests/**` for other raw `getByLabel('Select Status')` / `getByLabel('Select Adtype')` / similar dropdown patterns.
