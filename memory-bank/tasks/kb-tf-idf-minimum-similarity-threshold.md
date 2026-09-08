---
legacy_id: kb-tf-idf-minimum-similarity-threshold
---
# kb-tf-idf-minimum-similarity-threshold: KB TF-IDF Minimum Similarity Threshold

**Status**: COMPLETE
**Complexity**: Level 2
**Roadmap Link**: FEAT-088
**Branch**: feature/FEAT-088-kb-min-similarity-threshold
**Worktree**: N/A
**Pillar**: P4 — Knowledge Base / Domain Context
**Gap ID**: P4-A
**Estimated Effort**: ~2h
**Created**: 2026-06-03

---

## Description

The `TestPlanVault` (historical test plan RAG) has no minimum similarity threshold, returning near-random noise matches (scores as low as 0.04) when a vague or non-matching query is run. These are subsequently injected into the AC parser/enricher and downstream LLM steps as misleading context.

Fix: add a `min_score=0.2` (configurable via `KB_MIN_SIMILARITY_SCORE`) similarity threshold to the `TestPlanVault` retrieval path in `backend/kb/rag.py`; query results below this threshold are discarded. If no results meet the threshold, return an empty list.

---

## Acceptance Criteria

### AC-HAPPY-1: Configurable Minimum Similarity Threshold Added to Config
**Priority**: MUST

**Given** `Settings` in `backend/config.py`
**When** the configuration loads
**Then** it defines `kb_min_similarity_score` as a float defaulted to `0.2` (env var `KB_MIN_SIMILARITY_SCORE`).

**Verification**:
- Unit test or verification of configuration schema.

### AC-HAPPY-2: TestPlanVault Applies Minimum Similarity Score Gating
**Priority**: MUST

**Given** a query text passed to `TestPlanVault.query_plans()`
**When** the database returns matches and distances
**Then** the method filters matches, keeping only those whose similarity score (`1 - distance`) is greater than or equal to the minimum similarity score.

**Verification**:
- Unit test in `tests/test_feat_088_min_score.py`

### AC-HAPPY-3: Query Returns Empty List When All Matches Are Below Threshold
**Priority**: MUST

**Given** a query that yields only low-similarity matches below the threshold
**When** `TestPlanVault.query_plans()` is called
**Then** it returns an empty list `[]` instead of a partial, noisy list.

**Verification**:
- Unit test in `tests/test_feat_088_min_score.py`

---

## Clarifications Needed

_None — requirements are clear and mapped to FEAT-088._

---

## Implementation Roadmap

### 1. Update Environment Configuration (`backend/config.py` & `.env.example`)
- Open `backend/config.py` and define:
  ```python
  kb_min_similarity_score: float = Field(
      default=0.2,
      description=(
          "FEAT-088: Minimum similarity threshold for TF-IDF/RAG Knowledge Base retrieval. "
          "Matches scoring below this threshold are discarded. "
          "Env var: KB_MIN_SIMILARITY_SCORE."
      ),
  )
  ```
- Add `# Minimum similarity threshold for KB RAG retrieval (e.g. 0.2)` and `KB_MIN_SIMILARITY_SCORE=0.2` to `.env.example`.

### 2. Update TestPlanVault Query Path (`backend/kb/rag.py`)
- Import `settings` from `backend.config` into `backend/kb/rag.py`.
- Update `TestPlanVault.query_plans` signature:
  ```python
  def query_plans(self, query_text: str, n_results: int = 3, min_score: Optional[float] = None) -> List[MultiActorTestPlan]:
  ```
- Calculate `effective_min_score`:
  ```python
  effective_min_score = min_score if min_score is not None else settings.kb_min_similarity_score
  ```
- Retrieve both `metadatas` and `distances` from ChromaDB query results:
  ```python
  results = self.collection.query(
      query_texts=[query_text],
      n_results=n_results
  )
  ```
- Zip them together and filter:
  ```python
  metadatas = results["metadatas"][0] if (results and "metadatas" in results and results["metadatas"]) else []
  distances = results["distances"][0] if (results and "distances" in results and results["distances"]) else [0.0] * len(metadatas)

  plans = []
  for metadata, dist in zip(metadatas, distances):
      score = 1.0 - dist
      if score >= effective_min_score:
          plan_json = metadata.get("plan_json")
          if plan_json:
              try:
                  plans.append(MultiActorTestPlan.model_validate_json(plan_json))
              except Exception as e:
                  logger.error(f"Failed to deserialize plan from vault: {e}")
  ```

### 3. Create Unit Test Suite (`tests/test_feat_088_min_score.py`)
- Create `tests/test_feat_088_min_score.py` testing:
  - Default `effective_min_score` configuration loading.
  - Threshold filtering (matching vs. discarded based on simulated ChromaDB distance output).
  - High-distance (low similarity) returns empty list.

---

## Test Strategy

### Unit Tests (`tests/test_feat_088_min_score.py`)
- Mock ChromaDB PersistentClient and the corresponding collection so tests are fast and environment-independent.
- Test that querying with various mock distances (e.g., `0.1` -> score `0.9` vs. `0.95` -> score `0.05`) correctly includes/excludes the corresponding plans.
