---
slug: heal-13-playwright-failures-on-two-test
legacy_id:
feature:
status: COMPLETE
---

# heal-13-playwright-failures-on-two-test: Heal 13 Playwright failures on two-test — investigate before fixing

**Complexity**: Level 1
**Status**: COMPLETE
**Archived**: memory-bank/archive/heal-13-playwright-failures-on-two-test-archive.md
**Completed**: 2026-08-12
**Roadmap**: N/A
**Branch**: task/heal-13-playwright-failures-on-two-test
**Worktree**: N/A (Level 1 uses direct branch, not worktree)

## Task Description

13 Playwright tests fail when the nightly suite runs against `two-test.vcreative.net`. The tests were healed in PR #65 (`feature/heal-playwright-tests-round4`, merged 2026-08-11), but that PR's healing pass ran against `qa.vcreative.net`. `two-test` is a different environment with likely different PrimeNG build, form validation rules, and seed data.

**Non-goal**: rewriting the 13 test files defensively. PR #65's whole thesis was a *single shared helper* (`dismissBlockingOverlays` in `playwright/utils/OrderHelper.ts`) rather than per-test patches. That thesis must be preserved.

### Phase 0 (mandatory, before any code edit)

1. Pick one representative from each failure family below and run it with `TEST_ENV=qa`. If it passes on qa → env drift, NOT a test bug. Do not edit the test file; investigate the env delta.
2. For failures that reproduce on qa as well → real regressions since PR #65. Those go through normal heal path.

### Failure families (grouped by shared symptom, not by test file)

- **Family A** — `OrderHelper.ts:1342` *"Failed to select status 'Needs Writing' after 4 attempts"* (5 tests: QA-46, QA-157, QA-172, QA-197, WebKit QO Baseline).
  Single bug in the `selectStatus` retry loop at `OrderHelper.ts:1310-1343`. Fix once in the helper, not five times in the test files. Candidates: overlay timing on two-test's PrimeNG build, or the "Needs Writing" option missing from two-test's dropdown data.
- **Family B** — Locator click / `waitFor` timeout (3 tests: QA-196, VC2-9225, VC2-9267).
  Element never appears. QA-196 is downstream of Family A (waits for "Select Status" text). VC2-9225 waits for a "Deleted" tab button. VC2-9267 waits for the Select Status label. Investigate DOM shape delta on two-test.
- **Family C** — `toBeVisible` topbar assertion (2 tests: QA-101, QA-204).
  Identical locator chain `'#top-navbar, .user-text, .vppo-icon, .layout-topbar, app-topbar, ...'`. Almost certainly a shared setup helper or storage-state issue. If storage state for two-test is stale/missing, login never completes and the topbar never renders. Check `storage/test/storageState_*.json` before touching test code.
- **Family D** — Assertion state mismatch (1 test: QA-279).
  Send button never enables. Likely env-specific — file-attach flow that gates Send may complete differently on two-test.
- **Family E** — Form validation reject (1 test: QA-203).
  *"Due by 1 Missing fields"* tooltip. FORM error, not a timing bug. two-test's TV Ad form is rejecting submission — either it requires a "Due by" field the test doesn't fill, or the fill isn't sticking due to a different date-picker binding. Compare two-test's QO form DOM against qa's before editing `OrderHelper.fillOrderDates`.
- **Family F** — Search yields nothing (1 test: QA-185).
  Search for client "The" returned zero rows AND no empty-state within 60s across two attempts. Two-test data condition.

### Exit criteria

- Every failure classified as one of:
  - **(a) env-drift** — documented; no code change; `test.fixme` with an un-fixme condition if two-test will diverge long-term.
  - **(b) real regression since PR #65** — fixed in the helper if shared, in the test only if truly leaf-level.
  - **(c) test-quality bug PR #65 missed**.
- No per-test defensive rewrites of shared-helper failures.
- `dismissBlockingOverlays()` and `selectStatus()` remain the single call sites for their concerns.

### Rescope constraint

