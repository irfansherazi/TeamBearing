---
version: next
status: planned
priority: medium
complexity: 3
linked_tasks: []
created: 2026-07-30
---

# 2026 Agentic-Testing SOTA Adoption

Umbrella research feature tracking eight candidate capabilities identified in a July 2026 competitive/SOTA review of agentic testing tools (Playwright Test Agents v1.56, mabl × Rovo, Anthropic Skill Creator, testRigor, arXiv 2607.01980, Keysight/Shiplight self-healing consensus). Each bullet is a scoped candidate that will be split into its own feature and task when planned; this file exists to keep the batch traceable and prevent it from getting lost between quarterly planning cycles.

## Candidates

### High leverage, low friction
1. **~~Critic-pass LLM step (Stage 2 → execution)~~** — **PROMOTED 2026-07-30** to its own feature: [`critic-pass-llm-evaluator`](./critic-pass-llm-evaluator.md). Insert a small Haiku pass that re-reads the AC + compiled TestPlan and flags mismatches. Mirrors Playwright Healer / Anthropic Skill Creator test-measure-refine loop.
2. **Accessibility-tree grounding for `target_component`** — Capture ARIA role + accessible name alongside PrimeNG selector. Executor prefers a11y tree, falls back to selector. Reduces flakiness from DOM churn and aligns with the abstraction MCP-based agents consume. Ref: Playwright Test Agents v1.56 (Jan–Jul 2026 expansion).
3. **Episodic RAG over past run outcomes** — Persist step outcomes + selector matches to a vector store; retrieve top-k similar prior steps into the Stage 1 prompt alongside `<playwright_context>`. Extension of the existing selector RAG. Ref: agentic-RAG episodic/semantic memory patterns (Medium/Rane 2026).

### Medium leverage
4. **Domain plugin registry** — Replace `ac_enricher.py`'s hardcoded 9-domain map with a `knowledge/domains/*.md` folder with frontmatter, discoverable at runtime. Lets non-engineers extend the AI's app-model. Ref: mabl "Agent Instructions," testRigor plain-English rules.
5. **Bidirectional Jira write-back** — Post TestPlan preview as a Jira comment; post pass/fail + evidence link on completion. Table-stakes for PM adoption. Ref: mabl × Atlassian Rovo (Apr 2026). Today vQA is read-only from Jira.
6. **Public benchmark on PURE / open AC dataset** — Run vQA's parser on the PURE dataset used in arXiv 2607.01980 (94.3% semantic coverage, 4.61/5 correctness baseline) and publish coverage/correctness numbers. Turns internal drift regression into an external quality claim.

### Speculative / longer arc
7. **Persona agents as first-class citizens** — Extend `PERSONA_SWITCH` to persona-conditioned exploration (hesitation patterns, error-prone paths). Ref: userpilot 2026 pattern.
8. **Self-healing recovery router** — Dedicated healer node between executor and evaluator: retries with a11y-tree fallback, LLM re-plans, or asks the operator. Formalizes recovery logic currently scattered across `recovery_router.py`. Ref: 2026 self-healing default consensus (Keysight, Shiplight) — 75–90% recovery from layout restructures.

## Gap analysis (source)

- **3.1** — a11y-tree grounding (candidate 2)
- **3.2** — self-healing execution (candidate 8)
- **3.3** — episodic RAG over past runs (candidate 3)
- **3.4** — bidirectional Jira integration (candidate 5)
- **3.5** — verifier/critic loops (candidate 1)
- **3.6** — domain extensibility (candidate 4)
- **3.7** — empirical AC-parsing quality baseline (candidate 6)

**Complexity rationale**: Level 3 as an *umbrella* — the feature itself is a tracking bucket, not a single implementation. When individual candidates are extracted into their own features, they will re-evaluate (candidates 1–4, 6 likely Level 2–3; candidates 7–8 likely Level 4). This file should be closed once all candidates are either promoted to their own features or explicitly dropped.
