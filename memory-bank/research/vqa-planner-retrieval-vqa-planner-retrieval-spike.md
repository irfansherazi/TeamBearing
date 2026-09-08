# Spike Synthesis — vqa-planner-retrieval

**work_slug**: vqa-planner-retrieval
**run_id**: 20260717-9a2c2120fe42
**framing_sha**: 9a2c2120fe42
**approved_depth**: deep
**source_tool**: spike-synthesis-agent
**status**: approved
**lanes_synthesized**: academic, oss-production, practitioner-discourse, official-docs, codebase, DRP-002
**drp_001_status**: PENDING (human pasteback not yet received — DRP-001 spike card not produced; synthesis proceeds without it)

---

## Verdict Table

| # | Candidate Approach | Verdict | Confidence | Evidence Source(s) |
|---|-------------------|---------|------------|-------------------|
| V-01 | **Root cause fix**: retarget PlaywrightRAG from `../vsuitePlatform/playwright` to local `playwright/` | **ADOPT** | HIGH | Codebase F1: `_DEFAULT_PW_DIR` pointed at non-existent path in Docker → 0 chunks. Fixed. 1,712 chunks now indexed. |
| V-02 | **BM25+TF-IDF hybrid scoring** (0.6/0.4 weight, matching loader.py + selector_rag.py) | **ADOPT** | HIGH | Already shipped. OSS lane: bm25s is production-grade (0 open issues, 54 releases, 1M+ PyPI downloads). Academic: BM25 alone = 29.79 NDCG@10 vs dense 56.26 (CoIR ACL 2025) — hybrid closes part of the gap. Codebase F3, F8: pattern proven in two other RAG layers. |
| V-03 | **TF-IDF tokenizer fix** (preserve underscores via custom `token_pattern`) | **ADOPT** | HIGH | Already shipped. Docs F-14: scikit-learn default `\b\w\w+\b` strips underscores, splitting `QO_helpers` into `QO` + `helpers`. A-grade evidence (official scikit-learn docs). Zero-cost fix. |
| V-04 | **Synonym expansion in playwright_rag.query()** | **ADOPT** | HIGH | Already shipped. Codebase F17: loader.py had 35-entry synonym map, selector_rag.py had 32 entries, PlaywrightRAG had zero. Closes the "QO" → QO_helpers lexical gap. Proven by smoke test. |
| V-05 | **Index staleness detection** (`is_stale()` + `reload()` + background watcher) | **ADOPT** | HIGH | Already shipped. Practitioner lane: 4 sources confirm index staleness is "the silent killer of RAG in production" — stale embeddings score identically to fresh ones. Zero-cost operational safety net. Wired into FastAPI lifespan (60s check interval). |
| V-06 | **Static co-injection rule** (OrderHelper → always co-inject QO_helpers) | **ADOPT** | HIGH | Already shipped. DRP-002: import graph has exactly 1 inter-helper edge. False-positive rate = 0%. Solves the dependency-awareness problem without a graph parser. |
| V-07 | **jina-embeddings-v2-base-code** (dense code embeddings, local CPU) | **BORROW** | MEDIUM | OSS lane: Apache 2.0, 161M params, 8192-token context, 222K downloads/month, sentence-transformers compatible. CPU latency UNMEASURED — this is the critical unknown. ChromaDB already in production (HumanGuidanceVault). Requires MVE-1 before ADOPT promotion. |
| V-08 | **Titan Text Embeddings V2** (dense embeddings via Bedrock) | **BORROW** | MEDIUM | Docs F-06: 8192-token context, Active lifecycle, configurable dimensions (256/512/1024). No egress risk — already on Bedrock. No code-embedding validation yet. Requires MVE-2 before ADOPT promotion. |
| V-09 | **voyage-code-2** (dense code embeddings, API-only) | **TRAP** | HIGH | API-only, no local weights. Egress/cost risk in Docker/ECS. Practitioner: "always best, but also has high latency" — 20–50 API calls/session compounds. OSS lane confirmed no offline mode. Academic: outperformed by local CodeXEmbed anyway. |
| V-10 | **SFR-Embedding-Code-400M (CodeXEmbed)** | **TRAP** | HIGH | cc-by-nc-4.0 — non-commercial only. Best CoIR score (61.9) but license blocks production SaaS use. OSS lane confirmed. |
| V-11 | **ChromaDB default model (all-MiniLM-L6-v2)** | **TRAP** | HIGH | Docs F-02, F-03: 256-token hard truncation. Code Search data = 0.1% of training corpus. Not positioned for code-semantic retrieval. TypeScript helper functions routinely exceed 256 tokens. A-grade evidence (official HuggingFace model card + ChromaDB source). |
| V-12 | **Graph-overlay retrieval** (dynamic TypeScript AST import graph) | **DEFER** | HIGH | DRP-002: import graph has exactly 1 edge (OrderHelper → QO_helpers). Already handled by static co-injection rule V-06. False-positive rate = 0% but marginal benefit also = 0%. Maintenance cost of tree-sitter parser > benefit for 1-edge graph. Docs F-11/F-12: tree-sitter version skew risk (v0.26.0 vs v0.23.2). |
| V-13 | **Agentic per-step retrieval** (give planner a search tool) | **TRAP** | HIGH | Practitioner: 7× latency increase (4.8s → 32.4s) measured in production (Supermemory blog). Violates ≤2-node-per-loop anti-pattern. Academic (SoK Agentic RAG): "retrieval misalignment" and "cascading tool-execution vulnerabilities" as systemic risks. |
| V-14 | **AC-parse-time step classifier** (route each AC step to a helper module) | **DEFER** | MEDIUM | Requires labeled AC-step → module training data that doesn't exist beyond golden-10. Schema migration across LangGraph state machine is HIGH effort (Codebase F15: no `target_helper_module` field). Academic: 93% routing accuracy achievable but on different task framing. |
| V-15 | **Full-context injection** (dump all helpers into every prompt) | **TRAP** | HIGH | Practitioner: $2.25/call cost at 150K tokens, 30–90s latency. Microsoft Research 2025: attention degrades at 100K+ tokens. 4,767 lines of helpers ≈ 6K+ tokens per call. Budget ceiling is 8K tokens total (prompt_budget.py). |
| V-16 | **BM25 q-logarithm IDF enhancement** | **DEFER** | LOW | Academic: +89% NDCG on Go corpus (arXiv 2605.18561). Not validated on TypeScript. Already have hybrid BM25+TF-IDF shipped. Worth evaluating after current fixes are validated. Low-effort drop-in but uncertain benefit. |

