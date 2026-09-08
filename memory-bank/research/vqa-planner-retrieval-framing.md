# Phase 0 Framing Brief — vqa-planner-retrieval

**Topic**: Better context retrieval for vQA planner (replacing/augmenting TF-IDF code RAG)
**Source**: Ad-hoc topic (no work file)
**Framing date**: 2026-07-17
**Framing agent**: bmb:spike-framing-agent (claude-sonnet-4-6)

---

## Research Objectives

Determine whether and how replacing or augmenting the current 4-layer TF-IDF/BM25 passive retrieval
stack with dense embeddings, dependency-aware retrieval, step-level pre-mapping, or agentic tool-call
retrieval can achieve reliable surfacing of the correct TypeScript helper modules and selectors for
every planner step — eliminating the silent-exclusion failure mode where lexical mismatch causes the
planner to hallucinate selectors instead of reusing verified ones.

A secondary objective is to identify the lowest-cost path that satisfies the AWS Bedrock / Docker /
no-GPU / Python constraint envelope, so any recommendation can ship within the existing infrastructure
without a replatform.

---

## Research Questions

1. For ~200K tokens of TypeScript helper code (bigram TF-IDF baseline), does switching to dense
   embeddings (voyage-code-2, OpenAI text-embedding-3-small, or a quantized CodeBERT variant) produce
   measurably higher recall@3 when the AC step text shares no lexical overlap with the target
   function names — and what is the per-query latency and cost at vQA's invocation rate?

2. Does a dependency-graph or import-graph overlay (e.g., parse `import` statements in the `.ts`
   helpers to build an adjacency map) allow "pull QO_helpers.ts plus its imports automatically"
   to run deterministically at zero LLM cost — and what maintenance burden does the graph add when
   helpers change?

3. Can a lightweight LLM classifier (Claude Haiku or a fine-tuned small model) reliably route each
   parsed AC step to its primary helper module at AC-parse time (before the browser loop), and does
   doing so at parse time eliminate the per-step retrieval latency tax?

4. Does applying the hybrid BM25 + dense reranking pattern (already used in `kb/loader.py` for
   markdown) to the TypeScript helper corpus (`playwright_rag.py`) close the recall gap without
   requiring a new embedding service — i.e., can existing ChromaDB + scikit-learn handle it?

5. What are the production failure modes and maintenance costs of each retrieval strategy when helper
   files change across sprints (stale index, stale graph, stale classifier routing) — and which
   strategy degrades most gracefully?

---

## Ambiguity Profile

| Dimension          | Level  | Key Question |
|--------------------|--------|--------------|
| Technical feasibility | HIGH | Can dense code embeddings (voyage-code-2 / CodeBERT) run within the Docker/ECS no-GPU envelope at per-step latency < 2s, given ~200K tokens of helpers that must be indexed and queried at every planner call? |
| Existing-solutions | HIGH | Which of the 6 candidate approaches (dense, dependency-graph, pre-mapping classifier, hybrid rerank, agentic tool-call, small-LLM router) have been validated in production code-retrieval pipelines at this helper-corpus scale, and what recall numbers are publicly reported? |
| Architecture       | HIGH | Which retrieval strategy — or combination — fits the passive-injection pattern already in `planner.py` without requiring a new LangGraph node or a per-step LLM call that would violate the ≤2-node-per-loop anti-pattern? |
| Requirements       | MEDIUM | Is "every relevant helper reliably surfaces" a recall@1 or recall@3 requirement, and is there a token-budget ceiling on injected context (prompt_budget.py already trims aggressively)? |
| Data/evaluation    | MEDIUM | What benchmark can be constructed from existing failed runs (golden-10 dataset, session JSONL) to measure retrieval recall improvement before any deployment? |
| Effort-estimation  | MEDIUM | What is the implementation delta between (a) drop-in replacement of TF-IDF with ChromaDB dense in `playwright_rag.py` vs. (b) a full pre-mapping classifier at AC-parse time that requires changes to `ac_parser.py` and `VQAState`? |

_Omitted (low ambiguity): Integration/codebase, Safety/compliance_

---

## Activated Lanes  (Spike Depth: deep)

Three dimensions at HIGH drives `deep` depth (≥3 HIGH → deep per Step 2 rules).

