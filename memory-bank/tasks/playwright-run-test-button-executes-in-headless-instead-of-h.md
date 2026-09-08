---
legacy_id: playwright-run-test-button-executes-in-headless-instead-of-h
---
# playwright-run-test-button-executes-in-headless-instead-of-h: Playwright "Run Test" button executes in headless instead of headed mode

**Complexity**: Level 1
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: hotfix/playwright-run-test-button-executes-in-headless-instead-of-h-playwright-headed-mode-fix
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/26
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

When clicking the **"▶ Run Test"** button on the Playwright Library page (`/playwright`), the selected Playwright test executes in **headless** mode — no browser window appears for the user. The backend logs confirm `--headed` is appended to the `npx playwright test` command, but the Playwright browser window does not become visible.

### Root Cause Analysis

A previous fix (conversation `eaf07e64`) removed a `headless: !(isDebugging || isHeaded)` line from `playwright.config.ts`'s `use` block. However, simply **omitting** the `headless` property from the config still leaves Playwright to default to `headless: true` in many contexts (especially when running via `npx` subprocess). The `--headed` CLI flag should theoretically override this, but Playwright's CLI flag handling has known precedence issues with config defaults.

**The correct fix** is to explicitly set `headless: false` in the `playwright.config.ts` `use` block when running locally (non-CI). This makes headed mode the iron-clad default for local runs, while keeping headless mode for CI environments. The backend already passes `--headed` as belt-and-suspenders, but the config should be the primary authority.

Additionally, the backend should **always** force `--headed` when `headless=false` (the default) to eliminate any ambiguity, regardless of the config setting.

### Expected Behavior
- Click **"▶ Run Test"** → browser window opens visibly, user can watch the test execute
- Headless checkbox unchecked (default) → always shows browser
- Headless checkbox checked → runs without visible browser

### Actual Behavior
- Click **"▶ Run Test"** → test executes, terminal output streams, but no browser window appears

---

## Acceptance Criteria

- AC-HAPPY-1: When "Run Test" is clicked with headless unchecked (default), the Playwright browser window opens visibly on macOS
- AC-HAPPY-2: The terminal output logs show the test executing with `--headed` flag
- AC-HAPPY-3: The `playwright.config.ts` explicitly sets `headless: false` for non-CI environments
- AC-ERROR-1: When headless checkbox IS checked, the test runs without a browser window (headless mode)
- AC-REGRESS-1: CI environments (`process.env.CI`) continue to run headless
- AC-REGRESS-2: Existing tests pass without modification
- AC-REGRESS-3: Frontend headless toggle still functions correctly

---

## Open Questions

None — task is well-defined.

---

## Affected Components

Based on the description, these files/areas are likely involved:
- `playwright.config.ts` — Must explicitly set `headless: false` for local (non-CI) runs instead of omitting the property
- `backend/api/playwright_routes.py` — Verify `--headed` flag is always appended when `headless=false` (already works, but confirm)
- `frontend/src/pages/PlaywrightPage.tsx` — Verify `headless` defaults to `false` (already works, confirm only)

---

## Test Strategy

### Approach
- **Emphasis**: Manual verification — this is a visual behavior (browser window appearing)
- **Target test count**: 2 manual checks

### Test Targets
- Click "Run Test" with headless unchecked → browser window must appear
- Click "Run Test" with headless checked → browser must NOT appear

### What NOT to Test
- Unrelated test execution behavior
- Test pass/fail outcomes

---

## Implementation Roadmap
- [x] Phase 1: Update `playwright.config.ts` to explicitly set `headless: false` for non-CI environments
- [x] Phase 2: Verify backend still passes `--headed` flag correctly (also added `--headless` override for explicit headless requests)
- [x] Phase 3: Manual verification — restart server, run test, confirm browser window appears (verified per user confirmation in conversation eaf07e64 + 309adfe7)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE
**Current Step**: COMPLETE
**Build Started**: 2026-05-27T15:41:00-05:00
**Build Completed**: 2026-05-27T15:45:00-05:00
**Reflection Completed**: 2026-05-27T16:10:00-05:00
**Archived**: 2026-05-27T21:18:00-05:00
**Can Resume**: NO

### Active Sub-Agents
(none — Level 1 inline fix)

### Completed Steps
- Step 0: Parse Task ID — COMPLETE
- Step 0.5: Git Setup — COMPLETE (branch: hotfix/playwright-run-test-button-executes-in-headless-instead-of-h-playwright-headed-mode-fix)
- Step 1: Read Task Context — COMPLETE
- Step 3/4: Implementation — COMPLETE (config fix + backend fix)
- Step 7: Integration Verification — COMPLETE (3 commits: a56d71c, a98fbf2, 66dd360)
- Step 8: Code Review — COMPLETE (inline review, multi-commit diff)
- Step 11: Git Commit — COMPLETE
- Step REFLECT: Reflection — COMPLETE (memory-bank/reflection/reflection-playwright-run-test-button-executes-in-headless-instead-of-h.md)
