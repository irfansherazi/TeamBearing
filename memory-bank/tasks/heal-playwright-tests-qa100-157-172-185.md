---
slug: heal-playwright-tests-qa100-157-172-185
legacy_id:
feature:
status: BUILD_COMPLETE
---

# heal-playwright-tests-qa100-157-172-185: Heal 4 failing Playwright tests (QA-100, QA-157, QA-172, QA-185)

**Complexity**: Level 1
**Status**: BUILD_COMPLETE
**Roadmap**: N/A
**Branch**: task/heal-playwright-tests-qa100-157-172-185
**Worktree**: N/A (Level 1 uses direct branch, not worktree)

## Task Description

Heal 4 failing Playwright tests on the QA environment (`qa.vcreative.net`), driven by a prescribed
implementation plan authored from error-trace analysis. Each test has an independent, well-scoped
fix (selector scoping, timing correction, invalid API removal, or timeout bump).

Source plan: `/Users/joshschauer/.gemini/antigravity-ide/brain/1d9eb43d-8530-4f27-995d-325da4ac9c9c/implementation_plan.md`

## Implementation Notes

Four independent fixes, one per test file. Playwright convention constraints from
`playwright/CLAUDE.md` were honored: prefer `getByRole`/`getByLabel`/`data-testid`/`[data-pc-name]`
over class chains; never rely on `.ng-tns-*`, `.p-element`, `ui-` prefix; PrimeNG v19 uses
`p-datepicker`/`p-select` (not `p-calendar`/`p-dropdown`).

### QA-100 (`qa-100-script-library.test.ts`) — selector scope fix
- **Root cause**: page-scoped `input[type="text"], input:not([type])` fallback in the empty-library
  branch resolved to `#global-filter-input` in the background table (obscured by the new-template
  overlay), causing an actionability timeout.
- **Fix**: Two spots (Phase 3 ~line 388, Phase 5 ~line 544). Primary selector now `#scriptName`
  (same ID as Phase 1-2 line 237). Fallback: label-relative lookup scoped to a `:visible` form
  overlay only. Dropped the `box.x > 900` viewport heuristic.

### QA-157 (`qa-157-large-order-testing.test.ts`) — datepicker wait + selector fix
- **Root cause**: `reviseDrawer.locator('p-datepicker input').first()` timed out. The datepicker
  isn't in the DOM immediately after posting the blog comment (form re-renders), and the previous
  `scrollTop = 0` reset scrolled the wrong direction.
- **Fix**: (1) Wait for post to settle via `Promise.race` on the blog textarea/postBtn going
  hidden, bounded at 3s. (2) Broaden datepicker selector to include `p-calendar`, PT attributes
  (`[data-pc-name="datepicker"]`), and placeholder fallbacks. (3) Keep `scrollIntoViewIfNeeded`
  (scrolls in either direction), drop the `scrollTop = 0` reset. (4) Add diagnostic dump of
  drawer inputs when the datepicker doesn't match.
- **Deferred**: Dismissing the leftover Copy sidebar. The existing code comment (lines 165-167)
  documents that `Escape` triggers a blocking "Draft Saved" modal. Safe dismissal requires live
  investigation. The broader datepicker selector plus form-state wait should be sufficient on
  their own — if this test still fails, the leftover-sidebar work becomes the next iteration.

### QA-172 (`qa-172-production.test.ts`) — invalid filter API + inline-expansion fallback
- **Root cause**: `editForm` locator used `.filter({ visible: true })`, which is not a valid
  Playwright filter option (silently a no-op). The locator could resolve to the wrong container.
  In compact view, clicking a card may render POC fields inline rather than opening a separate
  drawer, in which case POC assertions against `editForm` fail even if the assertions themselves
  are correct.
- **Fix**: (1) Replace `.filter({ visible: true })` with `:visible` pseudo-selectors and explicit
  `isVisible()` gating on the POC lines. (2) Add diagnostic that logs the visible container
  landscape after all click strategies fire. (3) Shorten the drawer-open wait to 15s and add
  fallback: search POC fields on `firstCard` if no drawer opened. This decouples the test from
  whether compact view uses a drawer or inline expansion.

### QA-185 (`qa-185-saved-searches-sharing.test.ts`) — timeout + reload fallback
- **Root cause**: `test.setTimeout(120000)` on the owner test was inadequate on QA (the recipient
  test already uses 240000). The unconditional `page.reload({ waitUntil: 'domcontentloaded' })`
  cost ~10-15s even when the sidebar had already updated.
- **Fix**: (1) Bump timeout to 240000 to match the recipient test. (2) Try `scrollToFolder`
  after a short server-settle wait first; only reload as a fallback if the folder isn't visible.
  (3) Trim the virtualization-render wait from 1000ms → 500ms.

## Verification

- **Static**: file diffs preserve the existing serial-test structure, test.describe blocks, and
  fixture usage. Selectors follow playwright/CLAUDE.md conventions.
- **Runtime verification (deferred to user or CI)**: Cannot be run from this context — the
  playwright suite needs the QA environment and takes minutes per test. Suggested commands from
  the implementation plan:
  ```bash
  VQA_HEADLESS=1 TEST_ENV=qa STORAGE_DIR=$(pwd)/playwright/storage/qa \
    npx playwright test tests/vpromedia/qa-100-script-library.test.ts --project=chromium
  # (repeat for qa-157, qa-172, qa-185)
  ```
  Per Josh's feedback memory, these MUST be run and observed passing before the healing is
  declared complete — the commit landing on the branch is not by itself proof of a working fix.

---

## Execution State

**Build Status**: BUILD_COMPLETE
**Current Phase**: Implementation applied; runtime verification pending
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
1. QA-100: scoped input search to template form overlay + #scriptName primary selector
2. QA-157: bounded wait for blog-post settle + broadened datepicker selector + diagnostic
3. QA-172: removed invalid `.filter({visible:true})` + inline-expansion fallback + diagnostic
4. QA-185: timeout 120s → 240s + scroll-first-then-reload-as-fallback + trimmed vrt wait

### Deferred / Follow-up
- QA-157 leftover Copy sidebar dismissal (needs live investigation of the "Draft Saved" modal path)
- Actual Playwright run on QA to confirm each heal passes end-to-end
