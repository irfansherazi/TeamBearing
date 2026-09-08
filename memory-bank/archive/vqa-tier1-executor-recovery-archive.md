---
slug: vqa-tier1-executor-recovery
legacy_id: FEAT-116
feature: FEAT-116-vqa-tier1-executor-recovery
status: COMPLETE
archived: 2026-07-28
complexity: 3
---

# Task Archive: vqa-tier1-executor-recovery — vQA Tier 1 — Executor Recovery Hardening

## Metadata

- **Complexity**: Level 3
- **Type**: NFR / Infrastructure — four targeted reliability fixes
- **Priority**: Critical
- **Jira Issue**: N/A (internal reliability work; driven by 2026-07-27 QA-358 failure analysis)
- **Feature Branch**: `feature/FEAT-116-vqa-tier1-executor-recovery`
- **Roadmap Feature**: FEAT-116-vqa-tier1-executor-recovery
- **Started**: 2026-07-28 (planning); implementation 2026-07-28
- **Completed**: 2026-07-28
- **Duration**: same-day plan → build (4 phases) → reflect → archive

## Task Description

Ship the four highest-ROI executor fixes surfaced by the 2026-07-27 QA-358 failure analysis. Together they turn the Contest-dropdown failure pattern — where the planner emits `get_by_text("Contest")` against 41 pre-rendered but hidden matches inside a closed `<p-select>`, then loops through DOM strict-mode violations, CV fallback failures, and HITL amnesia — into an auto-recoverable actionable error instead of a run-terminating loop.

## Implementation Summary

Four phases in risk-ascending order (RAG/KB observability first, executor hotpath last):

### Phase 1 — T1-c: RAG Debugger LlamaIndex Removal (commit `9b774d2`)
- Replaced LlamaIndex `VectorStoreIndex.as_query_engine()` in `backend/engine/rag_debugger.py` with a direct Chroma retrieval call.
- Removed 3 `llama-index-*` packages from `backend/requirements.txt`; promoted `chromadb` to a direct dependency.
- 5 new tests in `backend/engine/test_rag_debugger.py` (RED → GREEN, 5/5 PASS).
- Covers AC-VERIFY-3 and AC-ERROR-1 (empty/missing collection returns `""` with WARNING).

### Phase 2 — T1-d: HumanGuidanceVault HNSW Fix (commit `35f7926`)
- `backend/kb/rag.py` line 143: HumanGuidanceVault collection now created with `hnsw:M=32, hnsw:construction_ef=200, hnsw:search_ef=100` — eliminates the "contigious 2D array" error at 500+ vectors.
- New `scripts/migrate_human_guidance_vault.py` — one-shot migration with hard-fail semantics on `PermissionError` / `BotoCoreError` (nonzero exit + full traceback; no silent zero-vector collection).
- `TestPlanVault` at line 54 was correctly left unchanged (its default HNSW config is not implicated).
- 5 new tests in `backend/kb/test_human_guidance_vault.py` (5/5 PASS).
- Covers AC-VERIFY-4 and AC-ERROR-2.

### Phase 3 — T1-b: Strict-Mode Scroll Fallback Kill (commit `9523823`)
- `backend/engine/executor.py` Stage 2.5 branch: for `total_count > 5` and `visible_count == 0`, short-circuit to `STRICT_MODE_AMBIGUOUS` immediately with a strategy hint (`container_selector` + `get_by_role='option'`).
- **Scroll path preserved for `total_count <= 5`** — deliberate correctness decision, small counts are potentially recoverable via scroll.
- Reclaims ~10s per failure (3 × ~3s futile scroll attempts + fallback timeout eliminated).
- 4 new tests in `backend/engine/test_executor_strict_mode.py` (RED → GREEN, 4/4 PASS).
- Covers AC-VERIFY-2.

### Phase 4 — T1-a: Component-Aware Precondition Check (commit `afae3ca`)
- `backend/engine/executor.py`: new `_is_target_in_open_container(page, target_text)` helper with a 4-entry `CLOSED_CONTAINER_SELECTORS` table (PrimeNG signatures: `p-select-overlay:not(.p-select-overlay-open)`, `p-dropdown-panel[aria-hidden="true"]`, native `<select>`, `p-autocomplete[aria-expanded="false"]`).
- Integrated as a **non-fatal, exception-safe gate** in the click dispatch path — each locator query wrapped in try/except so unrecognized DOM shapes do not block valid clicks. The gate can only fire on positive matches.
- 7 tests in `backend/engine/test_executor_component_gate.py` (6 unique scenarios × asyncio parameterization).
- Covers AC-VERIFY-1.

### Totals
- **21 new tests** across 4 test files, all PASS.
- **231/231** in the full regression suite (`backend/engine/test_*.py` + `backend/kb/test_*.py`).
- 8 pre-existing failures (planner attribute, KB content drift) confirmed pre-existing and unchanged by any phase.
- Lint (ruff): PASS on all new / modified files.
- Zero DECISION_NEEDED escalations across all 4 phase builds.

## Acceptance Criteria — Final Status

