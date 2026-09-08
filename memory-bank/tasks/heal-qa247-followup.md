---
slug: heal-qa247-followup
status: QUARANTINED
derived_from: heal-playwright-tests-round4
quarantined_on: 2026-08-10
---

# heal-qa247-followup: Fix QA-247 Dubbed Checkbox Enable After Approval

## Problem

`playwright/tests/vpromedia/qa-247-job-completion-hover-feature.test.ts` quarantined in `heal-playwright-tests-round4` Rev Phase 1.

**Root cause:** The `input#complete-job-<id>-Dubber` checkbox never enables after spot approval, even after:
- 90s of polling with fresh page reloads every 10s
- Confirmed `approveSpot()` successfully clicked an approval button (✅ logged)
- Navigating to `folder/all` and re-finding the spot multiple times

Investigation revealed the DOM dump from `folder/all` shows `complete-job-<id>-Writer`, `Filming`, `PostProd`, `Releaser`, `Traffic`, `Billing` — but **NO Dubber job**. The `Radio Commercial` ad type created for this test does not have a Dubber job on QA with the current `DemoProdDirector` firm configuration.

## Evidence

Phase 0.5 baseline: "Dubbed checkbox stuck `disabled` at line 173 after full approval flow. `<input disabled ...>` resolved 63 times over 30s."

Phase 1 run1 log: 6 poll attempts all returned `enabled=false`. DOM snapshot confirms no `complete-job-<id>-Dubber` input exists for the Radio Commercial order.

## Fix Required

Options:
1. Use an ad type that includes a Dubber job (e.g., "TV Ad" or "Sold Radio Commercial" with dubbing workflow enabled). Verify in the QA environment which ad types have Dubber in their job list.
2. OR: The test needs to verify the Dubber job is part of the order's job list before asserting; if absent, use a different spot type.
3. Alternatively: verify with eng that the Dubber approval workflow is correctly configured for `DemoProdDirector`'s firm on QA.

## Note

The initial assertions (disabled state + tooltip verification) work correctly — the setup is sound. Only the "after approval" enable step fails because the Dubber job doesn't exist in the created order.
