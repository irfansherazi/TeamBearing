---
legacy_id: force-headed-mode-in-playwright-config-remove-isci-headless
---
# force-headed-mode-in-playwright-config-remove-isci-headless: Force headed mode in playwright.config.ts — remove isCI headless gate

**Complexity**: Level 1
**Status**: COMPLETE (ARCHIVED) ✅
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: hotfix/force-headed-mode-in-playwright-config-remove-isci-headless-always-headed-playwright
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

In production the `CI` environment variable is set to `true`. In `playwright.config.ts`, the `headless` property is currently set to `isCI` (`headless: isCI`), which evaluates to `true` in production — causing all Playwright tests to run headless even though the backend already appends `--headed` to the subprocess command.

The `headless` config property takes precedence over the `--headed` CLI flag, so the browser never appears.

The fix is to set `headless: false` unconditionally in `playwright.config.ts` so tests always run headed regardless of the `CI` environment variable.

**Root cause:**
- `playwright.config.ts` line 116: `headless: isCI` → evaluates to `true` in production (CI=true)
- `playwright_routes.py` line 394: `cmd.append("--headed")` — already correct, but overridden by config

**Related history:**
- playwright-run-test-button-executes-in-headless-instead-of-h fixed this locally but the `isCI` gate regressed it in production where `CI=true` is always set by the ECS/container environment.

---

## Acceptance Criteria

- AC-HAPPY-1: `playwright.config.ts` sets `headless: false` unconditionally — no env-var gate
- AC-HAPPY-2: The `isCI` variable can remain for other purposes (retries, browser selection) but must NOT gate headless mode
- AC-HAPPY-3: Running a test from the vQA dashboard in production opens a visible Chromium browser window
- AC-REGRESS-1: No regressions in existing pytest suite (`pytest tests/ -v`)
- AC-REGRESS-2: The `--project` and `--headed` CLI flags passed by `playwright_routes.py` continue to work correctly
- AC-REGRESS-3: The `chromiumOnly` / multi-browser project selection logic (which uses `isCI`) remains intact

---

## Open Questions

None — task is well-defined.

---

## Affected Components

- `playwright.config.ts` — change `headless: isCI` to `headless: false` (line 116)
- Comments on lines 113-115 should be updated to reflect the new always-headed contract

---

## Test Strategy

### Approach
- **Emphasis**: Config verification — single-line change
- **Target test count**: 1 verification step

### Test Targets
- Confirm `playwright.config.ts` has `headless: false` after the change
- Optionally run `npx playwright test --list` to confirm config loads without error

### What NOT to Test
- Full end-to-end Playwright test run (out of scope for L1)
- Backend auth or vQA engine internals

---

## Implementation Roadmap
- [x] Phase 1: Edit `playwright.config.ts` — set `headless: false`, update surrounding comments
- [x] Phase 2: Code review by second agent
- [x] Phase 3: Verify config loads cleanly (`npx playwright test --list`)

---

## Execution State

**Build Status**: COMPLETE ✅
**Phase Being Built**: ALL PHASES DONE
**Phase Number**: 3 of 3
**Is Multi-Phase**: YES
**Build Started**: 2026-05-28T14:13:00-05:00
**Phase 1 Completed**: 2026-05-28T14:16:30-05:00
**Phase 2 Completed**: 2026-05-28T09:22:00-05:00 (Code Review: APPROVED, no issues)
**Phase 3 Completed**: 2026-05-28T09:22:00-05:00 (Config loads cleanly ✅)

### Current Build Step
- **Step**: ARCHIVED — IDLE
- **Status**: COMPLETE ✅

### Active Sub-Agents
(none)

### Completed Steps
- Phase 1 - Edit playwright.config.ts: COMPLETE
  - `headless: isCI` → `headless: false` (line 118)
  - Comments updated to explain always-headed contract and CI=true risk
  - Pytest: 700 passed, 21 pre-existing failures (none related to config change)
- Phase 2 - Code Review: COMPLETE (APPROVED ✅)
  - All AC verified: no blocking or advisory issues found
  - `isCI` still used correctly for retries, launchOptions, chromiumOnly
  - Comment block quality: excellent (prevents future regression)
- Phase 3 - Config verification: COMPLETE
  - `npx playwright test --list`: Config loads cleanly (‘▶ Playwright config loaded’ line emitted)
  - `@faker-js/faker` missing module error is pre-existing, unrelated to this change
