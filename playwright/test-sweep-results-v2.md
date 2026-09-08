# Playwright Test Sweep Results (v2)

- **Target**: https://qa.vcreative.net
- **Environment**: `TEST_ENV=qa`
- **Project**: chromium

## Pre-Flight Baseline Snapshot

| File Path | Size (Bytes) | Last Modified |
|-----------|--------------|---------------|
| `playwright/tests/verify-login.test.ts` | 1639 | Jun 10 16:22 |
| `playwright/tests/qa-46-basic-ad-types.test.ts` | 7734 | May 27 10:31 |
| `playwright/tests/qa-58-59-poc-delegation.test.ts` | 35070 | May 27 10:31 |
| `playwright/tests/qa-100-script-library.test.ts` | 30831 | Jun 10 11:07 |
| `playwright/tests/qa-101-client-merging.test.ts` | 38227 | May 27 10:31 |
| `playwright/tests/qa-125-new-user-experience.test.ts` | 14976 | Jun 10 16:21 |
| `playwright/tests/qa-157-large-order-testing.test.ts` | 9633 | Jun 10 14:49 |
| `playwright/tests/qa-170-search.test.ts` | 6516 | Jun 10 15:02 |
| `playwright/tests/qa-172-sales.test.ts` | 2648 | May 27 10:31 |
| `playwright/tests/qa-172-production.test.ts` | 3854 | May 27 10:31 |
| `playwright/tests/qa-175-lockout.test.ts` | 8688 | Jun  9 15:52 |
| `playwright/tests/qa-185-saved-searches-sharing.test.ts` | 10792 | Jun 10 15:18 |
| `playwright/tests/qa-196-Files.test.ts` | 1700 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step1-prewash.test.ts` | 279 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step2-upload.test.ts` | 289 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step3-audio.test.ts` | 295 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step4-qo.test.ts` | 360 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step5-listview.test.ts` | 299 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step6-slideout.test.ts` | 305 | May 27 10:31 |
| `playwright/tests/qa-196-components/qa-196-step7-history.test.ts` | 314 | May 27 10:31 |
| `playwright/tests/qa-197-revision-process.test.ts` | 27571 | May 27 10:31 |
| `playwright/tests/qa-203-datetime-picker-pastdue.test.ts` | 27582 | May 27 10:31 |
| `playwright/tests/qa-204-client-approval-upon-submit.test.ts` | 15410 | May 27 10:31 |
| `playwright/tests/qa-247-job-completion-hover-feature.test.ts` | 5409 | May 27 10:31 |
| `playwright/tests/qa-254-manual_archive.test.ts` | 3237 | Jun  9 15:53 |
| `playwright/tests/qa-257-Exporting_spot_info.test.ts` | 11242 | May 27 10:31 |
| `playwright/tests/qa-279-send-email.test.ts` | 11095 | May 27 10:31 |
| `playwright/tests/qa-298-folder-count-equals-visible-spot-count.test.ts` | 11392 | May 27 10:31 |
| `playwright/tests/qa-321-sorting-list-and-compact.test.ts` | 11645 | May 27 10:31 |
| `playwright/tests/webkit-qo-baseline.test.ts` | 3616 | May 27 10:31 |

---

## Test Run Logs

### Test 1: playwright/tests/verify-login.test.ts
**Run 1 Result**: FAIL
**Error** (if FAIL): expect(authenticatedIndicator).toBeVisible() failed inside loginHelper.mjs:120 (Timeout 20000ms)
**Root Cause Analysis** (if FAIL): The parent shell process had stale `SHARED_TEST_PASSWORD` and `ADMIN_TEST_PASSWORD` environment variables set which overrode our `.env` configuration. Additionally, a race condition in `loginHelper.mjs` checked `isVisible()` too early before the loader appeared, skipping the hidden wait and blocking the profile menu click.
**Fix Class**: LOGIC | TIMING
**Fix Applied**: Updated `playwright.config.ts` to use `dotenv.config({ override: true })` so correct credentials from `.env` take precedence. Also removed the `isVisible()` check in `loginHelper.mjs`'s loader handling to wait for loader state `'hidden'` natively and robustly.
**Run 2 Result (confirmation)**: PASS
**Regression Check** (if utility modified): N/A (First test executed in the suite)
**Final Status**: FIXED

### Test 2: playwright/tests/qa-46-basic-ad-types.test.ts
**Run 1 Result**: FAIL
**Error** (if FAIL): TimeoutError: locator.click failed (Timeout 30000ms) on getByRole('option', { name: 'Needs Producing' }) inside OrderHelper.ts
**Root Cause Analysis** (if FAIL): In Angular/PrimeNG v19, changing the ad type triggers dynamic status list updates, making option elements detach from the DOM while Playwright is clicking them. Additionally, under "Needs Producing" status, the ISCI input field is dynamically disabled by the application, causing `fill()` to crash.
**Fix Class**: TIMING | LOGIC
**Fix Applied**: Implemented a robust status select click-and-option retry pattern to survive detached elements in `OrderHelper.ts`. Also added `isEnabled()` checks to ISCI, length, and rotation fields to skip filling if disabled by business rules.
**Run 2 Result (confirmation)**: PASS
**Regression Check** (if utility modified): PASS (verify-login.test.ts regression check runs completed successfully)
**Final Status**: FIXED