---

## Minimum Viable Experiments

### MVE-1: jina-embeddings-v2-base-code CPU Latency Benchmark

**Goal**: Determine if jina-embeddings-v2-base-code is viable for per-step retrieval on ECS-class hardware (CPU-only, no AVX-512 guarantee).

**Protocol**:
1. Install `sentence-transformers` + `jinaai/jina-embeddings-v2-base-code` (Apache 2.0, 161M params)
2. Index the `playwright/utils/*.ts` corpus at function-level chunks (~68 functions, 4,767 lines)
3. Run the Golden-10 AC steps as queries (10 AC steps × 2 retrieval calls each = 20 queries)
4. Measure: p50, p95, p99 latency per query on a `t3.large` or equivalent (2 vCPU, 8 GB RAM)
5. Measure: Recall@2 against the currently-shipped hybrid BM25+TF-IDF baseline

**Promotion criteria**: p95 < 500ms AND recall@2 improvement > 15% over hybrid baseline → promote V-07 to **ADOPT**.

**Demotion criteria**: p95 > 1,000ms OR recall improvement < 5% → keep as **BORROW** (use only for re-ranking, not primary retrieval).

### MVE-2: Titan Text Embeddings V2 Code Retrieval Validation

**Goal**: Determine if Titan Text Embeddings V2 (already on Bedrock, zero egress risk) produces meaningful code-semantic embeddings for TypeScript helper retrieval.