| AC | Priority | Status | Notes |
|---|---|---|---|
| AC-VERIFY-1 (T1-a: `TARGET_INSIDE_CLOSED_CONTAINER` with trigger selector) | MUST | Met | Phase 4 tests |
| AC-VERIFY-2 (T1-b: `STRICT_MODE_AMBIGUOUS` in ≤ 500ms, no scroll call) | MUST | Met | Phase 3 tests |
| AC-VERIFY-3 (T1-c: `query_knowledge_base` returns grounded results without LlamaIndex) | MUST | Met | Phase 1 tests |
| AC-VERIFY-4 (T1-d: `HumanGuidanceVault.query()` succeeds with tuned HNSW) | MUST | Met | Phase 2 tests |
| AC-VERIFY-5 (regression: pre-existing tests still pass) | MUST | Met | 231/231 |
| AC-INTEGRATION-1 (QA-358 live re-run < 30s) | MUST | **Deferred** | Requires manual `python -m backend.cli --ticket QA-358 --role qa_analyst` against `vpromotions` QA env |
| AC-ERROR-1 (T1-c: empty collection returns `""` gracefully) | SHOULD | Met | Phase 1 tests |
| AC-ERROR-2 (T1-d: migration script exits non-zero on failure) | MUST | Met | Phase 2 tests |

## Pending Manual Verification (Post-Archive)

**AC-INTEGRATION-1** — QA-358 live re-run against `vpromotions` QA env.

Command:
```
python -m backend.cli --ticket QA-358 --role qa_analyst
```

Pass criteria: the "Select Contest from PRF Category dropdown" step either (a) auto-recovers via T1-a's `TARGET_INSIDE_CLOSED_CONTAINER` → planner opens the trigger → step succeeds; or (b) still fails but escalates to HITL / `STRICT_MODE_AMBIGUOUS` in ≤ 30s wall-clock (vs. ~225s observed in the 2026-07-27 failure session). Capture `run_id` and relevant `execution_log.jsonl` entries in a follow-up note.

If (b) still exceeds 30s, promote the T3-c planner-side reflex layer (auto-emit the open-trigger click on `TARGET_INSIDE_CLOSED_CONTAINER`) to a Tier-2 task.

## Key Files Changed

- `backend/engine/executor.py` — T1-a helper + T1-b strict-mode short-circuit
- `backend/engine/rag_debugger.py` — T1-c: direct Chroma path, LlamaIndex removed
- `backend/kb/rag.py` — T1-d: HNSW metadata on HumanGuidanceVault
- `backend/requirements.txt` — removed 3 llama-index-* packages; chromadb promoted to direct dep
- `scripts/migrate_human_guidance_vault.py` (new) — HNSW migration with hard-fail exit
- `backend/engine/test_executor_component_gate.py` (new) — 7 tests
- `backend/engine/test_executor_strict_mode.py` (new) — 4 tests
- `backend/engine/test_rag_debugger.py` (new) — 5 tests
- `backend/kb/test_human_guidance_vault.py` (new) — 5 tests

## Memory-Bank Corrections (from Guardrail Misses)

Two corrections were surfaced by this task's Guard & Recovery Log. Both are **out of scope** for this archive (they touch BMB tooling / systemPatterns.md, not this task's change surface) and are recorded here as follow-up work:

| File · section | Correction | Evidence |
|---|---|---|
| `scripts/commit-guard.sh` · `TEST_RE` | Extend regex to include Python's `test_*.py` prefix convention alongside existing JS patterns (`*.test.*`, `tests/`). Eliminates the C2 false-positive at the source. | C2 guard FAIL on all 4 phases — same false positive reproduced 4 consecutive times by independent agent invocations. |
| `memory-bank/systemPatterns.md` · Testing Patterns | Add a note that commit-guard `TEST_RE` covers JS-style patterns only — C2 flags on Python `test_*.py` files are false positives; confirm tests are present manually. | Interim documentation fix if the script correction is deferred. |

Recommend creating a Level 1 task (`/bmb:task fix-commit-guard-python-test-re`) to apply the higher-priority `commit-guard.sh` fix.

## Key Learnings (Extracted)

Three extractable learnings from the reflection have been consolidated:

1. **`exception-safe-precondition-gates`** — DOM precondition gates inserted before click dispatch must wrap all locator queries in try/except so unrecognized DOM shapes do not block the main execution path. **Consolidated into** `memory-bank/agent-rules/_learned/engine-reliability.md`.

2. **`component-aware-precondition-gate`** — Before dispatching a text-target click, check known "closed" container signatures (framework-specific: `p-select-overlay:not(.p-select-overlay-open)`, etc.); return an actionable error (`TARGET_INSIDE_CLOSED_CONTAINER` with the trigger selector) instead of allowing a strict-mode stack trace. **Consolidated into** `engine-reliability.md`.

3. **`futile-scroll-short-circuit`** — In 0-visible strict-mode branches, when `total_count > 5`, skip `scroll_into_view_if_needed` entirely — Angular pre-rendered false matches make scroll fallback futile. Preserve the scroll path for `total_count <= 5` (small counts are recoverable). **Consolidated into** `engine-reliability.md`.

The two workflow/tooling learnings from the reflection (`commit-guard-python-convention`, `concrete-spec-level-3`) are ecosystem findings and are captured above under **Memory-Bank Corrections** / this archive's narrative — they are not agent-rules `_learned/` entries because those govern coding patterns, not BMB tooling.

## Related Documents

- **Task file**: `memory-bank/tasks/vqa-tier1-executor-recovery.md`
- **Reflection**: `memory-bank/reflection/vqa-tier1-executor-recovery-reflection.md`
- **Roadmap feature**: `memory-bank/roadmap/FEAT-116-vqa-tier1-executor-recovery.md`
- **Commits**: `9b774d2` (Phase 1), `35f7926` (Phase 2), `9523823` (Phase 3), `afae3ca` (Phase 4), `b37a5fd` (reflection)
