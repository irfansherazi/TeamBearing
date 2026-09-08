# Spike Card — Codebase Lane
## vqa-planner-retrieval

**framing_sha**: 9a2c2120fe42
**run_id**: 20260717-9a2c2120fe42
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, official-docs, codebase
**lane**: Internal/Codebase
**status**: COMPLETE
**MCP used**: n/a (local-only lane)
**mcp_servers_available**: none
**fallback_used**: no

---

## Summary

The codebase lane performed a full read of all five target modules plus supporting context files. The core finding is that **PlaywrightRAG is a deliberate simplification** — it targets the wrong corpus (vsuitePlatform tests, which may not be checked out), uses a low-threshold TF-IDF (0.08), and injects at most 3,000 chars (≤750 tokens) per step. Meanwhile, a production-grade hybrid BM25+TF-IDF+ChromaDB stack already exists in `loader.py` and `rag.py`, and SelectorRAG (FEAT-042) has already applied that stack to the selector registry. The primary migration path (dense ChromaDB embeddings for PlaywrightRAG) would reuse both the existing `HumanGuidanceVault` pattern and the `SelectorRAG` BM25+TF-IDF dual-index pattern — both of which are in production today. The helper corpus to be indexed lives locally at `playwright/utils/*.ts` (4,493 lines across 5 files), NOT in the external vsuitePlatform repo that PlaywrightRAG currently points to.

---

## Findings

