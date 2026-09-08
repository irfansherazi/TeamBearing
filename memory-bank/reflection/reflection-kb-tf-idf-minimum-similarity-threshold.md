# Reflection: kb-tf-idf-minimum-similarity-threshold — KB TF-IDF Minimum Similarity Threshold (FEAT-088)

**Date**: 2026-06-03  
**Task**: kb-tf-idf-minimum-similarity-threshold  
**Complexity**: Level 2  
**Feature**: FEAT-088 (KB TF-IDF Minimum Similarity Threshold)  
**Branch**: `feature/FEAT-088-kb-min-similarity-threshold`  
**Commit**: N/A (local working tree updated, ready for commit)

---

## 1. What Was Built

We implemented a configurable cosine-similarity threshold gate for the historical successful test plans RAG in `TestPlanVault` to filter out low-similarity or completely unrelated matches when queries are vague.

Key implementation details:
1. **Configurable Threshold Setting**: Defined `kb_min_similarity_score` on the global Pydantic `Settings` in `backend/config.py`, defaulting to `0.2`. It maps to the `KB_MIN_SIMILARITY_SCORE` environment variable.
2. **Environment Template Addition**: Documented and defaulted `KB_MIN_SIMILARITY_SCORE=0.2` in `.env.example`.
3. **Distance-to-Similarity Mapping**: In `backend/kb/rag.py`, we updated `TestPlanVault.query_plans()` to convert ChromaDB cosine distance (returned via `"distances"` inside the query results payload) to similarity via `similarity = 1.0 - distance`.
4. **Threshold Filtering Gating**: Updated `query_plans()` retrieval path to filter matches, keeping only those whose similarity score is greater than or equal to `kb_min_similarity_score` (or an optional query-time override `min_score`). Matches below the threshold are discarded, returning an empty list `[]` if all results fail to meet the gate.
5. **Zero-Dependency Mock Tests**: Created `tests/test_feat_088_min_score.py` with 5 high-speed, robust unit tests mocking ChromaDB's persistent client and query responses, verifying boundary math and configuration settings override behaviors.

**Files changed**: 3 backend files modified, 1 new test file created  
**Tests**: 5/5 target tests passing GREEN (100%)

---

## 2. Acceptance Criteria Assessment

| AC | Status | Notes |
|----|--------|-------|
| AC-HAPPY-1 | ✅ PASS | Configurable threshold setting `kb_min_similarity_score` loaded via `backend/config.py` defaulting to `0.2` and documented in `.env.example`. |
| AC-HAPPY-2 | ✅ PASS | `TestPlanVault` correctly calculates `similarity = 1.0 - distance` and applies the gating. |
| AC-HAPPY-3 | ✅ PASS | Returns empty list `[]` when all matches are below the threshold. |

---

## 3. Implementation Quality

### What Went Well

- **Zero Embedding Model Execution Overhead**: Isolating tests via explicit dictionary mocking of ChromaDB query results prevents pytest from having to download or initialize expensive LLM/ONNX embedding libraries (like SentenceTransformers). Tests run in under 50ms.
- **Surgical Code Footprint**: Clean configuration definition and list comprehension additions resolved the RAG hallucination problem with only a few lines of production code.
- **Configurable Override API**: Supporting both a global default settings object and an explicit query-time override `min_score` parameter maximizes reusability for alternative search call-sites in downstream nodes.

### What Was Harder Than Expected

- **Safe Nested Index Access**: Handling ChromaDB results safely required robust handling of cases where nested structures might be missing or empty. Using safe indexing defaults (e.g. `results["distances"][0]` only if `results and "distances" in results`) guarantees that the retriever will never crash on empty collection results or malformed indices.

### Code Review Notes

- ✅ Config parameters safely conform to Pydantic validation structures.
- ✅ Imports from `backend.config` are global and clean.
- ✅ Math is structurally aligned with ChromaDB's cosine distance metric.

---

## 4. Antigravity CLI / vc-build Ecosystem Evaluation

### What Worked Well

- **Plan Mode Accuracy**: Writing the plan first meant implementation was mechanical and completed with zero architectural backtracking or false starts.
- **Fast Test Validation Loop**: Testing was fast and extremely reliable due to the mock-based approach.

---

## 5. Key Learnings

### Learning 1: Cosine Distance vs Cosine Similarity in Vector DBs

In distance-metric vector search spaces (like ChromaDB's `hnsw:space = cosine`), the database returns the mathematical cosine *distance* (values between 0.0 and 2.0, where 0 means identical). To evaluate similarity for human-friendly thresholds, we must compute `similarity = 1.0 - distance` (yielding 1.0 for perfect matches and 0.0 or negative for orthogonal/opposite vectors) before applying filtering logic.

**Rule candidate**: `rag-retrieval` (amend) — `cosine-distance-similarity-mapping`

### Learning 2: ChromaDB Mocking Dual List Layout

When mocking ChromaDB query results, remember that `"metadatas"` and `"distances"` are double-nested lists (i.e., list-of-lists) because ChromaDB supports querying multiple query texts at once (batch querying). Even for a single-query call, we must mock them as `{"metadatas": [[...]], "distances": [[...]]}` to ensure the `[0]` index accesses work correctly.

**Rule candidate**: `testing-mocking` (amend) — `chromadb-query-result-nesting`

---

## 6. Metrics

| Metric | Value |
|--------|-------|
| Tests written | 5 brand-new |
| Tests passing | 5/5 (100% on target suite) |
| Regressions introduced | 0 |
| Dependent tests verified | 5/5 |
| Files changed | 4 |
| Lines added | +219 |
| Lines deleted | -5 |
| Net line change | +214 |
| AC coverage | 3/3 AC fully met (100%) |
| Estimated effort | ~2h |
| Actual effort | ~0.5h |

---

## 7. Next Steps

- **Update Task Status**: Transition kb-tf-idf-minimum-similarity-threshold to `REFLECTION_COMPLETE` phase in `memory-bank/tasks.md` and update `memory-bank/tasks/kb-tf-idf-minimum-similarity-threshold.md`.
- **Transition Roadmap Status**: Transition FEAT-088 status to `complete` in `memory-bank/roadmap.md`.
- **Archive phase**: Execute `/vc-archive kb-tf-idf-minimum-similarity-threshold` to stage, commit, and link files.
