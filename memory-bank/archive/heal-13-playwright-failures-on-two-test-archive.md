---
slug: heal-13-playwright-failures-on-two-test
type: archive
status: COMPLETE
complexity: Level 1
completed: 2026-08-12
branch: task/heal-13-playwright-failures-on-two-test
pr_target: main
verification_status: pending
---

# Archive — heal-13-playwright-failures-on-two-test

**Task**: Heal 13 Playwright failures on two-test — investigate before fixing.
**Complexity**: Level 1 (investigative bug cluster; no roadmap feature)
**Duration**: ~1 session, 2026-08-12
**Branch**: `task/heal-13-playwright-failures-on-two-test` (9 commits ahead of `main` before archive; 12 after archive commits)

## Summary

Diagnosed 13 nightly Playwright failures on `two-test.vcreative.net` after PR #65 (`feature/heal-playwright-tests-round4`, merged 2026-08-11) healed them against `qa.vcreative.net`. Established that the failures were not 13 test bugs but a small number of hidden couplings to qa's incidental config state. Landed a 4-layer fix stack targeting the Family C root cause plus three "surface silent failures" follow-ups aligned with PR #65's shared-helper thesis. Family A (5 tests using `createBasicOrder`) is expected to inherit the fix through the shared helper this task introduced; Families B, D, E, F remain unaddressed pending re-run signal.

## Deliverables (12 commits on branch)

1. `daa7107` — task file created
2. `de9df25` — Phase 0 evidence report (structural findings, no test runs)
3. `307bf91` — Layer 1: mirror `firm_settings_cache.json` to `test/` env
4. `8fb00bd` — Layer 2: extract `selectQOStatus(page, status)` shared helper; both `createBasicOrder` and `createOrderWithNewClient` call it
5. `dc33e16` — 3 follow-ups: `ENV_TIMEOUT_MULTIPLIER` fix for `test` env, `checkFirmSettingCached` loud warning, `generateStorageStates.mjs` failure summary
6. `8249d60` — Layer 3: `dismissBlockingOverlays` prefix + gated Escape in `selectQOStatus`
7. `9eabd3b` — Layer 4: early-return when Status field already shows target
8. `63b88ea` — Layer 4 refinement: structural `label:has-text("Status") + p-select` fallback for prepopulated-non-target case + project memory saved
9. `c2cc864` — 16 refreshed `playwright/storage/test/*.json` states
10. `3cb9281` — reflection document
11. (this archive commit) — archive doc + `_learned/` consolidation + task COMPLETE

## Root cause taxonomy — Family C (fixed) : 4 layers of stacked issues

| Layer | Root cause | Category |
|---|---|---|
| 1 | `playwright/storage/test/firm_settings_cache.json` never authored (PR #65 authored only qa's copy, with a year-2027 sentinel timestamp treating "never expires" as convention) | (c) test-quality bug PR #65 missed |
| 2 | `createOrderWithNewClient` had a naked `getByText('Select Status').click()` at `OrderHelper.ts:1834`; its sibling `createBasicOrder` was hardened by PR #65 | (c) test-quality bug PR #65 missed |
| 3 | `selectQOStatus`'s retry loop pressed Escape unconditionally; two-test's QO sidebar catches Escape as "close sidebar?" confirmation. Additionally, `dismissBlockingOverlays` (built by PR #65) was never called from the QO flow. | (c) test-quality bug PR #65 missed |
| 4 | QO Status field can be prepopulated on load (varies by firm/user/ad-type per Josh — not env-drift). Existing locators were placeholder-anchored. | expected variation (widened locator + early-return) |

## Provisional verdicts for the other families (pending targeted verification)

| Family | Tests | Provisional verdict | Notes |
|---|---|---|---|
| A | QA-46, QA-157, QA-172, QA-197, WebKit QO Baseline (5 tests) | Likely fixed as a side effect | `createBasicOrder` inherits Layers 3+4 through `selectQOStatus`; needs a real test run to confirm |
| B | QA-196, VC2-9225, VC2-9267 (3 tests) | Mixed — QA-196 documented as env-different in commit `2c74deb`; VC2-9225 and VC2-9267 unknown | Needs targeted investigation |
| D | QA-279 (1 test) | Unknown | Send button never enables; file-attach flow |
| E | QA-203 (1 test) | Unknown | Form validation "Due by missing fields"; likely env-drift on required-field set or date-picker binding |
| F | QA-185 (1 test) | Unknown | Search yields nothing; two-test data condition |

## Follow-up tasks surfaced (out of scope for this task)

- **`storageState_Admin.json` still missing in both `qa/` and `test/` envs.** The new loud generator summary will surface WHY on the next run (auth failure, missing password, etc.). Actual fix is a separate small task.
- **Verify Family A on two-test.** After a real test run — should be a no-op if Layers 3+4 in `selectQOStatus` did their job.
- **Diagnose Families B/D/E/F individually.** Each is likely a similar-shape isolated env-drift or missing-artifact issue; unlikely to share a common root cause.
- **Consider a pre-nightly linter** (`checkAllEnvsHaveArtifact()`) that ensures every path under `playwright/storage/qa/` has a mirror in every other configured env. Would have caught Layer 1 before it reached a failed test.

## Verification status (explicit — required disclaimer)

Per Josh's stated preference ("Run tests before claiming a fix worked"), this archive proceeds without end-to-end green verification of any of the 13 failing tests on two-test. Josh has run QA-101 through Layer 3's diagnostic surface and confirmed the failure signature I was fixing; the Layer 4-refinement + storage-state-refresh commits have NOT been re-verified with a full QA-101 run. The archive is committed at Josh's explicit direction to close out and open the PR for review; the PR body carries the same disclaimer.

## Continuous learning consolidation

Two `_learned/` files updated (additive only — no mutations, no retirements, no expiry, no pruning):

- `browser-patterns.md`: +3 rules (`healed-tests-must-survive-every-env`, `dry-sibling-functions-during-healing`, `playwright-zero-resolution-locator`); +1 reinforcement to `shared-overlay-dismissal-helper` (PR #65 built the helper but did not wire it into QO flow — this task did). Evidence 4 → 5.
- `testing-patterns.md`: +1 rule (`loud-boundary-failures`, three concrete examples from this task). Evidence 5 → 6.

`agent-rules-index.md` reindex not run — the `_learned/` file count is already 40, well over the soft cap of 10; index maintenance is a separate consolidation task. Additive nature of this task's changes means the existing index remains directionally correct.

## Documentation

- Task file: `memory-bank/tasks/heal-13-playwright-failures-on-two-test.md` (status COMPLETE after this archive)
- Reflection: `memory-bank/reflection/heal-13-playwright-failures-on-two-test-reflection.md`
- Project memory (personal): `~/.claude/projects/-Users-joshschauer-Documents-vProMedia-vQA/memory/project_qo_status_prepopulation.md` — "QO Status field can be prepopulated"