| # | Finding | Grade | Source (file:line) | Effort |
|---|---------|-------|--------------------|--------|
| F1 | PlaywrightRAG targets `../vsuitePlatform/playwright` (parent repo, not this repo) via `_DEFAULT_PW_DIR`. The local `playwright/utils/` tree (4,493 lines, 5 key files) is NOT indexed. | B | `backend/kb/playwright_rag.py:61` | LOW |
| F2 | Chunking is blank-line/comment-boundary only (no AST or function-level granularity). Small files fall back to a 3,000-char whole-file chunk. Max chars per chunk: 1,500 (query truncation). | B | `backend/kb/playwright_rag.py:206-308, 415` | LOW |
| F3 | TF-IDF config: `ngram_range=(1,2)`, `max_features=8000`, threshold `0.08`. Returns `max_results=2` chunks. No BM25 layer — unlike `loader.py` which has BM25+TF-IDF hybrid at 0.6/0.4 weight. | B | `backend/kb/playwright_rag.py:352-357, 391` | LOW |
| F4 | Index is built at module import time (singleton, line 442). No rebuild hooks from KB scripts. `reload()` exists but is only called manually (no file-mtime watch like `loader.py`). | B | `backend/kb/playwright_rag.py:432-442` | LOW |
| F5 | PlaywrightRAG is injected into the prompt at `Tier.RAG` (priority 4 of 8) via the `playwright_context` slot, capped implicitly by total prompt budget of 8,000 tokens. No explicit per-section `max_chars` set for it in `_build_system_prompt_v2`. | B | `backend/engine/prompt_budget.py:67-74`, `backend/engine/planner.py:2487-2488` | LOW |
| F6 | ChromaDB is in production via `HumanGuidanceVault` at `storage/chromadb/` (persistent). Uses `embedding_functions.DefaultEmbeddingFunction()` which is ChromaDB's built-in `all-MiniLM-L6-v2` ONNX model. Distance threshold `0.7` (cosine distance, so similarity ≥ 0.3 to match). Collection: `human_guidance`. | B | `backend/kb/rag.py:138-145, 233` | LOW |
| F7 | ChromaDB `HumanGuidanceVault` runs on CPU ONNX (macOS CoreML bypass at lines 6-18 of `rag.py`). Confirms no-GPU compatibility. TestPlanVault is a separate collection at `memory/chroma_rag/test_plan_vault`. | B | `backend/kb/rag.py:1-18, 31-32` | LOW |
| F8 | SelectorRAG (FEAT-042) already applies BM25+TF-IDF dual-index + synonym expansion to `selector_registry.json` entries (373 entries). Index persisted as `.pkl` at `memory/selector_rag/`. Auto-rebuild on stale check at module load. Hard 2,000-char output cap via env `SELECTOR_RAG_MAX_CHARS`. | B | `backend/kb/selector_rag.py:1-38, 164-210` | LOW |
| F9 | Selector registry has 373 named entries (from file size/structure; first entries confirmed). Keyword matching algorithm: token overlap (`meaningful_words` set intersection), threshold ≥ 2 overlapping words. SelectorRAG replaces this with BM25+TF-IDF combined score (0.6/0.4 weight, same as `loader.py`). | B | `backend/kb/selector_registry.py:134-166, 208-210` | LOW |
| F10 | `selector_registry.json` is rebuilt via `make kb-refresh` → `scripts/extract_playwright_kb.py`. Source: `playwright/utils/OrderHelper.ts`, `NavHelper.ts`, `QO_helpers.ts`. Manual trigger, not automated on KB update. | B | `backend/kb/selector_registry.py:15-25`, `memory-bank/techContext.md:68-71` | LOW |
| F11 | Planner has 4-layer retrieval per step: (1) `kb.query_with_expansion()` (TF-IDF+BM25, gated by domain keyword), (2) `selector_rag.query()` (BM25+TF-IDF), (3) `playwright_rag.query()` (TF-IDF only), (4) `skill_library.query()`. All four inject into `SYSTEM_PROMPT_TEMPLATE` at the `<context>` block. | B | `backend/engine/planner.py:2384-2489, 1192` | LOW |
| F12 | Total per-step prompt size is logged at INFO level at `planner.py:2741-2746` with per-section char counts. KB+selectors+playwright_rag contribute to `Tier.RAG` (priority 4). AMBIENT and HISTORY tiers are dropped first when over 8,000-token budget. | B | `backend/engine/planner.py:2726-2746`, `backend/engine/prompt_budget.py:49-74` | LOW |
| F13 | `HumanGuidanceVault` queries are inserted at "Phase -1" in `loader.py.query()` — before TF-IDF Phase 0 and Phase 1. If ChromaDB returns a match, TF-IDF is skipped entirely. Distance threshold 0.7 (cosine distance). | B | `backend/kb/loader.py:412-429` | LOW |
| F14 | Local helper corpus (`playwright/utils/`): QO_helpers.ts (635 lines), NavHelper.ts (306), OrderHelper.ts (2,223), SearchHelper.ts (617), ViewHelper.ts (712) = 4,493 lines total. Functions have JSDoc headers. This is the correct retrieval target, not vsuitePlatform. | B | `playwright/utils/` (wc -l output) | MEDIUM |
| F15 | AC parser does NOT do workflow/module classification at parse time. Two LLM stages: BDD Normalizer → JSON Compiler. Output is `TestPlan` with fields `step_type` (FILL, SELECT_DROPDOWN, DATE_SELECT, etc.), `input_value`. No `target_helper_module` field exists in the schema. Adding pre-mapping would require a new `VQAState` field and schema change. | B | `backend/engine/ac_parser.py:1-100`, `backend/engine/state.py` (inferred) | HIGH |
| F16 | `_build_system_prompt` (non-budget version) does NOT use `PromptBudget`. `_build_system_prompt_v2` (budget-controlled) exists but callers switch between v1/v2 based on a feature flag. Per-section max_chars caps: KB articles 2,000 chars, failure KB 3,000 chars, recipe block 4,000 chars, diary 5 entries, action history 8 entries. | B | `backend/engine/planner.py:2262-2880, 2883-2900`, `backend/kb/loader.py:557-570` | LOW |
| F17 | `loader.py` has a synonym expansion map (`_SYNONYM_MAP`) with 35 domain-specific mappings. `selector_rag.py` replicates this map with 32 entries. PlaywrightRAG has NO synonym expansion — a direct cause of lexical mismatch failures. | B | `backend/kb/loader.py:584-628`, `backend/kb/selector_rag.py:73-106` | LOW |
| F18 | Guiding Principle "RAG-Based KB Retrieval" in `systemPatterns.md` describes TF-IDF over markdown. Does not mention dense embeddings for TypeScript helpers. `techContext.md` lists `scikit-learn (TF-IDF vectorizer for KB RAG)` as the canonical knowledge retrieval entry — no mention of ChromaDB for TypeScript helpers. | A | `memory-bank/systemPatterns.md:116-118`, `memory-bank/techContext.md:13` | — |
| F19 | `systemPatterns.md` documents a KB sync cadence requiring automated sync on every `main` merge and a `STALE_CONTEXT` warning if KB is > 48 hours out of sync with `main`. PlaywrightRAG has no such hook — pure manual reload only. | A | `memory-bank/systemPatterns.md:460-461` | MEDIUM |
| F20 | Import graph of local helpers: `playwright/utils/QO_helpers.ts` exports date/ISCI utilities; `OrderHelper.ts` is the largest (2,223 lines); `NavHelper.ts` wraps navigation; `SearchHelper.ts` and `ViewHelper.ts` cover search and view paradigms. The `CLAUDE.md` in `playwright/` confirms these are the primary utility layer. No transitive import analysis performed (would require TS parsing). | C | `playwright/CLAUDE.md`, `playwright/utils/` (ls output) | MEDIUM |