**Protocol**:
1. Embed the `playwright/utils/*.ts` function-level chunks via `amazon.titan-embed-text-v2:0` (Bedrock InvokeModel)
2. Store in a new ChromaDB collection with a custom Bedrock embedding function
3. Run the Golden-10 AC step queries
4. Measure: Recall@2 against the hybrid BM25+TF-IDF baseline
5. Measure: per-query Bedrock API latency (RPM throttle risk — check Service Quotas first)

**Promotion criteria**: Recall@2 improvement > 10% over hybrid baseline AND per-query latency < 300ms → promote V-08 to **ADOPT**.

**Demotion criteria**: Recall@2 ≤ hybrid baseline → **TRAP** (not trained on code, general-purpose text embeddings insufficient).

---

## Decision Register

| # | Decision | Rationale | Evidence Source | Date |
|---|----------|-----------|----------------|------|
| D-01 | **ADOPT**: Fix PlaywrightRAG corpus path to local `playwright/` | Root cause of 0 chunks indexed — wrong path (`../vsuitePlatform/playwright`) doesn't exist in Docker | Codebase F1 | 2026-07-17 |
| D-02 | **ADOPT**: Add BM25 hybrid scoring to PlaywrightRAG | Proven pattern in 2 other RAG layers (loader.py, selector_rag.py). BM25 catches lexical hits TF-IDF weights poorly. bm25s is production-grade. | Codebase F3/F8, OSS bm25s | 2026-07-17 |
| D-03 | **ADOPT**: Fix TF-IDF token_pattern to preserve underscores | scikit-learn default regex splits `QO_helpers` → `QO` + `helpers`, breaking identifier matching | Docs F-14 (A-grade, official docs) | 2026-07-17 |
| D-04 | **ADOPT**: Add synonym expansion map to PlaywrightRAG | Closes QO → QO_helpers gap. Same pattern as loader.py (35 entries) and selector_rag.py (32 entries). | Codebase F17 | 2026-07-17 |
| D-05 | **ADOPT**: Wire is_stale() + reload() into FastAPI lifespan | 4 practitioner sources confirm index staleness is silent and undetectable. Zero-cost safety net. | Practitioner lane (HackerNoon, ranjankumar.in, ilovedevops) | 2026-07-17 |
| D-06 | **ADOPT**: Static co-injection of QO_helpers when OrderHelper matches | DRP-002 proved import graph has 1 edge. Static rule = deterministic, zero-maintenance. | DRP-002 spike card | 2026-07-17 |

---

## Findings by Angle

### Academic / SOTA
BM25 alone scores 29.79 NDCG@10 on CoIR vs 56.26 for the best dense model (voyage-code-2) — a +26.5-point gap (ACL 2025, A-grade). The gap is largest on queries with no lexical overlap to code tokens, exactly vQA's failure mode. CodeXEmbed-400M achieves 61.9 NDCG@10 (beating voyage-code-2) but is cc-by-nc-4.0. Hybrid BM25+dense retrieval shows up to 580% recall improvement over dense-only in domain-general studies. Lightweight TF-IDF+SVM classifiers achieve 93% routing accuracy for query complexity — but routing to helper *modules* (not complexity tiers) is an untested analogy.

### OSS / Production
jina-embeddings-v2-base-code (Apache 2.0, 161M params, 8192-token context, 222K downloads/month) is the best-fit local CPU embedding candidate. bm25s (1.7K stars, 0 open issues, 54 releases) is a drop-in BM25 upgrade. ChromaDB v1.5.9 is actively maintained with 20ms p50 warm query latency. Key TRAPs: voyage-code-2 is API-only, SFR-Embedding-Code is cc-by-nc, LlamaIndex CodeSplitter has active production bugs (3 open issues).

### Practitioner Discourse
Strong consensus: (1) Dense-only retrieval silently fails on exact identifiers — hybrid is mandatory. (2) Agentic per-step retrieval multiplies latency 7× — passive injection is architecturally superior. (3) Index staleness is "the silent killer" — file-hash-triggered rebuild is required. (4) Full-context injection at 200K tokens costs $2.25/call and degrades attention. (5) Structured/graph retrieval increasingly preferred over embeddings for code in 2025–2026.

