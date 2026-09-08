# Archive: kb-tf-idf-minimum-similarity-threshold — KB TF-IDF Minimum Similarity Threshold

**Archived**: 2026-06-03  
**Status**: COMPLETE  
**Complexity**: Level 2  
**Feature**: FEAT-088 (KB TF-IDF Minimum Similarity Threshold)  
**Branch**: `feature/FEAT-088-kb-min-similarity-threshold`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/main

---

## What Was Built

We implemented a configurable cosine-similarity threshold gate for the historical successful test plans RAG in `TestPlanVault` to filter out low-similarity or completely unrelated matches when queries are vague. This prevents noisy, misleading past plans from being injected into the AC parser and downstream LLM steps as context.

### Key Design Decisions
- **Cosine Distance-to-Similarity Conversion**: Because ChromaDB uses a cosine distance space where identical matches have a distance of `0.0`, we map distance to similarity as `similarity = 1.0 - distance` (yielding `1.0` for identical matches and `0.0` or negative for orthogonal/opposite vectors) before applying filtering logic.
- **Configurable Global & Query-Time Gate**: Created `kb_min_similarity_score` on the global Pydantic `Settings` in `backend/config.py` (representing the `KB_MIN_SIMILARITY_SCORE` env var, defaulted to `0.2`), and supported an explicit query-time override `min_score` in `TestPlanVault.query_plans()` for downstream calling flexibility.
- **Robust Nesting Bounds Safety**: Handled ChromaDB's double-nested list structure (`metadatas[0]`, `distances[0]`) using robust guard clauses to prevent index out of bounds or TypeErrors when the collection is empty or query results are missing expected keys.
- **High-Speed Zero-Dependency Testing**: Mocked the nested response structures of the ChromaDB PersistentClient and collection query output using dictionaries. This eliminates any network or local ONNX execution overhead, keeping test runs under 50ms without initializing heavy sentence-transformer models.

---

## Implementation Summary

### Files Changed (4 files, +214 net lines changed)

| File | Change |
|------|--------|
| `backend/config.py` | Defined global `kb_min_similarity_score` parameter (type `float`, default `0.2`) on Pydantic `Settings` with env var mapping to `KB_MIN_SIMILARITY_SCORE`. |
| `backend/kb/rag.py` | Added `min_score: Optional[float] = None` to `TestPlanVault.query_plans()`. Mapped cosine distance to similarity score, filtered query results below the effective score, and returned empty lists safely if all results are filtered. |
| `.env.example` | Added documentation and a standard default configuration line for `KB_MIN_SIMILARITY_SCORE=0.2`. |
| `tests/test_feat_088_min_score.py` | Created 5 unit tests validating global configuration defaults, query-time override parameters, threshold math filtering boundaries, and empty collection retrieval safety. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Tests written | 5 brand-new |
| Tests passing | 5/5 (100%) |
| Dependent tests passing | 5/5 (100%) |
| Regressions introduced | 0 |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| AC-HAPPY-1 | ✅ PASS | Configurable similarity threshold variable `kb_min_similarity_score` loaded via `backend/config.py` with `0.2` default and documented in `.env.example`. |
| AC-HAPPY-2 | ✅ PASS | `TestPlanVault` correctly calculates `similarity = 1.0 - distance` and gates matching results under the threshold. |
| AC-HAPPY-3 | ✅ PASS | Gating returns an empty list `[]` instead of noisy matches when all retrieval distances are too high. |

---

## Rule Consolidation (Archive Phase)

No active rules were pruned because all rules remain highly accurate.

**Files amended/reviewed in reflection**:
- `memory-bank/reflection/reflection-kb-tf-idf-minimum-similarity-threshold.md` captures:
  - Cosine Distance vs Cosine Similarity in Vector DBs
  - ChromaDB Mocking Dual List Layout

---

## Retrospective Notes

See full reflection at [reflection-kb-tf-idf-minimum-similarity-threshold.md](../reflection/reflection-kb-tf-idf-minimum-similarity-threshold.md).

**Key Learnings**:
- **Distance-to-Similarity Gating**: Vector databases configured with `hnsw:space = cosine` return distance, which must be subtracted from `1.0` to represent standard cosine-similarity (where higher is better).
- **Double List Nesting in ChromaDB Mocking**: ChromaDB collections support batch queries, meaning results under `"distances"` and `"metadatas"` are arrays of arrays (e.g. `[[dist1, dist2]]`). Mock query objects must reflect this layout to be verified correctly by collection handlers.

---

## Next Work

- **intelligent-ingestion-and-pre-flight-verification: Intelligent Ingestion & Pre-Flight Verification (FEAT-070)** — Implement hybrid LLM-in-the-Loop Enricher and negative path scenario verification.