---

## TRAP Candidates

| # | Candidate | Risk | Why Flagged |
|---|-----------|------|-------------|
| T1 | **Dense embeddings for PlaywrightRAG** — ChromaDB `HumanGuidanceVault` uses `all-MiniLM-L6-v2` (general English). TypeScript function-level code retrieval queried with natural-language AC steps may produce low-quality embeddings since `all-MiniLM-L6-v2` was not trained on code. A code-specific model (voyage-code-2, CodeBERT) may be required for meaningful recall improvement. | MEDIUM | F6: existing ChromaDB instance uses general embedding function, not a code-aware model. Switching embedding function requires reindexing all existing `human_guidance` chunks (breaking change to existing collection unless new collection is created). |
| T2 | **PlaywrightRAG targeting vsuitePlatform** — The module defaults to `../vsuitePlatform/playwright` which is an EXTERNAL repo not present in this container. If `PLAYWRIGHT_TESTS_DIR` is not set, PlaywrightRAG silently initializes empty (line 94-98). Any improvement to PlaywrightRAG must retarget to the LOCAL `playwright/utils/` tree. | HIGH | F1: the current indexed corpus is wrong (or empty). Any benchmark comparing TF-IDF vs dense on this module is measuring retrieval from an empty or wrong index. |
| T3 | **Pre-mapping classifier at AC parse time** — Adding a `target_helper_module` field to the `TestPlan` Pydantic schema and `VQAState` requires changes across `ac_parser.py`, `schemas.py`, `state.py`, and all downstream consumers that read `test_plan`. Phase 2 synthesis must weigh this against the low-effort alternative (synonym expansion + BM25 addition to PlaywrightRAG). | HIGH | F15: no helper module routing exists; adding it is a cross-cutting schema change. |
| T4 | **PromptBudget drop behavior** — PlaywrightRAG context is at `Tier.RAG` (priority 4). On long steps with large failure diaries and many selector hits, the RAG tier is dropped BEFORE HISTORY (tier 5) but AFTER RULES (tier 3). A larger/denser retrieval result (e.g., 3K chars dense vs 1.5K TF-IDF) could be more aggressively trimmed. | LOW | F5, F12: 8,000-token ceiling with progressive drop; denser retrieval blocks may be lost when the prompt is at capacity. |

---

### Open Questions

1. What is the actual runtime status of `PLAYWRIGHT_TESTS_DIR`? Is it set in the Docker container environment or left at default (which would make PlaywrightRAG initialize empty in production)?
2. Is `_build_system_prompt_v2` (PromptBudget-controlled) or `_build_system_prompt_v1` the active code path in production? The feature flag gate was not confirmed in this read.
3. How many blueprint YAML files exist in `knowledge/blueprints/`? SelectorRAG indexes both selector entries AND blueprints — knowing the blueprint count would inform the combined index size.
4. What is the ChromaDB collection count in `human_guidance` (i.e., how many HITL-written workflows have been indexed)? This determines whether the existing ChromaDB instance has meaningful recall signal.
5. Does `OrderHelper.ts` export explicit JSDoc `@param`/`@returns` tags that could serve as chunk metadata for retrieval? Confirmed it has a top-level JSDoc block but specific function-level JSDoc density is unconfirmed.
6. Is the `skill_library` (`backend/memory/skill_library.py`) using a different embedding approach from TF-IDF? Its query is the fourth retrieval layer per step but was not fully read.