### Official Docs
ChromaDB default model (all-MiniLM-L6-v2) has 256-token hard truncation and 0.1% code training data — TRAP for code retrieval (A-grade). Titan Text Embeddings V2 has 8192-token context and Active lifecycle — BORROW candidate (A-grade). scikit-learn TF-IDF default token_pattern strips underscores — confirmed root cause of QO_helpers tokenization bug (A-grade). tree-sitter has version skew between core (v0.26.0) and TypeScript grammar (v0.23.2) — compatibility risk.

### Codebase (Internal)
PlaywrightRAG was a deliberate simplification that pointed at the wrong corpus. A production-grade hybrid BM25+TF-IDF+ChromaDB stack already exists in `loader.py` and `rag.py`. SelectorRAG (FEAT-042) had already applied that stack to the selector registry. The primary migration path (dense ChromaDB embeddings for PlaywrightRAG) would reuse both the existing `HumanGuidanceVault` pattern and the `SelectorRAG` BM25+TF-IDF dual-index pattern. AC parser has no module-routing field — adding one requires HIGH-effort schema changes.

### DRP-002 (TypeScript Import Graph)
The import graph has exactly 1 inter-helper edge (OrderHelper → QO_helpers). All other helpers are fully isolated. Graph-overlay retrieval adds meaningful value for only 1 of 6 files. A static co-injection rule (already shipped) handles this deterministically at zero maintenance cost. Dynamic graph parsing is over-engineered for this corpus topology.

### DRP-001 (Dense Embedding Recall Benchmark)
**NOT YET AVAILABLE** — pasteback status is PENDING. The mini-eval comparing TF-IDF vs BM25+TF-IDF vs dense retrieval on vQA's own Golden-10 AC steps has not been received. MVE-1 and MVE-2 are the replacement path for this data.

---

## Knowns / Unknowns

### Knowns
- **Root cause fixed**: PlaywrightRAG path corrected from `../vsuitePlatform/playwright` (doesn't exist in Docker) to local `playwright/` — now indexes 1,712 chunks
- **BM25 hybrid shipped**: 0.6 TF-IDF + 0.4 BM25 scoring matches the proven pattern in loader.py and selector_rag.py
- **Graph overlay not needed**: Import graph has exactly 1 edge; static co-injection rule handles it
- **Index staleness watcher shipped**: is_stale() + reload() wired into FastAPI lifespan at 60s intervals
- **Synonym expansion shipped**: 10-entry `_CODE_SYNONYM_MAP` closes QO/navigate/search lexical gaps
- **TF-IDF tokenizer fixed**: Custom `token_pattern` preserves underscores for `QO_helpers`, `NavHelper`, etc.
- **Full-context injection is infeasible**: $2.25/call, attention degrades at 100K+ tokens, budget ceiling is 8K tokens
- **Agentic retrieval is infeasible**: 7× latency, violates ≤2-node anti-pattern, introduces cascading failure risks
- **all-MiniLM-L6-v2 is unsuitable for code**: 256-token truncation, 0.1% code training data
- **voyage-code-2 is unsuitable for Docker**: API-only, egress risk, high latency
- **SFR-Embedding-Code is unsuitable for production**: cc-by-nc-4.0 license

### Unknowns
- **jina-embeddings-v2-base-code CPU latency**: No benchmark exists for this model on ECS-class CPU (no AVX-512). 450ms/query baseline for BERT-class models (sbert.net) may be acceptable or may crowd out the 2s per-step budget. → **MVE-1**
- **Titan Text Embeddings V2 code retrieval quality**: Active on Bedrock with 8192-token context, but no code-specific embedding validation exists. General-purpose text embedding may not capture TypeScript semantic relationships. → **MVE-2**
- **ChromaDB cold-start latency on ECS**: ~1 minute first-retrieval latency reported (LlamaIndex #15201). No pre-warm strategy confirmed for containerized deployments.
- **Hybrid BM25+dense recall improvement on vQA's specific corpus**: The 69% error reduction from hybrid retrieval is from general text RAG, not code RAG at ~200K tokens with function-name lexical mismatch. DRP-001 was designed to answer this but is still PENDING.
