# Deep Research Probe — DRP-001
**work_slug**: vqa-planner-retrieval  
**artifact_slug**: vqa-planner-retrieval  
**probe_id**: DRP-001  
**run_id**: 20260717-9a2c2120fe42  
**ambiguity_dimension**: Data/evaluation + Technical feasibility  
**recommended_run_mode**: human-assist  
**Status**: PENDING

---

## Background Context (read before submitting to Deep Research)

We are evaluating retrieval strategies for a QA automation agent called vQA. The agent runs a
per-step browser planner loop: for each AC step (e.g. "Select 'Radio Commercial' from the 'Ad Type'
dropdown"), it retrieves relevant TypeScript helper code and Playwright selectors from a corpus, then
sends the retrieved context + a screenshot + accessibility tree to Claude Sonnet to decide the next
browser action.

The current retrieval uses **TF-IDF cosine similarity** (scikit-learn, threshold=0.08, max 2 chunks).
The corpus is ~200K tokens of TypeScript helper files (QO_helpers.ts, OrderHelper.ts, NavHelper.ts,
SearchHelper.ts, ViewHelper.ts, FirmOptionsHelper.ts). The failure mode: TF-IDF silently excludes the
correct helper when AC step text doesn't lexically overlap with the helper code, causing the LLM to
hallucinate selectors instead of reusing verified ones.

We are considering:
1. Replacing TF-IDF with dense code embeddings (voyage-code-2, CodeXEmbed, text-embedding-3-small)
2. Hybrid BM25 + dense embedding with reranking
3. AC-parse-time workflow classification (classify the AC step to a module before the loop starts)
4. Agentic/tool-call retrieval (give the planner a search tool instead of passive injection)

**Key constraint**: Python backend, AWS Bedrock, no GPU, must run in Docker/ECS on CPU only.

---

## Research Question

**Build a mini recall evaluation framework** that compares TF-IDF vs. dense code embeddings
(voyage-code-2, CodeXEmbed, or text-embedding-3-small) vs. hybrid BM25+dense for the vQA code
retrieval problem specifically:

1. What does the academic and practitioner literature say about recall@k improvements from dense
   code embeddings over TF-IDF/BM25 for **TypeScript/JavaScript** corpora at **small-to-medium
   scale** (~200K tokens, not millions)?

2. What **CPU inference latency** benchmarks exist for voyage-code-2, CodeXEmbed, and
   text-embedding-3-small on embedding query text at runtime (not index build)? What is the
   p95 latency per query on CPU with no GPU?

3. Are there **published eval frameworks** (CodeSearchNet, CoSQA, SWE-bench retrieval tasks,
   or similar) that measure code retrieval recall for queries phrased as natural-language test
   steps (e.g. "click the Ad Type dropdown and select Radio Commercial") rather than code-to-code
   search? What recall@k numbers are reported?

4. What is the **practical minimum corpus size** below which dense embeddings stop helping
   (because TF-IDF already achieves near-perfect recall on a small, well-structured corpus)?
   Is 200K tokens of TypeScript helpers above or below that threshold?

5. For a system that must retrieve code at **every step of a browser automation loop** (potentially
   20-50 steps per test run), what are the latency and cost implications of:
   - A remote embedding API call (voyage-code-2 via API) per step vs.
   - A local CPU-only model (sentence-transformers, all-MiniLM-L6-v2) per step vs.
   - A pre-computed index with only cosine similarity at query time?

---

## Instructions for Deep Research

Copy the Research Question section above into Claude.ai Deep Research (or equivalent). Ask it to:
- Search academic papers (2022–2026), official model documentation, and practitioner benchmarks
- Prioritize sources that measure **code retrieval** (not general text retrieval) at **small corpus scale**
- Include any published numbers on CPU inference latency for the candidate embedding models
- Flag if any of the candidate approaches have known failure modes at small corpus scale

Paste the full Deep Research output into the pasteback file at:
`memory-bank/research/vqa-planner-retrieval-vqa-planner-retrieval-DRP-001-pasteback.md`

Set `Status: COMPLETE` in the pasteback file header when done.