---

### Existing Patterns

| Pattern | Location (file:line) | Relevance |
|---------|----------------------|-----------|
| BM25 + TF-IDF dual-index, 0.6/0.4 combined score | `backend/kb/loader.py:349-483`, `backend/kb/selector_rag.py:164-250` | Direct reuse pattern for upgrading PlaywrightRAG from TF-IDF-only to hybrid retrieval |
| Synonym expansion map (35 domain entries) | `backend/kb/loader.py:584-628` | Should be applied to PlaywrightRAG query expansion — currently absent there |
| ChromaDB `HumanGuidanceVault` (persistent, `all-MiniLM-L6-v2`, cosine space) | `backend/kb/rag.py:122-272` | Template for a new `PlaywrightHelperVault` dense-embedding collection |
| SelectorRAG stale-check + background rebuild | `backend/kb/selector_rag.py:183-248`, `backend/engine/planner.py:231-248` | Same pattern needed for any PlaywrightRAG index with a persist+rebuild lifecycle |
| Per-step RAG result caching + cache clear on run start | `backend/engine/planner.py:187-218` | Any new retrieval layer should hook into `clear_rag_caches()` |
| PromptBudget `Tier.RAG` slot assignment | `backend/engine/prompt_budget.py:49-74` | New retrieval results must declare tier and slot for budget controller |
| File-mtime hot-reload (`loader.py`) | `backend/kb/loader.py:699-732` | Model for auto-rebuild when helper TypeScript files change |
| CoreML bypass for ONNX on macOS | `backend/kb/rag.py:1-18` | Must be preserved/inherited in any new ChromaDB collection initialization |
| KB sync cadence policy (48h stale warning, CI auto-rebuild) | `memory-bank/systemPatterns.md:460-461` | Any new index must comply with the same staleness governance |

---

### Compatibility Constraints

- **Python 3.12, no GPU**: `all-MiniLM-L6-v2` ONNX CPU confirmed working; any code-specific dense model must also run CPU-only (rules out GPU-requiring variants of CodeBERT without ONNX export).
- **ChromaDB persistent client at `storage/chromadb/`**: existing `human_guidance` collection uses cosine space. A new collection for TypeScript helpers can coexist but MUST use a separate `collection_name` to avoid data pollution. Cannot change embedding function of an existing collection without dropping and recreating it.
- **8,000-token prompt budget (default)**: PlaywrightRAG is at `Tier.RAG` (drop priority 4 of 8). Dense retrieval returning larger chunks will be dropped under budget pressure the same as TF-IDF results — a per-section `max_chars` cap must be set.
- **vsuitePlatform dependency**: `_DEFAULT_PW_DIR` resolves to a path OUTSIDE this repo (`../vsuitePlatform/playwright`). Any retrieval improvement must either set `PLAYWRIGHT_TESTS_DIR` to `playwright/` (local) or change the default path. This is a BREAKING config change if vsuitePlatform retrieval was ever intentional.
- **`rank_bm25` already installed** (imported in `loader.py` and `selector_rag.py`): BM25 upgrade to PlaywrightRAG requires no new dependency.
- **`chromadb` already installed** (imported in `rag.py`): dense upgrade requires no new dependency if `all-MiniLM-L6-v2` is used; a code-specific model (voyage-code-2) would require the `voyageai` pip package.
- **Schema stability**: `TestPlan` Pydantic model governs `ac_parser.py` output. Adding `target_helper_module` for pre-mapping classifier requires coordinated changes to `schemas.py`, `state.py`, and all downstream node consumers — HIGH change surface.
