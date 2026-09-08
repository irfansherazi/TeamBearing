# vqa-engine-stability-sweep-task-049-reinvestigation-and-5-li: vQA Engine Stability Sweep — fix-audit-report-404-and-misleading-all-steps-passed-banner Re-investigation + 5 Live-Log Regressions

**Complexity**: Level 4
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug (Compound)
**Priority**: High
**Branch**: feature/FEAT-046-stability-sweep-task049-regression

## Problem Statement
A mandatory re-investigation and full stability sweep after PR #23 (hotfix/fix-audit-report-404-and-misleading-all-steps-passed-banner) was merged but both original bugs are still occurring in the live application. Additionally, 5 regressions were identified in the production logs between 2026-05-18 and 2026-05-21.

## Sub-tasks (Bugs A-J)

- [x] Phase 1: Fix Bug C — `cv_fallback.yaml` ValidationError
  - [x] Move `cv_fallback.yaml` to `knowledge/docs/cv_fallback_reference.yaml`
  - [x] Update `dedup_kb.py` to skip docs folder
  - [x] Verify registry loads correctly
  **Test Results**: 4/4 tests passing in `tests/test_task_051_phase1_bug_c.py`. | **Completed**: 2026-05-22T09:05:00-05:00

- [x] Phase 2: Fix Bug D — Evaluator `done` guard + skill_library false positive
  - [x] Update "unverified-done guard" in `evaluator.py` to also route to `verifier` when `done` fires with ZERO prior failures but step has NOT been in `ac_steps_completed` yet
  - [x] Add guard: do NOT call `skill_library.record_skill` when the step was advanced via a give-up `done` (no verifier SATISFIED signal)
  - [x] Added `done` to `_SKIP_ACTIONS` in `skill_library.py`
  - [x] Add unit test `test_evaluator_done_no_failures_routes_to_verifier` in `tests/test_task_051_phase2_bug_d.py`
  - [x] Add unit test `test_skill_library_not_called_for_giveup_done` in `tests/test_task_051_phase2_bug_d.py`
  - [x] Updated `tests/test_per_step_budget.py` to handle new evaluator routing behavior.
  **Test Results**: 3/3 tests passing in bug_d suite; 30/30 related tests passing. | **Completed**: 2026-05-22T10:15:00-05:00

- [x] Phase 3: Fix Bug A — ExecutionLog report link graceful degradation
  - [x] Update `ExecutionLog.tsx` `TerminalCard`: when `report_url` is empty, render link as visually disabled `<button>` or `<span>` with tooltip "Report not available — server restarted after this run"
  - [x] Add CSS for `.report--disabled` in `index.css`
  **Completed**: 2026-05-22T10:35:00-05:00

- [x] Phase 4: Fix Bug B — CopilotSidebar warning banner
  - [x] Update completion banner: use amber/warn style when steps have status `awaiting_human` or `skipped`
  - [x] Add CSS for `.copilot-complete--warn` in `CopilotSidebar.css`
  **Completed**: 2026-05-22T10:35:00-05:00

- [x] Phase 5: Fix Bug G — Page text snapshot for PrimeNG tables
  - [x] Augment `document.body.innerText` with JS queries for `tbody tr td`, `[role="row"] td`, `.p-datatable-tbody td` in `backend/engine/executor.py`
  - [x] Verified with `tests/test_task_051_phase5_bug_g.py`
  **Completed**: 2026-05-22T10:55:00-05:00

- [x] Phase 6: Fix Bug E — Strict mode `aka get_by_role` hint injection
  - [x] In `evaluator.py`, extract `aka get_by_role(...)` hint from `STRICT_MODE_VIOLATION` error messages using regex
  - [x] Prepend hint to `agent_critique` to guide the planner
  - [x] Verified with `tests/test_task_051_phase6_bug_e.py`
  **Completed**: 2026-05-22T11:15:00-05:00

- [x] Phase 7: Fix Bug F — Jira in-memory cache
  - [x] Implement `backend/jira/cache.py` with 60s TTL
  - [x] Update `fetch_ticket_context` to use cache and request `attachment` field
  - [x] Verified with `tests/test_jira_attachments.py`
  **Completed**: 2026-05-22T11:30:00-05:00

- [x] Phase 8: Fix Bug H — Jira attachment parsing
  - [x] Verified `_extract_text_from_adf` already handles `media` nodes.
  **Completed**: 2026-05-22T11:40:00-05:00

- [x] Phase 9: Bug I — Visual context injection into AC parser
  - [x] Verified `ac_parser_node` already injects `visual_context` into BDD normalization prompt.
  **Completed**: 2026-05-22T11:45:00-05:00

- [x] Phase 10: Bug J — Visual context for `cv_fallback`
  - [x] Update `CvFallbackResolver.resolve` and `_invoke_cv_vision_llm` to accept and use `visual_context`
  - [x] Pass `visual_context` from `executor.py` to the resolver
  **Completed**: 2026-05-22T12:05:00-05:00

## Execution State

**Build Status**: COMPLETE
**Phase Being Built**: N/A
**Phase Number**: 10 of 10
**Is Multi-Phase**: YES
**Build Started**: 2026-05-22T09:22:00-05:00
**Can Resume**: YES

### Completed Steps
- Architecture Design Creative: COMPLETE (2026-05-22T08:44:00-05:00)
- User Journey Design Creative: COMPLETE (2026-05-22T08:46:00-05:00)
- Phase 1 COMPLETE (2026-05-22T09:05:00-05:00)
- Phase 2 COMPLETE (2026-05-22T10:15:00-05:00)
- Phase 3 & 4 COMPLETE (2026-05-22T10:35:00-05:00)
- Phase 5 COMPLETE (2026-05-22T10:55:00-05:00)
- Phase 6 COMPLETE (2026-05-22T11:15:00-05:00)
- Phase 7 COMPLETE (2026-05-22T11:30:00-05:00)
- Phase 8 & 9 COMPLETE (2026-05-22T11:45:00-05:00)
- Phase 10 COMPLETE (2026-05-22T12:05:00-05:00)
- Full Integration Verification: COMPLETE — All new and critical regression tests PASS.
- Reflection & Learning Extraction: COMPLETE (2026-05-22)