If Phase 0 shows most failures are env-drift, this task is **"document the env delta + quarantine two-test-specific failures,"** NOT "heal 13 tests." Rescope explicitly rather than forcing edits.

## Implementation Notes

Discovery already established:

- `playwright.config.ts:22-32` — `ENV_MAP.test = 'https://two-test.vcreative.net'`, `ENV_MAP.qa = 'https://qa.vcreative.net'`, default `TEST_ENV = 'test'`. So a bare `npx playwright test` targets **two-test**. `TEST_ENV=qa npx playwright test` swaps baseURL to `qa.vcreative.net`.
- `storage/test/storageState_*.json` all contain cookies with `domain: two-test.vcreative.net` and `origin: https://two-test.vcreative.net`. These auth states were captured **on two-test**. Family C's storage-state hypothesis is *strengthened*: if storage was refreshed only on two-test and never on qa, running `TEST_ENV=qa` will trip a fresh auth path (or silent failure) — meaning Phase 0's "run on qa" is not a pure baseline; it also swaps auth material. This must be handled explicitly, not silently.
- Recent commit `206731e test(playwright): harden QA-170/175/196/197/279 for reliability across environments` (post-PR#65) touched QA-197 (Family A) and QA-279 (Family D). Worth diffing to see what "cross-environment" hardening already tried.

## Phase 0 Findings (evidence-first, before any code edit)

### Structural findings (definitive, from repo state — no test runs yet)

1. **`playwright/storage/test/*.json` are 20-day stale.** mtime = 2026-07-22 10:52 vs. `playwright/storage/qa/*.json` mtime = 2026-08-11 10:10 (refreshed by PR #65 commit `277bb7c` "Phase 0.5 rescope — session regen"). Different user rosters too: `test/` has `storageState_kristine_hurd.json` and `storageState_doug_loepp.json` which qa lacks; qa has `storageState_DemoTopBiller.json` which test lacks.
2. **JWTs in `test/` states are decodable and unexpired.** DemoProdDirector: iat=2026-07-16, exp=2026-08-15 (valid ~3 more days). Domain is `.vcreative.net` (parent), so the token is theoretically portable across `qa`/`test`/`smoke`. `user_id=600920`, `firm_id=11850` match on both.
3. **`session_salt` differs between qa and test states for the same user** — DemoProdDirector `test`-side salt = `n3QD3n7Rh9wV+XOBPMjwgA==`, `qa`-side salt = different value. If the backends share the user table (undetermined), PR #65's Aug 11 qa re-auth *rotated* the salt and silently invalidated the two-test state.
4. **`playwright.config.ts:32` defaults `TEST_ENV` to `'test'`** — so a bare `npx playwright test` targets two-test. Nightly runs on two-test by default; nothing in the repo overrides this for the nightly script yet.
5. **`setup.ts:128 ENV_TIMEOUT_MULTIPLIER = qa:2.5, smoke:2, else:1`.** Comment claims `else = 1× (localhost / test env)` but `test` is `two-test.vcreative.net`, a remote AWS host — not localhost. Two-test likely needs the same 2.5× headroom qa gets. **Systematic timing budget too tight on two-test.** Family A's `selectStatus` inner loop uses hardcoded ms (1000/5000/400/600), so this multiplier wouldn't rescue it directly — but every `test.setTimeout(N * ENV_TIMEOUT_MULTIPLIER)` in the outer test bodies is 2.5× tighter on two-test than on qa.
6. **QA-196 has documented QA-vs-test DOM differences already.** Commit `2c74deb` (Jun 30) says: "Sales POC field (required on QA)", "QA truncates inline file list", "QA shows file name, not type". So the Family B QA-196 failures on two-test are the *reverse* env-drift of what that commit patched.
7. **QA-196 per-env spot data is stale on test.** `storage/qa-196/qa-196_spot_data_test_chromium.json` is 150B / Jul 22 vs. `qa-196_spot_data_qa_chromium.json` 255B / Aug 11 — different shape, different mtime.
8. **No env-branching in the failing test bodies.** Only `qa-298` and `qa-257` `if (TEST_ENV === ...)`. All 13 failures run identical logic against different environments.

### Provisional family verdicts (evidence-supported hypotheses, not test-run confirmed)

| Family | Tests | Most-likely primary cause | Evidence-strength |
|---|---|---|---|
| **A** — selectStatus 4-attempt failure | QA-46, QA-157, QA-172, QA-197, WebKit QO Baseline | PrimeNG overlay timing on two-test's older/different build; hardcoded ms in the retry loop, no env multiplier applied inside `OrderHelper.ts:1310-1343` | Medium (structural) |
| **B** — Locator waitFor timeout | QA-196×N, VC2-9225, VC2-9267 | DOM-shape drift; QA-196 already documented as env-different in commit `2c74deb` | High (QA-196 has git-log proof) |
| **C** — topbar assertion never visible | QA-101, QA-204 | Stale/rotated storage state — the single most likely explanation for a shared setup helper failing identically across two tests with the same locator chain | High (matches finding 1 + 3 exactly) |
| **D** — Send button never enables | QA-279 | Env-specific attach flow; needs test run to confirm | Low (no structural evidence yet) |
| **E** — "Due by 1 Missing fields" form reject | QA-203 | Two-test QO form validation drift (different required fields) OR date-picker binding difference | Medium (Family E is post-login form, not auth) |
| **F** — Search yields nothing | QA-185 | Data condition on two-test; client "The" seed row missing | Medium (no seed check yet) |

### Rescope proposal (before running any tests)

The user's Phase 0 spec says "run one rep from each family against `TEST_ENV=qa` — if it passes on qa, env-drift, not test bug." **That experiment is confounded** because `TEST_ENV=qa` also swaps in fresh storage state material. If a test passes on qa, we can't distinguish "env-drift" from "just needed fresh auth material." We'd falsely blame two-test's app instead of its stale state.

Cheaper + cleaner experiment:

1. **Regenerate `playwright/storage/test/*.json`** via `node playwright/utils/generateStorageStates.mjs` (or whatever the current generator is — verify) with `TEST_ENV=test`. This should take a few minutes and costs one test-account login round per user. Then re-run the 13 failures against two-test.
   - If Family C (QA-101, QA-204) now passes → **confirmed stale-state**, not code bug. No test edits.
   - If Families A/B/D/E/F change at all → tells us how much auth freshness bought.
2. **Whatever still fails** after storage refresh is either (a) real env-drift (two-test's app is genuinely different) or (b) real regression / test-quality bug. THEN run those specific tests against `TEST_ENV=qa` — but *only* against `TEST_ENV=qa` with the fresh qa storage — to see if qa still passes. That is now an unconfounded comparison.
3. **Also worth fixing regardless**: `ENV_TIMEOUT_MULTIPLIER` — the comment is wrong; `test` is not localhost. Adding `test: 2.5` or `test: 2` (matching qa/smoke) is a one-line change that likely un-flakes some Family A retries without touching test bodies. Small helper change; preserves PR #65 thesis.

### Recommended path forward

- **Not yet** run tests. Confirm with Josh:
  - Q1: OK to regenerate `playwright/storage/test/` before running Phase 0 comparisons? (Alternative: run stale-first to prove the hypothesis, then refresh — costs one wasted test run.)
  - Q2: Are two-test and qa the same backend user DB? (If yes, session_salt rotation from qa auth invalidates test states. If no, Finding 3 is a coincidence.)
  - Q3: OK to fix `ENV_TIMEOUT_MULTIPLIER` for two-test in the same task (small helper change, aligned with PR #65 thesis), or scope-out?

## Family C: RESOLVED (two-layer fix) — verdict = (c) test-quality bugs PR #65 missed

### Layer 1: missing firm_settings_cache



Josh ran `generateStorageStates.mjs` for `TEST_ENV=test`, then re-ran QA-101 by itself. New failure trace showed:
```
⚠️ Storage state file for user "Admin" not found at: .../playwright/storage/test/storageState_Admin.json
🚀 Testing user detected (Admin). Ensuring session via storage state...
🔍 Verifying dashboard access for session stability...
[20s timeout on topbar locator]
```

Root cause:
- QA-101 (`qa-101-client-merging.test.ts:60-72`) and QA-204 (`qa-204-client-approval-upon-submit.test.ts:37-56`) both start with a `Pre-condition: Enable Firm Setting` describe block using `test.use({ user: 'Admin' })`.
- The block is skipped when `checkFirmSettingCached('Demo Broadcasting', 'clientApprovalRequired', true)` returns true (`qa-101:58-64`, `qa-204:35-42`).
- `checkFirmSettingCached` (`FirmOptionsHelper.ts:206-232`) reads `<STORAGE_DIR>/firm_settings_cache.json` and returns true when the entry matches and `age < 7 days`.
- `playwright/storage/qa/firm_settings_cache.json` exists (Jul 22, 145B) with a **sentinel future timestamp `1800000000000` = 2027-01-01** so `age = Date.now() - future` is negative → always passes the 7-day gate. Effectively "never expires."
- `playwright/storage/test/firm_settings_cache.json` **never existed**.
- On qa: cache hit → Admin block skipped → tests pass.
- On two-test: cache miss → Admin block runs → no `storageState_Admin.json` in `test/` (the Admin login flow has never generated one anywhere) → `assumeUser` (`loginHelper.mjs:212-237`) navigates to baseURL with an anonymous context, lands on the login page, and waits 20s for a topbar that only appears post-auth. Family C surfaces.
- Additionally: `generateStorageStates.mjs` DOES include Admin (`imail-test+... no, doc+test_admin@vcreativeinc.com`) in its user list, but no `storageState_Admin.json` exists in either `qa/` or `test/` — the Admin generation has been silently failing for a while (probably missing `ADMIN_TEST_PASSWORD` or the Admin login path differs). Not blocking Family C's fix (cache mirror bypasses it), but worth a follow-up task.

Fix landed: `playwright/storage/test/firm_settings_cache.json` mirroring qa's content. Zero code change. Category (c) — PR #65 authored the qa cache but didn't mirror to `test/`.

Verification run (Josh, QA-101 on two-test): cache hit succeeded, Admin block skipped, DemoSalesExec logged in, dashboard reached, QO form opened, client autocomplete + typo new-client flow completed — **all previously-broken steps now green**. New failure surfaced downstream (see Layer 2).

### Layer 2: `createOrderWithNewClient` had a naked, unhardened `getByText('Select Status').click()`

Once Layer 1 unblocked the DemoSalesExec flow, QA-101 failed 30s later at `OrderHelper.ts:1834`:
```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for getByText('Select Status')
   at createOrderWithNewClient (.../OrderHelper.ts:1834:43)
```

Diagnosis: three touch-points of `page.getByText('Select Status')` in `OrderHelper.ts`:

- L1280–L1281 & L1334–L1335 — inside `createBasicOrder`, wrapped in PR #65's hardened retry loop with PrimeNG-overlay fallback selectors.
- L1834 — inside `createOrderWithNewClient`, **naked click**, no retry, no `dismissBlockingOverlays`, no fallback.

`createOrderWithNewClient` is a copy-paste sibling of `createBasicOrder`'s tail that PR #65's healing skipped. Called by QA-101 (`:143`), QA-204 (`:78`), and imported (but not necessarily called) by QA-157. On qa this raw click succeeds because qa's DOM is quiet; on two-test an overlay/render race blocks it within 30s. Category (c) — divergent forks of the same code path, only one hardened.

Fix landed: extracted the ~70-line hardened block from `createBasicOrder:1272-1343` into a new exported helper `selectQOStatus(page, status)` (`OrderHelper.ts:1106`). Both `createBasicOrder` (line 1359) and `createOrderWithNewClient` (line 1850) now call it. Zero test-file changes. Preserves PR #65's shared-helper thesis *more strictly* than PR #65 itself did.

Sanity checks:
- Grep confirms all 4 `getByText('Select Status')` references are contained in the helper.
- `npx tsc --noEmit --project playwright/tsconfig.json` reports only two pre-existing unrelated errors in `playwright/utils/prf/*Helper.ts` (unused `@ts-expect-error` directives from another feature).

**Risk**: if `clientApprovalRequired` is actually FALSE on two-test's Demo Broadcasting firm, the Layer-1 cache lies and downstream approval-flow subtests may fail differently. Cheapest way to find out is the next test run.

## Systemic finding (Josh-flagged priority)

`ENV_TIMEOUT_MULTIPLIER` at `setup.ts:128` still gives test env 1× (comment claims "localhost" but two-test.vcreative.net is remote). Not the primary cause of Family A, but adds an unnecessary tightness on every `test.setTimeout(N * ENV_TIMEOUT_MULTIPLIER)`. Recommend a separate one-liner change (`test: 2` or `test: 2.5`) — out of scope for this task unless Josh flips it.

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Task branch + file created on `task/heal-13-playwright-failures-on-two-test`
- Playwright config + storage state + timing multiplier audit
- Family C root cause identified: missing `firm_settings_cache.json` in `test/`
- Fix landed: cache mirror

### Family C — 4 layers of stacked fixes (multi-cause)

| Layer | Root cause | Verdict | Fix |
|---|---|---|---|
| 1 | `playwright/storage/test/firm_settings_cache.json` never authored (PR #65 authored only qa side) | (c) test-quality bug PR #65 missed | Mirror qa's cache file to `test/` |
| 2 | `createOrderWithNewClient` had a naked, unhardened `getByText('Select Status').click()` at OrderHelper.ts:1834 while its sibling `createBasicOrder` was hardened by PR #65 | (c) test-quality bug PR #65 missed | Extract `selectQOStatus(page, status)` shared helper; both call sites use it |
| 3 | selectQOStatus's retry loop fired unconditional `page.keyboard.press('Escape')`; two-test's QO sidebar wires Escape to a "Are you sure you want to close the sidebar?" confirmation | (c) test-quality bug PR #65 missed | Gate Escape on `.p-select-overlay:visible \| .p-dropdown-panel:visible` |
| 4 | QO Status field can be prepopulated on load (varies by firm/user/ad-type per Josh 2026-08-12); placeholder-anchored locators find nothing when field is filled | **expected variation** (not env-drift as first suspected) | Early-return if field already shows target value; add structural fallback `label:has-text("Status") + p-select` for prepopulated-non-target case |

Josh's clarification: Layer 4 is not "env-drift" — it's expected variation the QO form exhibits. Two-test happens to be prefilled today, but qa or another firm could be tomorrow. Saved as project memory `project_qo_status_prepopulation.md`.

### Family Status
- **A** — pending (selectStatus 4-attempt failure; likely resolves as a downstream benefit of Layer 3+4 shared-helper hardening since `createBasicOrder` also calls selectQOStatus now; needs a real test run to confirm)
- **B** — pending (locator waitFor timeout; QA-196 already documented as env-different; VC2-9225/VC2-9267 unknown)
- **C** — **FIXED across 4 layers** (see table)
- **D** — pending (Send button never enables; QA-279)
- **E** — pending (Due by missing fields; QA-203 form validation)
- **F** — pending (search yields nothing; QA-185 data condition)

### Follow-up tasks surfaced (out of scope for this task)
- Fix `generateStorageStates.mjs` Admin flow so `storageState_Admin.json` actually lands in both envs (systemic; blocks any test that opts into `user: 'Admin'` when cache is invalid).
- Fix `ENV_TIMEOUT_MULTIPLIER` for two-test env.
- Consider making `checkFirmSettingCached` fail loudly instead of silently returning false when the cache file is missing — the silent miss is what caused Family C to look like a shared-helper failure instead of a missing artifact.
