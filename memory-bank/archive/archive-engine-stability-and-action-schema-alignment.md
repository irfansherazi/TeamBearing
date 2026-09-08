# engine-stability-and-action-schema-alignment: Engine Stability and Action Schema Alignment

**Feature**: FEAT-067  
**Phase**: ARCHIVE  
**Status**: COMPLETE  
**Created**: 2026-06-01  
**Completed**: 2026-06-01  
**Complexity**: Level 3  
**Branch**: feature/FEAT-067-engine-stability

---

## Problem Statement

The vQA engine currently suffers from stability issues and schema desynchronization:
1. **Stagnant UI False Positives**: Actions like `scroll`, `press_key`, and `coordinate_action` are incorrectly flagged as "STAGNANT UI" because they may not result in an immediate DOM delta, leading to aggressive circuit breaker loops.
2. **Schema Gaps**: The `PlannerAction.strategy` literal in `schemas.py` is missing `window` and `coordinate_action`, causing validation errors when these strategies are emitted.
3. **Locator Resolution Errors**: The executor's `_resolve_locator` function fails when encountering these non-traditional strategies, which in turn causes failures in RAG-based selector validation.

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `scroll`, `press_key`, and `coordinate_action` do not trigger "STAGNANT UI" errors in `verifier.py`. |
| AC-2 | `PlannerAction.strategy` in `schemas.py` includes `window` and `coordinate_action` in its `Literal`. |
| AC-3 | `executor.py` handles `window` and `coordinate_action` without RAG locator resolution errors. |
| AC-4 | Comprehensive unit tests verifying the exemptions and schema alignment. |

---

## Test Strategy

### Unit Tests
- `tests/engine/test_task_087_stagnant_exemptions.py`:
  - Verify `scroll`, `press_key`, and `coordinate_action` bypass the stagnant UI check.
- `tests/engine/test_task_087_schema_alignment.py`:
  - Verify `PlannerAction` validates successfully with `strategy="window"` or `strategy="coordinate_action"`.
  - Verify `_resolve_locator` handles these strategies gracefully.

---

## Proposed Changes

### 1. Verifier Logic
- Update `backend/engine/verifier.py` to add `scroll`, `press_key`, and `coordinate_action` to the stagnant UI exception list.

### 2. Schema Definition
- Update `backend/engine/schemas.py` to include `window` and `coordinate_action` in the `strategy` `Literal`.

### 3. Executor Logic
- Update `backend/engine/executor.py`'s `_resolve_locator` to explicitly handle `window` and `coordinate_action` by returning `None` or a no-op locator, ensuring it doesn't raise `ValueError`.
`ValueError`.
