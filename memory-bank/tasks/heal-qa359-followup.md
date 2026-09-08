---
slug: heal-qa359-followup
status: QUARANTINED
derived_from: heal-playwright-tests-round4
quarantined_on: 2026-08-10
---

# heal-qa359-followup: Fix QA-359 vPromo Storage State

## Problem

`playwright/tests/qa-359-recorded.test.ts` quarantined in `heal-playwright-tests-round4` Rev Phase 1.

**Root cause:** `vpromotions-test.vcreative.net` requires its own authentication session separate from `qa.vcreative.net`. The `generateStorageStates.mjs` script provisions sessions for `qa.vcreative.net` (and `two-test.vcreative.net`) but NOT for the vPromo app domain. When the test navigates to `https://vpromotions-test.vcreative.net/app_test.php/promo`, the storage state doesn't apply and the page shows a login form. The `New PRF` button never mounts.

## Evidence

- Phase 0 error context snapshot: login form with `heading "Login With Email"` at vpromotions-test.vcreative.net
- The `waitFor({ state: 'visible', timeout: 20000 })` correctly waits but the button never appears because the user is unauthenticated.

## Fix Required

1. Extend `generateStorageStates.mjs` to also provision a storage state for `vpromotions-test.vcreative.net` (and/or the prod vPromo URL) for `DemoProdDirector`.
2. Store as `playwright/storage/qa/storageState_DemoProdDirector_vpromo.json` (or equivalent convention).
3. Update `qa-359-recorded.test.ts` to load the vPromo storage state before navigating to `vpromotions-test.vcreative.net`.
4. Remove the `test.fixme()` wrapper.

## Out of Scope

This is an infrastructure gap (missing storage state provider), not a test logic issue. The test's wait/click logic is correct.