| Lane                   | Status   | Reason |
|------------------------|----------|--------|
| Academic / SOTA        | ACTIVATE | Technical feasibility: HIGH — code-embedding recall benchmarks and repo-level RAG surveys directly address whether dense retrieval closes the TF-IDF recall gap at this corpus scale |
| OSS / Production       | ACTIVATE | Existing-solutions: HIGH — production systems (LlamaIndex code RAG, ChromaDB, voyage-code-2, LangChain retrievers) have concrete embedding+reranking patterns at ~100K–500K token code corpora |
| Practitioner Discourse | ACTIVATE | (default-on) — blog posts and Discord/Reddit threads on code RAG pipelines will surface gotchas (index staleness, latency, cost) not in academic papers |
| Official Docs          | ACTIVATE | Existing-solutions: HIGH — voyage-code-2 (Voyage AI), ChromaDB, scikit-learn, LangChain retriever docs needed to confirm API compatibility with existing Python stack and no-GPU constraint |
| Internal / Codebase    | ACTIVATE | Architecture: HIGH — `backend/kb/playwright_rag.py`, `backend/kb/loader.py`, `backend/engine/planner.py`, `backend/engine/prompt_budget.py`, and `backend/engine/ac_parser.py` must be read to confirm integration points and token-budget constraints before any verdict |

---

## Deep Research Probes

| probe_id | research_question | ambiguity_dimension | insufficiency_rationale | expected_output_shape | recommended_run_mode |
|----------|-------------------|---------------------|-------------------------|-----------------------|----------------------|
| DRP-001  | For the specific failure mode "AC step text shares no lexical tokens with helper function names" (e.g., "Select 'Radio Commercial' from 'Ad Type' dropdown" → QO_helpers.ts), what is the empirical recall@3 improvement of voyage-code-2 or CodeXEmbed vs. TF-IDF bigram on a synthetic benchmark constructed from vQA's own helper corpus and golden-10 AC steps? | Technical feasibility | Normal OSS/Academic lanes will return benchmark numbers from different corpora (general code search, GitHub repos) — not from Angular/PrimeNG helper files queried with natural-language QA step text. The domain gap is large enough that generic recall figures may be misleading. A targeted probe constructing a mini-eval from actual vQA artifacts is required to make a defensible ADOPT/BORROW decision. | Recall@1/3/5 table comparing TF-IDF, BM25+TF-IDF hybrid, and ≥1 dense model on a 50-query synthetic eval built from golden-10 AC steps × helper corpus; latency measurement per query on CPU (Docker/ECS constraint) | human-assist |
| DRP-002  | Does parsing TypeScript import graphs from `playwright/utils/*.ts` to build a static dependency adjacency map provide reliable "pull QO_helpers.ts and all its transitive imports" at zero-LLM cost, and what is the false-positive (pulling irrelevant helpers) rate when a helper is imported by many others? | Architecture | Academic and OSS lanes cover dependency-aware retrieval in general (e.g., RepoGraph, CodeRAG), but none address the specific shape of the vQA helper graph (5 large files, high import fan-in from QO_helpers, TypeScript-specific re-export patterns). The internal codebase lane can read the files but cannot produce a quantified false-positive estimate without actually building the graph. This probe needs a focused traversal of the real import graph. | Import adjacency map of the 6 utils files with transitive closure per entry-point; estimated false-positive rate (irrelevant helpers pulled per correct helper hit); build/maintenance cost estimate | agent-run |

---

## MCP Availability

| Server        | Status      | Notes / Affected lane |
|---------------|-------------|----------------------|
| arxiv         | UNAVAILABLE (degraded) | No dedicated arxiv MCP server present — Academic/SOTA lane falls back to WebSearch (confirmed: arxiv papers surface via WebSearch query) |
| github-search | UNAVAILABLE (degraded) | No GitHub Search MCP — OSS/Production lane falls back to WebSearch + `gh` CLI for repo inspection |
| context7      | UNAVAILABLE | context7.com is a documentation website, not a connected MCP server in this session — Official Docs lane falls back to WebFetch against vendor documentation URLs |

All three MCP research servers are absent. All five activated lanes will operate on WebSearch / WebFetch / Bash fallbacks. This increases lane-agent effort but does not reduce coverage for this topic — the relevant signal (arxiv papers, GitHub repos, Voyage/ChromaDB docs) is reachable via fallback.

---

## Recommendation

**proceed** — The problem is well-scoped, the failure mode is concretely documented (lexical mismatch → silent exclusion → hallucinated selectors), the constraint envelope is tight but workable (Python, ChromaDB, no GPU, Bedrock), and three HIGH-ambiguity dimensions make a full deep spike warranted. DRP-001 (mini eval on real vQA artifacts) is the critical gate: its output will determine whether the ADOPT verdict goes to dense-only, hybrid, or pre-mapping classifier without relying on corpus-mismatched benchmarks from the literature.
