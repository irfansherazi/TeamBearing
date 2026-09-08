# Archive: fair-quality-gate-hitl-pre-parse-guardrail — FAIR Quality Gate HITL Pre-Parse Guardrail

**Archived**: 2026-06-03  
**Status**: COMPLETE  
**Complexity**: Level 2  
**Feature**: FEAT-077 (P1 Jira Ingestion Gap P1-C)  
**Branch**: `feature/FEAT-077-fair-quality-gate-guardrail`  
**Merge Commit**: `003bdd4` → `main`  
**Repo**: https://github.com/vcreativeinc/vQA/commit/003bdd4

---

## What Was Built

A pre-parse HITL guardrail that intercepts FAIR-graded tickets (score 4–6/10) inside `ac_parser_node` before Stage 1 BDD Normalization runs. When triggered, the node broadcasts a `WSPreParseGuidanceMessage` WebSocket event, blocks on `asyncio.Event` until the operator responds, and then merges the operator's guidance into Stage 1.

### Key Design Decisions
- **Circular import avoidance**: State (`_pre_parse_events`) and broadcast helper live in `ac_parser.py`; both are re-exported from `routes.py` at module level via lazy imports
- **Re-run protection**: Guardrail skips if `pre_parse_guidance` already populated or `pre_parse_guidance_approved=True` — no double-blocking
- **Test isolation**: Module-level `autouse` fixtures mock AC step cache (always MISS) and KB pre-flight (empty return), preventing upstream short-circuits from hiding the guardrail code path

---

## Implementation Summary

### Files Changed (5 files, 1,158 net lines)

| File | Change |
|------|--------|
| `backend/engine/state.py` | `awaiting_pre_parse_guidance: bool` + `pre_parse_guidance_approved: bool` added to `VQAState` + `make_initial_state` |
| `backend/api/schemas.py` | `WSPreParseGuidanceMessage`, `StatusResponse.awaiting_pre_parse_guidance`, `ResumeRequest.pre_parse_guidance` + `.pre_parse_guidance_approved` |
| `backend/engine/ac_parser.py` | `_pre_parse_events` dict, `_broadcast_pre_parse_guidance_required` async helper, guardrail block, fixed dead-code bug (lines 1119–1128) |
| `backend/api/routes.py` | `resume_run` priority-checks `_pre_parse_events` before standard resume; re-exports `_pre_parse_events` + `_broadcast_pre_parse_guidance_required` |
| `tests/test_task_096_pre_parse_guardrail.py` | 22 TDD tests (new file) |

---

## Test Results

| Metric | Value |
|--------|-------|
| Tests written | 22 |
| Tests passing | 22/22 (100%) |
| Regressions introduced | 0 |
| Pre-existing failures | 44 (confirmed identical to baseline) |

---

## Acceptance Criteria Coverage

| AC | Status |
|----|--------|
| AC-ENTRY-1 (FAIR detected before Stage 1) | ✅ |
| AC-HAPPY-1 (awaiting_pre_parse_guidance set) | ✅ |
| AC-HAPPY-2 (WS warnings broadcast) | ✅ |
| AC-HAPPY-3 (guidance text injected into Stage 1) | ✅ |
| AC-HAPPY-4 (bypass approved, logged at INFO) | ✅ |
| AC-EDGE-1 (GOOD/POOR unaffected) | ✅ |
| AC-EDGE-2 (guidance available to Stage 1) | ✅ |
| AC-EDGE-3 (re-run with existing guidance skips guardrail) | ✅ |
| AC frontend panel (UI warning display) | ⏳ Deferred — separate frontend task |

---

## Rule Consolidation (Archive Phase)

**Pruned**: 6 stale 0x-reinforced bullets from `testing-patterns.md`  
(reporter-priority-override-test, status-enum-exhaustiveness, missing-dep-verification-noise, fraction-based-prompt-assertions, hook-unit-test-coverage, synthesis-llm-compiler-pattern)  
**Result**: 17 → 11 bullets (within 15-bullet max)

**Files amended in reflection**: `testing-patterns.md` (+3), `backend-api-patterns.md` (+1)

---

## Git History

| Commit | Description |
|--------|-------------|
| `99256de` | feat(fair-quality-gate-hitl-pre-parse-guardrail): FAIR guardrail pre-parse HITL interception |
| `53493fa` | reflect(fair-quality-gate-hitl-pre-parse-guardrail): Add reflection and continuous learning extraction |
| `003bdd4` | feat(FEAT-077): Merge fair-quality-gate-hitl-pre-parse-guardrail FAIR Quality Gate HITL Pre-Parse Guardrail |

---

## Retrospective Notes

See full reflection at [reflection-fair-quality-gate-hitl-pre-parse-guardrail.md](../reflection/reflection-fair-quality-gate-hitl-pre-parse-guardrail.md).

**Hardest part**: Discovering that the AC step cache was short-circuiting the quality gate before the guardrail could run — required `autouse` fixtures at module level mocking the cache and KB pre-flight. This learning is now captured as `autouse-fixture-layering` in `testing-patterns.md`.

**Incidental fix**: Removed dead-code block (duplicate unreachable `return` + `_ac_cache.set()` call) at lines 1119–1128 of the original `ac_parser.py`. This code was being executed on every POOR-grade run but never producing results.

---

## Next Work

- **Frontend panel** (deferred): `WSPreParseGuidanceMessage` type in `types/index.ts`, intercept in `useWebSocket.ts`, render warning panel in `RunningView.tsx`
- **Next FEAT-077 sub-task**: To be determined based on FEAT-077 remaining acceptance criteria
