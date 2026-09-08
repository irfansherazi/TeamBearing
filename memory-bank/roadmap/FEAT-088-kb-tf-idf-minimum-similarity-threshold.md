---
legacy_id: FEAT-088
version: v1.0.0-prod-readiness
linked_tasks: [kb-tf-idf-minimum-similarity-threshold, kb-tf-idf-minimum-similarity-threshold]
status: complete
---

### FEAT-088: KB TF-IDF Minimum Similarity Threshold
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: high
- **Complexity**: Level 2
- **Pillar**: P4 — Knowledge Base / Domain Context
- **Gap ID**: P4-A
- **Estimated Effort**: ~2h
- **Description**: The TF-IDF KB has no minimum similarity threshold, returning near-random noise matches (scores as low as 0.04) that are injected into the AC parser as guidance. Fix: add a `min_score=0.2` threshold filter to the KB retrieval path; results below the threshold are discarded.
- **Acceptance Criteria**:
  - AC-1: `backend/kb/rag.py` applies a `min_score` filter defaulting to `0.2`.
  - AC-2: `min_score` is configurable via `config.py` (`KB_MIN_SIMILARITY_SCORE`).
  - AC-3: When no results meet the threshold, the retriever returns an empty list (not a noisy partial list).
  - AC-4: Unit test: verify that a query with no good matches returns an empty list instead of low-score noise.
- **Key Files**:
  - `backend/kb/rag.py`
  - `backend/config.py` — `KB_MIN_SIMILARITY_SCORE`
- **Linked Tasks**: [kb-tf-idf-minimum-similarity-threshold](tasks/kb-tf-idf-minimum-similarity-threshold.md)
- **Branch**: feature/FEAT-088-kb-min-similarity-threshold
- **Created**: 2026-06-03
