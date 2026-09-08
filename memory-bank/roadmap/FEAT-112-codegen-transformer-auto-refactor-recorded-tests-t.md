---
legacy_id: FEAT-112
version: next
linked_tasks: [codegen-transformer-auto-refactor-recorded-tests-to-use-proj]
status: complete
---

  ### FEAT-112: Codegen Transformer — Auto-refactor recorded tests to use project helpers
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Automatic transformation step inserted between recording and commit that rewrites raw Playwright codegen TypeScript into a production-ready test using project helpers. Core transformer (`backend/engine/codegen_transformer.py`) and pipeline integration (`codegen_session.py`) are already prototyped and validated. Remaining work is tests + UI feedback.
    1. **`_analyze_transformations` helper**: Inspect the transformed code to produce a summary dict (auth_applied, date_helpers, nav_helpers, fragile_warnings, captcha_helpers).
    2. **Tests**: `tests/test_codegen_transformer.py` covering `_strip_fences`, `transform_recorded_test` fallback, and `_analyze_transformations`.
    3. **WS payload**: Include `transformations` key in the `recording_done` broadcast from `codegen_session.py`.
    4. **RecordDemoModal UI row**: Display transformation summary in the "done" panel (e.g., "Auth fixture · 2 date helpers · 1 ⚠️ FRAGILE").
- **Acceptance Criteria**:
    - AC-1: `tests/test_codegen_transformer.py` passes under `pytest tests/` with 8+ tests
    - AC-2: `_strip_fences` handles typescript fence, ts fence, no fence, trailing-only fence
    - AC-3: `transform_recorded_test` returns raw code on Bedrock failure (no raise)
    - AC-4: `_analyze_transformations` returns dict with auth_applied, date_helpers, nav_helpers, fragile_warnings, captcha_helpers
    - AC-5: `codegen_session.py` includes `transformations` key in `recording_done` WS broadcast after successful transform
    - AC-6: `CodegenDoneEvent` in `frontend/src/types.ts` includes optional `transformations` field
    - AC-7: RecordDemoModal "done" panel renders `Transformations` row when `result.transformations` is present
- **Key Files**:
    - `backend/engine/codegen_transformer.py` — Add `_analyze_transformations` function
    - `backend/engine/codegen_session.py` — Call `_analyze_transformations` and include in WS broadcast
    - `tests/test_codegen_transformer.py` — New test file
    - `frontend/src/types.ts` — Add optional `transformations` field to `CodegenDoneEvent`
    - `frontend/src/components/RecordDemoModal.tsx` — Add Transformations row to done panel
- **Linked Tasks**: codegen-transformer-auto-refactor-recorded-tests-to-use-proj
- **Branch**: feature/FEAT-112-codegen-transformer
- **Created**: 2026-07-14
