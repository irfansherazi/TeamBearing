# Archive: Codegen Transformer — Auto-refactor recorded tests to use project helpers

## Metadata
- **Task ID**: codegen-transformer-auto-refactor-recorded-tests-to-use-proj
- **Roadmap Feature**: FEAT-112
- **Complexity**: Level 2
- **Completed**: 2026-07-14
- **Branch**: feature/FEAT-112-codegen-transformer (committed directly to `main`, Worktree: N/A)
- **Key Commits**: `4fe7ee2` (Phase 1), `8403af5` (Phase 2), `cc7b973` (Reflection)

## Summary

Added the observable instrumentation layer on top of the pre-validated codegen transformer pipeline. When a user closes a Playwright recording browser, `codegen_session.py` now calls `transform_and_analyze()` instead of `transform_recorded_test()`, receives a transformation summary dict, and broadcasts it as a `transformations` key in the `recording_done` WebSocket payload. The RecordDemoModal "done" panel renders a human-readable Transformations row (e.g., "Auth fixture · 2 date helpers · 1 ⚠️ FRAGILE") when the key is present. Graceful degradation is preserved: if Bedrock fails, raw code is still committed and the `transformations` key is absent from the payload.

## Solution

### Phase 1: `_analyze_transformations` + Tests

Added `_analyze_transformations(transformed_code: str) -> dict` to `backend/engine/codegen_transformer.py`. Uses regex counting to inspect the transformer's output and returns a 5-key dict:

```python
{
    "auth_applied": bool,       # test.use(  OR from '../utils/setup' import
    "date_helpers": int,        # calculateDueDate/StartDate/EndDate/DueDateTime calls
    "nav_helpers": int,         # goToFolder calls
    "fragile_warnings": int,    # // ⚠️ FRAGILE: comment occurrences
    "captcha_helpers": int,     # resolveCaptcha calls
}
```

Also added `transform_and_analyze(raw_code, ticket_id) -> tuple[str, dict | None]` as the new primary entry point, keeping `transform_recorded_test` as a thin backward-compatible wrapper.

Created `tests/test_codegen_transformer.py` with 8 unit tests across 3 classes:
- `TestStripFences` (4 tests): typescript fence, ts fence, no fence, trailing-only fence
- `TestTransformRecordedTest` (2 tests): mocked Bedrock success path; Bedrock raises → returns raw
- `TestAnalyzeTransformations` (2 tests): code with helpers → correct counts; no helpers → all zeros

### Phase 2: WS Payload + RecordDemoModal Transformations Row

- `codegen_session.py` (lines 362–394): swapped `transform_recorded_test` for `transform_and_analyze`, conditionally adds `transformations` to the `result` dict before broadcasting
- `frontend/src/types.ts`: added `CodegenTransformations` interface and optional `transformations?: CodegenTransformations` field on `CodegenDoneEvent`
- `frontend/src/components/RecordDemoModal.tsx`: added `formatTransformations` helper and conditional `<Transformations>` label/value row in the done panel

## Files Changed

| File | Change |
|------|--------|
| `backend/engine/codegen_transformer.py` | Added `_analyze_transformations`, `transform_and_analyze`; refactored `transform_recorded_test` as thin wrapper |
| `tests/test_codegen_transformer.py` | New — 8 unit tests (created) |
| `backend/engine/codegen_session.py` | Swapped to `transform_and_analyze`; conditional `transformations` in WS payload |
| `frontend/src/types.ts` | Added `CodegenTransformations` interface; optional field on `CodegenDoneEvent` |
| `frontend/src/components/RecordDemoModal.tsx` | Added `formatTransformations` helper + conditional Transformations row |

## Acceptance Criteria Verification

| AC | Status | Evidence |
|----|--------|---------|
| AC-1: pytest passes with 8+ tests | ✅ | 8 tests in `tests/test_codegen_transformer.py` |
| AC-2: `_strip_fences` handles all fence variants | ✅ | `TestStripFences` 4-case coverage |
| AC-3: Bedrock failure returns raw code | ✅ | `test_bedrock_failure_returns_raw_code` |
| AC-4: `_analyze_transformations` returns 5-key dict | ✅ | `TestAnalyzeTransformations` 2-case coverage |
| AC-5: `codegen_session.py` includes `transformations` in payload | ✅ | Lines 362–394, guarded by `if transformations is not None` |
| AC-6: `CodegenDoneEvent` has optional `transformations` field | ✅ | `frontend/src/types.ts` |
| AC-7: RecordDemoModal renders Transformations row | ✅ | `RecordDemoModal.tsx` conditional row |

## Key Design Decisions

1. **`transform_and_analyze` returns `tuple[str, dict | None]`** — `None` is the graceful-degradation signal; callers use an `if transformations is not None` guard rather than try/except. Avoids a second Bedrock call.
2. **Regex analysis (not AST)** — transformer output conforms to well-defined system-prompt patterns; regex is sufficient and far simpler than a TypeScript AST parser.
3. **`auth_applied` OR-signal** — checks both `test.use(` and the setup import, making it robust to code that imports setup without an explicit `test.use` call.
4. **Conditional WS key** — `transformations` is omitted entirely on failure (not sent as `{}`), preserving forward compatibility with older UI versions.

## Patterns Extracted

- **`async-service-boundary-mocking`** → `agent-rules/_learned/testing-patterns.md`: patch at `_call_*` coroutine boundary with `AsyncMock`, not at the SDK client level
- **`pipeline-transform-and-analyze-tuple`** → `agent-rules/_learned/backend-api-patterns.md`: combined tuple-returning function for pipeline steps that transform and analyze atomically

## Technical Debt Noted

- `_analyze_transformations` does not count `generateRandomSpotTitle`, `generateRandomISCI`, or `generateRandomCartId` usage — a future `data_generators` metric can be added without breaking the dict shape
- Integration tests covering the full `monitor_session → transform_and_analyze → WS broadcast` pipeline are absent (out of scope; would require boto3-level mocking)

## Reflection

Full reflection document: `memory-bank/reflection/reflection-codegen-transformer-auto-refactor-recorded-tests-to-use-proj.md`

**Task Quality**: ✅ All 7 ACs met in a single build session with zero test failures  
**Ecosystem Effectiveness**: ✅ Highly Effective — well-scoped plan drove implementation without ambiguity