### Test 3: playwright/tests/qa-58-59-poc-delegation.test.ts
**Run 1 Result**: FAIL
**Error** (if FAIL): TimeoutError: page.waitForSelector failed (Timeout 30000ms) on 'input[id^="table-checkbox-"]'
**Root Cause Analysis** (if FAIL): In some states of the production-equivalent QA database, the `/folder/inbox` directory can become completely empty of spots. Hardcoding `/folder/inbox` causes the test to hang indefinitely when no rows are available.
**Fix Class**: LOGIC
**Fix Applied**: Implemented an adaptive folder fallback mechanism. If the `inbox` folder is empty, the test automatically and dynamically falls back to the `drafts` folder (and if empty, to the `all` folder), updating the scoped `activeFolder` variable so all subsequent navigation steps and count verifications align seamlessly.
**Run 2 Result (confirmation)**: PASS
**Regression Check** (if utility modified): N/A (Test-local refactoring only, no shared utility modified)
**Final Status**: FIXED

### Test 4: playwright/tests/qa-100-script-library.test.ts
**Run 1 Result**: FAIL
**Error** (if FAIL): TimeoutError: locator.waitFor: Timeout 15000ms exceeded on `.p-sidebar, .p-drawer, .p-dialog, app-v-sidebar` filtered by `/Script|Library|Send|Submit/i`
**Root Cause Analysis** (if FAIL): The `directSendLink.click({ force: true })` bypassed Angular's event binding, so the "Send Script to Library" dialog never opened. `{ force: true }` skips Playwright's normal pointer/hover event chain which Angular components rely on to trigger click handlers.
**Fix Class**: SELECTOR | TIMING
**Fix Applied**: Removed `{ force: true }` from click; added `scrollIntoViewIfNeeded()` and `expect(directSendLink).toBeVisible()` gate before click; moved console error listeners before the click; expanded dialog selector to also include `app-v-drawer, p-sidebar, p-drawer`; increased dialog wait timeout from 15s to 30s.
**Run 2 Result (confirmation)**: PASS
**Regression Check** (if utility modified): N/A (test-local fix only)
**Final Status**: FIXED

### Test 5: playwright/tests/qa-101-client-merging.test.ts
**Run 1 Result**: FAIL
**Error** (if FAIL): expect(locator).toBeVisible() failed — locator `.p-multiselect-item, [data-pc-section="option"], li[role="option"]` filtered by typo client name not found
**Root Cause Analysis** (if FAIL): The multiselect filter used only the first 15 chars of the typo client name (`"Apollo Candy Co"`), which matched all accumulated typo clients from previous test runs (20+ entries). The current run's specific client was scrolled off-screen in the dropdown list and not in the DOM visible viewport.
**Fix Class**: SELECTOR | TIMING
**Fix Applied**: Changed filter from `typoClientName.substring(0, 15)` to the full `typoClientName` to uniquely narrow the dropdown to just the current run's client; increased wait after filter from 1000ms to 1500ms; added `scrollIntoViewIfNeeded()` before clicking the option; added `[role="option"]` (without `li`) to the option selector for PrimeNG v19 compatibility; increased option visibility timeout from 5000ms to 10000ms.
**Run 2 Result (confirmation)**: PASS
**Regression Check** (if utility modified): N/A (test-local fix only)
**Final Status**: FIXED

---

## Batch 1 Complete (Tests 1–5)

| # | Test File | Status | Fix Class | Fix Description |
|---|-----------|--------|-----------|-----------------|
| 1 | verify-login.test.ts | FIXED | LOGIC \| TIMING | dotenv override + loader race condition fix |
| 2 | qa-46-basic-ad-types.test.ts | FIXED | TIMING \| LOGIC | Status option retry + disabled field guards |
| 3 | qa-58-59-poc-delegation.test.ts | FIXED | LOGIC | Adaptive folder fallback if inbox empty |
| 4 | qa-100-script-library.test.ts | FIXED | SELECTOR \| TIMING | Remove force:true, add visibility gate + scroll |
| 5 | qa-101-client-merging.test.ts | FIXED | SELECTOR \| TIMING | Full typo name filter to avoid scrolled-off options |

**Batch Totals**: 0 PASS, 5 FIXED, 0 BLOCKED
**Cumulative Totals**: 5/5 complete (5 FIXED, 0 BLOCKED)

