---
version: next
linked_tasks: [heal-playwright-tests-round4]
status: completed
---

### Round-4 Playwright Suite Heal — 16 Failing Tests
- **Version**: next
- **Status**: completed
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Heal 16 failing Playwright tests on `qa.vcreative.net`. Diagnosis is pre-supplied and grouped into 3 root causes: (RC1) `OrderHelper.selectStatus()` PrimeNG v19 overlay race — 11 tests; (RC2) shared PrimeNG `.p-overlay-mask` hazard on post-overlay clicks — 4 tests (QA-58/59, QA-196 x3, VC2-9225, QA-359 pending investigation); (RC3) 3 independent leaves (QA-203 `exact:true` miss on test file, VC2-9267 enable-transition race, QA-185 verification only). Favors helper hardening (durable artifacts) over per-test patches where 2+ tests share a symptom.
- **Linked Tasks**: heal-playwright-tests-round4 (COMPLETE 2026-08-11)
- **Branch**: feature/heal-playwright-tests-round4
- **Created**: 2026-08-10
- **Completed**: 2026-08-11
- **Archive**: memory-bank/archive/heal-playwright-tests-round4-archive.md
