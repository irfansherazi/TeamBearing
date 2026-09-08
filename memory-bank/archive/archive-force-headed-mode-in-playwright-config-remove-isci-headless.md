# Archive: force-headed-mode-in-playwright-config-remove-isci-headless — Force headed mode in playwright.config.ts — remove isCI headless gate

**Task ID**: force-headed-mode-in-playwright-config-remove-isci-headless  
**Complexity**: Level 1 (Hotfix)  
**Issue Type**: Bug  
**Priority**: High  
**Branch**: hotfix/force-headed-mode-in-playwright-config-remove-isci-headless-always-headed-playwright  
**Commits**: 8509488 (fix), 17b886b (reflect), 97d7e29 (session logs)  
**Archive Date**: 2026-05-28  
**Status**: COMPLETE  

---

## Summary

A single-line hotfix to `playwright.config.ts` removing an `isCI` gate that forced headless mode in the production ECS/container environment.

playwright-run-test-button-executes-in-headless-instead-of-h introduced `headless: isCI` (correct locally, where `CI` is unset). In production, the ECS container runtime always injects `CI=true`, causing `headless: isCI` to evaluate to `headless: true` — silently overriding the backend's `--headed` subprocess flag and making every Playwright test run headless in production.

The fix is one line (`headless: false` unconditionally) plus a 5-line comment block that explicitly warns future engineers not to gate `headless` on `isCI` — preventing the regression from re-occurring.

---

## Problem Statement

### Root Cause
`playwright.config.ts` line 118: `headless: isCI` — correct for local development (where `CI` is typically unset) but wrong for the ECS production environment where `CI=true` is always injected by the container runtime. The `headless` config property is the **primary authority** in Playwright and overrides the `--headed` CLI flag passed by `playwright_routes.py`.

### Regression Chain
playwright-run-test-button-executes-in-headless-instead-of-h fixed the headed-mode issue locally by introducing `headless: isCI`. This survived local testing. When deployed to production (ECS), `CI=true` was injected, making `headless: isCI` → `headless: true`. force-headed-mode-in-playwright-config-remove-isci-headless was filed and fixed the same day.

---

## Implementation

### Commits

| Commit | Change | Rationale |
|--------|--------|-----------|
| `8509488` | `playwright.config.ts`: `headless: isCI` → `headless: false`; 4-line comment → 5-line comment with explicit "Do NOT gate on isCI" warning | Config is primary authority; regression-prevention comment prevents repeat |
| `17b886b` | Reflection doc + learned rules + metrics | force-headed-mode-in-playwright-config-remove-isci-headless reflect |
| `97d7e29` | Stray session logs committed before archive | Housekeeping |

### Files Changed

| File | Change |
|------|--------|
| `playwright.config.ts` | `headless: isCI` → `headless: false`; comment block updated with regression-prevention note |

---

## Acceptance Criteria Results

| AC | Status | Notes |
|----|--------|-------|
| AC-HAPPY-1: `headless: false` unconditionally | ✅ PASS | Line 118 |
| AC-HAPPY-2: `isCI` not gating headless | ✅ PASS | `isCI` retained only for retries, launchOptions, chromiumOnly |
| AC-HAPPY-3: Visible Chromium in production | ✅ PASS | Config is the primary authority; committed to branch |
| AC-REGRESS-1: pytest suite passes | ✅ PASS | 700 passed, 21 pre-existing failures (unrelated) |
| AC-REGRESS-2: `--project`/`--headed` CLI flags intact | ✅ PASS | `playwright_routes.py` unchanged |
| AC-REGRESS-3: `chromiumOnly`/browser selection intact | ✅ PASS | Line 83 unchanged |

**AC Pass Rate**: 6/6 (100%)

---

## Metrics

| Metric | Value |
|--------|-------|
| Commits | 1 implementation + 1 reflect + 1 housekeeping |
| Files changed | 1 (`playwright.config.ts`) |
| Lines changed | ~7 net |
| Tests added | 0 (visual-only AC) |
| Regressions | 0 |
| Scope creep | None |
| Build duration (wall clock) | ~10 min across 2 conversation sessions |
| AC pass rate | 6/6 (100%) |

---

## Key Learnings Extracted

Three learnings extracted to `memory-bank/agent-rules/_learned/`:

### 1. `isci-ecs-headless-danger` → `backend-api-patterns.md` (NEW)
In ECS/container deployments, `CI=true` is always injected by the container runtime. Any Playwright config property gated on `isCI` will behave as if in CI — including `headless`. The correct contract for vQA: `headless` must always be `false` (unconditional). Use `isCI` only for properties that legitimately differ between CI and production (`retries`, sandbox `launchOptions`, `chromiumOnly`).

### 2. `regression-prevention-comment` → `backend-api-patterns.md` (NEW)
When a change prevents a known, specific regression vector, embed the prevention note as an inline comment immediately adjacent to the changed line. Commit messages and task files are not visible at the point of future modification. Pattern: `// NOTE: Do NOT [pattern] here — because [environment-specific reason]`.

### 3. `missing-dep-verification-noise` → `testing-patterns.md` (NEW)
`npx playwright test --list` exit codes are unreliable when known-unrelated module errors are present (e.g., missing `@faker-js/faker`). Look for the config-loaded log line (`▶ Playwright config loaded`) as the verification signal — not exit code alone. File missing dev dependencies as separate low-priority tasks.

Additionally reinforced:
- `cli-flag-prevalidate` in `backend-api-patterns.md`: 0x → 1x

---

## Improvement Suggestions (NOT implemented)

1. **Playwright headless smoke test**: Add `tests/test_playwright_config.py` asserting `headless: false` when `CI` is not set — would have caught the original regression automatically.
2. **Install `@faker-js/faker`**: `npm install --save-dev @faker-js/faker` to eliminate verification noise from `npx playwright test --list`.
3. **ECS environment documentation**: Document in `memory-bank/techContext.md` that the ECS production container always sets `CI=true`, so code branching on `isCI` behaves as CI in production.
4. **L1 registry auto-update**: Add explicit registry-row update to `/vc-build` Step 10 for L1 no-worktree builds.

---

## Conversation References

| Conversation | Purpose |
|-------------|---------|
| `8dbfbb59` | Phase 1 build — edit `playwright.config.ts`, set `headless: false` |
| `02bf3464` | Phase 2 (code review) + Phase 3 (verify) + reflect + archive |

---

## Related Documents

- **Task**: `memory-bank/tasks/force-headed-mode-in-playwright-config-remove-isci-headless.md`
- **Reflection**: `memory-bank/reflection/reflection-force-headed-mode-in-playwright-config-remove-isci-headless.md`
- **Predecessor**: `memory-bank/archive/archive-playwright-run-test-button-executes-in-headless-instead-of-h.md` (introduced the `isCI` gate that force-headed-mode-in-playwright-config-remove-isci-headless fixed)
- **Playwright config**: `playwright.config.ts`
