---
legacy_id: update-qa-170-playwright-test-sales-poc-selection
---
# update-qa-170-playwright-test-sales-poc-selection: Update QA-170 Playwright Test Sales POC Selection

**Complexity**: Level 1
**Status**: COMPLETED
**Jira Issue**: N/A
**Issue Type**: Task
**Priority**: Medium
**Branch**: task/update-qa-170-playwright-test-sales-poc-selection-update-qa170-sales-poc
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

The Playwright test `playwright/tests/qa-170-search.test.ts` currently prepares its test data by creating a fresh spot with `salesPoc: true` in the order details. This selects the first available sales option from the multiselect list.

To make the test more deterministic, reliable, and compliant with target sandbox data, we need to update the test to explicitly and always select `"Demo Account Executive"` as the sales POC.

---

## Acceptance Criteria

- **AC-HAPPY-1**: The Playwright test in `playwright/tests/qa-170-search.test.ts` passes `'Demo Account Executive'` as the `salesPoc` string parameter when calling `OrderHelper.createAndSubmitOrder`.
- **AC-HAPPY-2**: During test execution, the order-creation phase successfully locates and selects the "Demo Account Executive" option inside the Sales POC multiselect.
- **AC-REGRESS-1**: No regressions are introduced to general search retention verification or the order helper's multiselect-handling logic.
- **AC-REGRESS-2**: The `qa-170-search.test.ts` test suite runs and passes successfully.

---

## Open Questions

⚠️ **Review these before starting the build:**

- None — task is well-defined. The `OrderHelper.createAndSubmitOrder` function is already pre-configured to accept string values for `salesPoc` and filter/click the corresponding multiselect option.

---

## Affected Components

Based on the description, these files are involved:
- `playwright/tests/qa-170-search.test.ts` — The data prep step `createAndSubmitOrder` will be updated to pass `"Demo Account Executive"` as the `salesPoc` property.

---

## Test Strategy

### Approach
- **Emphasis**: Automated End-to-End Playwright Execution
- **Target test count**: 1 test file (`qa-170-search.test.ts`)

### Test Targets
- `playwright/tests/qa-170-search.test.ts`

### What NOT to Test
- Unrelated backend route or API logic.

---

## Implementation Roadmap

- [x] Phase 1: Update `playwright/tests/qa-170-search.test.ts` to pass `'Demo Account Executive'` as the `salesPoc` parameter.
- [x] Phase 2: Run and verify the Playwright test passes cleanly.

---

## Execution State

**Build Status**: COMPLETED
**Last Completed**: 2026-06-08
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
1. Updated `playwright/tests/qa-170-search.test.ts` to pass `'Demo Account Executive'` as `salesPoc` parameter to `OrderHelper.createAndSubmitOrder`.
2. Fixed test grid loading issues by explicitly navigating to the `All` folder view (`folder/all`) after order submission to refresh the table.
3. Swapped fragile `p-table tr` row search with robust, standard `ViewHelper.getRow` helper.
4. Ran and verified that the entire `qa-170-search.test.ts` test runs and passes successfully on Chromium.
