## Spike Card: OSS / Production
**Work slug**: vqa-planner-retrieval   |   **Status**: DEGRADED
**run_id**: 20260717-9a2c2120fe42
**framing_sha**: 9a2c2120fe42
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, official-docs, codebase
**MCP used**: FALLBACK (WebSearch/WebFetch)
**mcp_servers_available**: none
**fallback_used**: yes
**Sources consulted**: 18

### Findings

| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| [ChromaDB releases — chroma-core/chroma](https://github.com/chroma-core/chroma/releases) | repo | B | v1.5.9 (May 2026) active; ~2 releases/month; Rust-core rewrite delivers up to 4x CPU throughput gains; 20ms p50 warm query at 100K vectors | source_tool: WebFetch. Existing ChromaDB install in vQA is already on a well-maintained, CPU-capable stack; warm query latency is acceptable for the ~200K-token helper corpus |
| [ChromaDB production issues — tokio panic #4365 / compactor failure #1843](https://github.com/chroma-core/chroma/issues/4365) | issue | B | Post-1.0 Rust core introduces tokio-runtime-worker panics and HNSW/SQLite compactor desync failures not present in pre-1.0 | source_tool: WebSearch. Version pinning and index-health checks are production necessities; silent compactor desync is a TRAP candidate |
| [ChromaDB default embedding — all-MiniLM-L6-v2 ONNX on-demand download](https://github.com/chroma-core/chroma/issues/2910) | issue | B | Default ONNX embedding download fails in air-gapped/restricted Docker containers; model must be pre-baked or replaced with explicit embedding function | source_tool: WebSearch. ECS/Docker constraint means vQA must supply its own embedding function — cannot rely on ChromaDB default at startup |
| [bm25s — xhluca/bm25s](https://github.com/xhluca/bm25s) | repo | B | 1.7K stars, 54 releases (latest 0.3.9, May 2026), 0 open issues, 1M+ PyPI downloads; up to 500x faster than rank_bm25; NumPy/Numba only, no Java/PyTorch | source_tool: WebFetch. Drop-in upgrade from scikit-learn TF-IDF for lexical leg of hybrid retrieval; no new dependencies conflict with existing stack |
| [py-tree-sitter — tree-sitter/py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) | repo | B | 1.5K stars, 17 releases, latest v0.26.0 (June 2026), 6 open issues, pre-compiled wheels for all major platforms | source_tool: WebFetch. Well-maintained official binding; TypeScript grammar available via tree-sitter-typescript package on PyPI |
| [tree-sitter-typescript — tree-sitter/tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript) | repo | B | Official first-party TypeScript grammar maintained by the tree-sitter org; includes both TS and TSX dialects | source_tool: WebSearch. Covers vQA helper file format (TypeScript utils); no third-party grammar risk |
| [ASTChunk — yilinjz/astchunk](https://github.com/yilinjz/astchunk) | repo | C | 92 stars, backed by cAST paper (arXiv:2506.15655); depends on tree-sitter; TypeScript supported; language-agnostic chunking algorithm; 5.5pt gain on RepoEval with StarCoder2-7B | source_tool: WebSearch. Very low star count and new (2025); research-grade rather than production-hardened; TRAP candidate for dependency |
| [LlamaIndex CodeSplitter — run-llama/llama_index](https://github.com/run-llama/llama_index/issues/13521) | issue | B | Known production bug: CodeSplitter raises TypeError on init with tree_sitter_languages in certain versions (issues #13521, #11273, #17567 all open/recent); tree-sitter module import failures in Docker | source_tool: WebSearch. LlamaIndex CodeSplitter is a TRAP candidate — production bug rate is high; hand-rolling tree-sitter chunking avoids inheriting these regressions |
| [LlamaIndex graph-based code retrieval](https://markaicode.com/usecases/llamaindex-for-code-generation/) | post | C | PropertyGraphIndex reduces hallucinated imports by 68% vs naive chunk retrieval; requires additional graph node not compatible with vQA's passive-injection ≤2-node pattern | source_tool: WebSearch. Architecturally incompatible with vQA's planner pattern without a replatform; useful benchmark signal only |
| [jinaai/jina-embeddings-v2-base-code — Hugging Face](https://huggingface.co/jinaai/jina-embeddings-v2-base-code) | model page | A | 161M params, Apache 2.0, 8192-token context, 222K downloads/month, 30 languages including TypeScript; runs via sentence-transformers; no GPU requirement stated | source_tool: WebFetch. Best-fit local CPU embedding candidate: Apache 2.0 license, small model, high downloads, no API dependency |
| [Salesforce/SFR-Embedding-Code-400M_R (CodeXEmbed) — Hugging Face](https://huggingface.co/Salesforce/SFR-Embedding-Code-400M_R) | model page | A | 400M params, cc-by-nc-4.0, 8192-token context, CoIR NDCG@10=61.9 (beats voyage-code-2's 56.3); runs via sentence-transformers; requires trust_remote_code=True | source_tool: WebFetch. Highest benchmark score available locally, but cc-by-nc-4.0 prohibits commercial use — TRAP candidate for licensing in a production vQA SaaS |
| [voyage-code-2 — Voyage AI blog + HuggingFace page](https://blog.voyageai.com/2024/01/23/voyage-code-2-elevate-your-code-retrieval/) | vendor blog + model page | B | API-only; no local inference weights; 14.52% recall improvement on 11 code benchmarks; Python client available; AWS Marketplace listing exists for Bedrock integration | source_tool: WebSearch. API-only model adds external egress dependency inside Docker/ECS — TRAP candidate for vQA's air-gap/latency constraints; Bedrock integration possible via AWS Marketplace but adds cost and cold-start risk |
| [CodeXEmbed vs voyage-code-2 — arXiv:2411.12644 (COLM 2025)](https://arxiv.org/abs/2411.12644) | paper | A | CodeXEmbed-7B exceeds voyage-code-2 by >20% on CoIR; 400M variant CoIR=61.9 vs voyage-code-2 CoIR=56.3 | source_tool: WebSearch. Local open-weight models outperform voyage-code-2 on the relevant benchmark; cc-by-nc-4.0 licensing of 400M model is the blocking constraint |
| [sentence-transformers efficiency docs — sbert.net](https://sbert.net/docs/sentence_transformer/usage/efficiency.html) | official doc | A | MiniLM delivers 5–14K sentences/sec on CPU; all-mpnet-base-v2 achieves 100–150ms/query CPU; quantization yields 2x speedup (25.6ms → 12.3ms) with preserved accuracy | source_tool: WebSearch. Confirms CPU-only sentence-transformers is viable for vQA's per-step latency target (<2s); MiniLM-class models are fastest on CPU |
| [bm25s vs TF-IDF — StackOne hybrid retrieval comparison](https://www.stackone.com/blog/mcp-tool-search-bm25-tfidf-hybrid/) | engineering blog | B | BM25 consistently outperforms TF-IDF on longer documents; hybrid BM25+dense improves R@100 from 0.32 to 0.38 and MRR from baseline; named production deployment at StackOne | source_tool: WebSearch. Hybrid BM25+dense is the confirmed production pattern; bm25s is the obvious Python replacement for the current scikit-learn TF-IDF leg |
| [ChromaDB 1M+ downloads / Pinecone cost comparison — dev.to](https://dev.to/johalputt/hot-take-pinecone-20-is-too-expensive-use-chroma-10-for-2026-local-rag-pipelines-gcp) | practitioner blog | C | Chroma 1.0 p99 latency 112ms at 1M vectors; recommended as default starting point for teams building LLM retrieval; PyPI download signal strong | source_tool: WebSearch. Confirms ChromaDB production readiness at scales well above vQA's corpus; C grade (personal blog, no named org) |
| [all-MiniLM-L6-v2 embed latency — ChromaDB Docker guide](https://oneuptime.com/blog/post/2026-02-08-how-to-run-chromadb-in-docker-for-embeddings/view) | practitioner blog | C | all-MiniLM-L6-v2 embeds in ~20ms per batch; Chroma query ~20ms; full RAG cycle ~40ms at small corpus | source_tool: WebSearch. Latency numbers match the <2s target easily; C grade (blog, single source) |
| [LlamaIndex.TS archived — LlamaIndex developer docs](https://developers.llamaindex.ai/typescript/framework/) | official doc | A | LlamaIndex.TS (TypeScript port) was archived; TypeScript code-splitting via LlamaIndex requires the Python package, not a native TS runtime | source_tool: WebSearch. LlamaIndex Python CodeSplitter is the only active path; confirms no native TypeScript helper integration exists |

### TRAP Candidates

- **ChromaDB Rust-core compactor desync (v1.0+)**: HNSW index silently diverges from SQLite on compactor failure in >=1.0; default repair path misleading; index-health validation required in startup code. Source: GitHub issue #1843 (WebSearch).
- **ChromaDB default ONNX embedding download fails in Docker**: The all-MiniLM-L6-v2 ONNX model is fetched on first connect; fails in ECS/Docker with restricted egress. Must pre-bake or replace with explicit embedding function. Source: GitHub issue #2910 (WebSearch).
- **voyage-code-2 API-only, no local weights**: Requires outbound API call per embedding request — adds external egress dependency, per-token cost, and cold-start tail latency inside Docker/ECS. Not viable without explicit Bedrock/API integration budget. Source: HuggingFace model page + Voyage AI blog (WebSearch/WebFetch).
- **SFR-Embedding-Code-400M_R cc-by-nc-4.0 license**: Highest-benchmarked local code embedding model is restricted to non-commercial research use. Cannot ship in a production SaaS without licensing risk. Source: HuggingFace model page (WebFetch).
- **LlamaIndex CodeSplitter tree-sitter init failures**: Multiple open production bugs (init TypeError, module import failures in Docker) across recent LlamaIndex versions. Pulling in LlamaIndex to use CodeSplitter inherits a fragile tree-sitter dependency. Source: GitHub issues #13521, #11273, #17567 (WebSearch).
- **ASTChunk (yilinjz/astchunk) low adoption**: 92 stars, research-grade, no named production deployments. Depending on it introduces an unmaintained-library risk for the chunking layer. Source: GitHub (WebSearch).

### Open Questions

1. What is the actual per-query CPU latency of jina-embeddings-v2-base-code (161M params) on the ECS task instance type (CPU only, no AVX-512?) for a corpus of ~200K TypeScript tokens chunked at function level? No concrete benchmark found for this model+hardware combination.
2. Does the 400M-param SFR-Embedding-Code model exceed the ECS task's RAM ceiling at startup? (400M BF16 ≈ 800MB model weights + overhead.) No ECS memory footprint data found.
3. Is there an Apache-2.0-licensed local code embedding model that matches SFR-Embedding-Code performance? jina-embeddings-v2-base-code (Apache 2.0, 161M) is the next candidate, but its CoIR score relative to SFR-Embedding-Code-400M (61.9) is not confirmed — only MTEB general scores available.
4. Can bm25s persist its sparse index to disk and reload at container restart without re-tokenizing the full helper corpus? (Critical for ECS cold-start latency.) Not confirmed in this lane; requires a code verification test.
5. ChromaDB 1.5.x introduced sharding and bloom filters — does the new Rust storage layer change the persistence file format in a way that breaks an existing Chroma collection built with an older Python version?
6. What is the index rebuild time for ~200K TypeScript tokens using jina-embeddings-v2-base-code on CPU? Needed to evaluate whether rebuild-on-startup is acceptable vs. persisting the index between deployments.

---

### Libraries/Repos Evaluated

| Name | Stars | Last commit | Adoption signal | Maintained? |
|------|-------|-------------|-----------------|-------------|
| [chroma-core/chroma](https://github.com/chroma-core/chroma) | n/a (very high — top RAG DB) | May 2026 (v1.5.9) | PyPI top-10 ML package; named by LlamaIndex, LangChain as default vector store | yes |
| [xhluca/bm25s](https://github.com/xhluca/bm25s) | 1.7K | May 2026 (v0.3.9) | 1M+ PyPI downloads; EasyRAG production deployment; 54 releases | yes |
| [tree-sitter/py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) | 1.5K | June 2026 (v0.26.0) | Powers Neovim/Helix/Zed syntax highlighting; official binding | yes |
| [tree-sitter/tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript) | n/a | 2025/2026 (recent) | First-party official grammar; PyPI package available | yes |
| [jinaai/jina-embeddings-v2-base-code](https://huggingface.co/jinaai/jina-embeddings-v2-base-code) | n/a (HuggingFace) | n/a | 222K downloads/month; Apache 2.0; 30 languages | yes |
| [Salesforce/SFR-Embedding-Code-400M_R](https://huggingface.co/Salesforce/SFR-Embedding-Code-400M_R) | n/a (HuggingFace) | n/a | 13.9K downloads/month; cc-by-nc-4.0; research release | unclear |
| [voyage-ai/voyageai-python](https://github.com/voyage-ai/voyageai-python) | n/a | 2025 (active) | voyage-code-2 API only; Pinecone integration; AWS Marketplace listing | yes (API product) |
| [run-llama/llama_index (CodeSplitter)](https://github.com/run-llama/llama_index) | 40K+ | active | Widely used but CodeSplitter has active production bugs (issues #13521, #11273, #17567) | yes (framework maintained; CodeSplitter sub-component fragile) |
| [yilinjz/astchunk](https://github.com/yilinjz/astchunk) | 92 | 2025 (new) | Research-only; no named production users | unclear |
| [sentence-transformers/sentence-transformers](https://github.com/UKPLab/sentence-transformers) | 15K+ | active | Dominant CPU embedding inference library; used by ChromaDB, LangChain, LlamaIndex | yes |
