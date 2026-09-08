## Spike Card: Academic / SOTA
**Work slug**: jira-to-playwright-prompt-quality   |   **Status**: DEGRADED
**run_id**: 20260715-c5e7c39abca4
**framing_sha**: c5e7c39abca4
**approved_depth**: deep
**approved_lanes**: academic, oss-production, practitioner-discourse, docs, codebase
**MCP used**: FALLBACK (WebSearch/WebFetch)
**mcp_servers_available**: none
**fallback_used**: yes
**Sources consulted**: 14

> Coverage is reduced relative to a full MCP/arXiv search. All arXiv papers are preprints (Grade B)
> unless confirmed peer-reviewed publication is cited. MDPI review (2025) attempted but returned 403;
> ACM EASE 2025 paper returned 403. Those two sources are graded C (unverified fetch) or excluded.
> See Open Questions for gaps.

---

### Findings

| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| [Acceptance Test Generation with LLMs: Industrial Case Study (AutoUAT)](https://arxiv.org/abs/2504.07244) — Moha et al., arXiv 2025 | paper (preprint, industry study) | B | Two-step pipeline (Gherkin scenario generation → Cypress script) using GPT-4 Turbo achieves 95% helpfulness on scenario generation and 92% on script generation; 60% usable as-is, 8% minor fixes, 24% requiring regeneration with additional inputs, 8% discarded. Input: user stories + HTML page context. | Directly validates vQA's two-stage AC→test pipeline design. The 24% "regeneration needed" rate maps to the quality gap vQA is experiencing. HTML context as supplementary input is a concrete lever. source_tool: WebFetch |
| [BDD Scenario Generation with LLMs (GPT-4, Claude 3, Gemini)](https://arxiv.org/abs/2603.04729) — arXiv 2026 | paper (preprint) | B | Claude 3 scores highest in human/LLM evaluation of BDD scenarios. Chain-of-thought is most effective for Claude; few-shot for Gemini; zero-shot for GPT-4. Detailed requirement descriptions yield high-quality scenarios; user stories alone yield low quality. Temperature=0 + top_p=1.0 is optimal. LLM evaluators (DeepSeek) correlate better with human judgment than text/semantic similarity metrics. | Input quality of AC text is a primary quality driver — vQA's Jira AC varies widely in detail level, which may explain unreliable output more than prompt technique. CoT is the right prompting default for Claude. source_tool: WebFetch |
| [Large-Scale Independent Study of LLMs for Test Case Generation](https://arxiv.org/abs/2407.00225) — arXiv 2024 | paper (preprint) | B | 216,300 test cases across GPT-3.5, GPT-4, Mistral 7B, Mixtral 8x7B. Reasoning-based prompting (GToT) significantly enhances reliability and compilability. Compilation failure rates reach 86% with weaker approaches. Hallucination is a persistent issue. Hybrid LLM + automated validation + search-based refinement recommended for production. | 86% compilation failure rate with naive approaches underscores that prompt technique choice is critical. Hybrid validation loops (generate → validate → retry) are empirically necessary for production quality. source_tool: WebFetch |
| [Understanding Chain-of-Thought Effectiveness in Code Generation](https://arxiv.org/abs/2512.09679) — arXiv 2024 | paper (preprint) | B | Externally-guided CoT outperforms direct generation by 5–12% (Pass@1). Naive zero-shot CoT can degrade performance. High-quality structured CoT from capable models outperforms lightweight alternatives with same template. CoT strategy should depend on model capacity, task complexity, language. | For vQA: CoT is beneficial but must be structured/guided, not naive. Claude 3.5 Sonnet has sufficient capacity to benefit from CoT. Placing reasoning before answer field is critical (Tam et al. finding). source_tool: WebFetch |
| [Generating Structured Outputs from LLMs: Benchmark and Studies (JSONSchemaBench)](https://arxiv.org/abs/2501.10868) — arXiv 2025 | paper (preprint) | B | Benchmarks 6 constrained decoding frameworks (Guidance, Outlines, Llamacpp, XGrammar, OpenAI, Gemini) on 10K real-world JSON schemas. Key finding: "poor understanding of effectiveness in practice" — constrained decoding adoption is wide but gaps in coverage and quality remain; provides actionable insights. | vQA's JSON Compiler must contend with schema complexity; constrained decoding (tool-use / structured output API) is more reliable than prompt-only JSON enforcement, but framework choice matters. source_tool: WebFetch |
| [Let Me Speak Freely? Format Restrictions Impact on LLM Performance](https://arxiv.org/abs/2408.02442) — Tam et al., arXiv 2024 | paper (preprint) | B | Strict format constraints (JSON, XML) cause "significant decline in LLM reasoning abilities." Stricter constraints lead to greater performance degradation. Answer field after reasoning field preserves performance; reversing order degrades it. | TRAP CANDIDATE: Forcing JSON output in a single prompt step may degrade the LLM's reasoning quality in vQA's BDD Normalizer stage. Two-stage design (reason first, format second) is empirically justified — validates vQA's pipeline separation. source_tool: WebFetch |
| [Meaning Typed Prompting (MTP) / Semantix framework](https://arxiv.org/abs/2410.18146) — arXiv 2024 | paper (preprint) | B | Integrates type definitions and semantic abstractions into prompts for structured output generation; outperforms existing frameworks in "accuracy, reliability, consistency, and token efficiency" on multiple benchmarks. Reduces reliance on complex JSON schemas; uses expressive type definitions instead. | Practical alternative to raw JSON schema prompting; relevant to vQA's JSON Compiler prompt design if schema complexity is a reliability bottleneck. source_tool: WebFetch |
| [CoverUp: Coverage-Guided LLM-Based Test Generation](https://arxiv.org/abs/2403.16218) — Pizzorno & Berger, arXiv 2024 | paper (preprint) | B | Iterative coverage-feedback loop drives LLM test generation; achieves 80% line+branch coverage (vs 47% for CodaMosa), 89% vs 77% vs MuTAP. Effectiveness stems from combined feedback loop + context + LLM, not LLM alone. | Feedback-loop architecture (generate → measure → re-prompt with gap) is the key pattern for improving LLM test output quality iteratively. Directly applicable to a retry loop in vQA's AC parser. source_tool: WebFetch |
| [Anthropic Structured Outputs (Claude API — GA early 2026)](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) — Official Anthropic blog/announcement | doc (vendor announcement) | B | Structured Outputs entered public beta Nov 2025 (Claude Sonnet 4.5, Opus 4.1), GA early 2026. Uses grammar-based constrained decoding; model literally cannot produce tokens violating schema. Zero JSON parsing errors in reported real-world tests. JSON mode deprecated in favor of structured outputs. Bedrock support timeline not specified in announcement. | vQA's JSON Compiler may be using legacy JSON mode or prompt-only enforcement. Migrating to Claude Structured Outputs API would provide deterministic schema compliance — but Bedrock delivery date for this feature is an open question. source_tool: WebSearch |
| [Three-Layer Reliability Architecture for LLM JSON (practitioner survey via WebSearch)](https://eastondev.com/blog/en/posts/ai/20260506-llm-structured-output/) | post (practitioner) | C | Production pattern: parameter validation layer → failure retry layer → constrained decoding layer. Adding error feedback to retry improved retry success from 60% to >95%. Grammar-based FSM at inference time gives mathematical (not statistical) guarantee. | Retry-with-feedback is a proven production pattern for JSON reliability; relevant to vQA's quality gate design. source_tool: WebSearch |
| [Two-Stage Decoupled Pipeline: deliberation then formatting (practitioner synthesis via WebSearch)](https://tetrate.io/learn/ai/llm-output-parsing-structured-generation) | post (practitioner) | C | Two-stage strategy: first let model deliberate freely, then parse/format output into required structure. Decoupling deliberation from formatting constraint avoids reasoning degradation from format pressure (corroborates Tam et al. 2408.02442). | vQA's BDD Normalizer → JSON Compiler split already follows this best practice at the macro level; the key question is whether each stage also applies it internally. source_tool: WebSearch |
| [AutoCodeRover: Autonomous Program Improvement (SWE-bench 22% patch efficacy)](https://www.researchgate.net/publication/383959416_AutoCodeRover_Autonomous_Program_Improvement) | paper (preprint/ResearchGate) | B | AutoCodeRover uses code search + LLM reasoning for autonomous bug fixing; 22% on SWE-bench-lite. Not directly a test-plan generator but demonstrates LLM agentic loop effectiveness on SE tasks. | Agentic feedback loops (search → reason → verify) outperform single-pass LLM calls; reinforces iterative pipeline design for vQA. source_tool: WebSearch |
| [Rethinking the Value of Agent-Generated Tests (Feb 2026 research, via Zylos AI summary)](https://zylos.ai/research/2026-03-05-ai-agent-automated-test-generation/) | post (secondary summary of research) | C | Agent-written test volume has no statistically significant effect on task resolution rates in autonomous coding agents; more tests ≠ better outcomes. | TRAP CANDIDATE: Adding more LLM-generated test steps to a plan does not guarantee higher QA value — vQA should optimize test plan precision and executability over step count. source_tool: WebSearch |
| [Automated Test Generation Using LLM Based on BDD: A Comparative Study (SCITEPRESS 2025)](https://www.scitepress.org/Papers/2025/136836/136836.pdf) — SCITEPRESS 2025 | paper (conference, PDF unreadable via WebFetch) | C | [SOURCE UNVERIFIED — PDF binary, unable to extract findings via WebFetch] Comparative study of LLM-based BDD test generation; multi-LLM comparison (ChatGPT, Gemini, Grok, GitHub Copilot). | Cannot extract specific findings; see Open Questions. source_tool: WebFetch (failed — PDF binary) |

---

### TRAP Candidates

1. **Format-restriction reasoning degradation (Tam et al., arXiv 2408.02442, Grade B):** Enforcing JSON output in a single LLM call measurably degrades reasoning quality. If vQA's BDD Normalizer or JSON Compiler collapses reasoning + formatting into one prompt step, this may be a root cause of quality failures — not fixable by prompt tuning alone, requiring architectural separation (reason-first, format-second).

2. **Input quality as primary quality driver (BDD Scenario Generation paper, arXiv 2603.04729, Grade B):** Detailed requirement descriptions yield high-quality scenarios; user stories alone yield low quality. If vQA's Jira AC text is consistently sparse or unstructured, prompt engineering improvements may have a low ceiling and require upstream AC quality enforcement (input validation / HITL at AC ingestion).

3. **More tests ≠ better outcomes (Zylos AI summary of Feb 2026 research, Grade C — secondary source):** Agent-generated test volume has no statistically significant effect on task resolution rates. Optimizing for test plan completeness (step count) rather than executability and precision may be misaligned with quality goals. Flagged as TRAP candidate pending access to primary paper.

4. **Hallucination ceiling without validation loops (Large-Scale Study, arXiv 2407.00225, Grade B):** Compilation failure rates of 86% with naive LLM prompting; hybrid LLM + automated validation is required for production quality. A prompt-only fix has an empirical ceiling; an execution/validation feedback loop is necessary to reach production-grade reliability.

---

### Open Questions

1. **Bedrock delivery date for Claude Structured Outputs API:** Anthropic's structured outputs (grammar-based constrained decoding, GA early 2026) may not yet be available via AWS Bedrock's `ChatBedrockConverse` / Converse API. What is the Bedrock release timeline, and does `langchain-aws` expose it? (Routes to DRP-002 / Docs lane.)

2. **SCITEPRESS 2025 BDD comparative study findings:** PDF could not be read via WebFetch. This paper compared ChatGPT, Gemini, Grok, GitHub Copilot for BDD test generation from user stories and acceptance criteria with accuracy, coverage, and clarity metrics — potentially high-relevance findings are inaccessible. Recommend manual fetch.

3. **Peer-reviewed confirmation of BDD scenario generation paper (arXiv 2603.04729):** Published March 2026, not yet confirmed peer-reviewed; grade held at B. If published in a venue, upgrades to A.

4. **Specific failure mode taxonomy for vQA's AC parser:** Literature documents general LLM failure modes (hallucination, schema violation, context overflow) but does not provide a taxonomy specific to the BDD Normalizer → JSON Compiler pipeline shape. The codebase lane (ac_parser.py, prompts.py) is the primary source for this.

5. **Evaluation benchmark for vQA's Golden 10 dataset:** The framing brief references a "Golden 10" benchmark. Academic literature does not provide a validated benchmark for Jira-AC-to-Playwright-test-plan quality specifically. The closest is the EASE 2025 continuous evaluation framework (ACM, access blocked), which proposes a longitudinal evaluation approach. Can vQA's Golden 10 be extended into a longitudinal eval?

6. **Self-consistency sampling for JSON reliability:** Self-consistency (multiple sample majority vote) is well-established for reasoning tasks but literature on its effectiveness specifically for structured JSON output (where outputs must be schema-valid, not just semantically consistent) was not directly found. This is a gap worth targeted search.

7. **DSPy / Instructor / Guardrails AI empirical accuracy data:** Academic benchmarks on these OSS libraries' structured output enforcement for LLM-to-JSON pipelines were not surfaced in this lane. Routes to OSS/Production lane.

---

### Papers Found

| Title | Authors | Year | Relevance |
|-------|---------|------|-----------|
| [Acceptance Test Generation with LLMs: An Industrial Case Study](https://arxiv.org/abs/2504.07244) | Moha et al. | 2025 | Direct analog to vQA's two-stage AC→test pipeline; 95%/92% helpfulness rates with GPT-4 Turbo; 24% regeneration rate |
| [Behaviour Driven Development Scenario Generation with LLMs](https://arxiv.org/abs/2603.04729) | (authors unconfirmed) | 2026 | Evaluates GPT-4/Claude 3/Gemini for BDD from requirements; Claude + CoT is optimal; input quality is primary quality driver |
| [Large-scale Study of LLMs for Test Case Generation](https://arxiv.org/abs/2407.00225) | (authors unconfirmed) | 2024 | 216K tests; GToT best; 86% compile failure naive; hybrid validation required |
| [Understanding CoT Effectiveness in Code Generation](https://arxiv.org/abs/2512.09679) | (authors unconfirmed) | 2024 | Guided CoT +5–12% Pass@1; naive zero-shot CoT can degrade; model capacity matters |
| [Generating Structured Outputs from LLMs: Benchmark and Studies (JSONSchemaBench)](https://arxiv.org/abs/2501.10868) | (authors unconfirmed) | 2025 | 10K JSON schema benchmark; constrained decoding coverage/quality gaps; actionable insights |
| [Let Me Speak Freely? Format Restrictions on LLM Performance](https://arxiv.org/abs/2408.02442) | Tam et al. | 2024 | Format constraints degrade reasoning; answer-after-reasoning field ordering critical |
| [Meaning Typed Prompting / Semantix](https://arxiv.org/abs/2410.18146) | (authors unconfirmed) | 2024 | Type-annotated prompting outperforms few-shot/CoT for structured output accuracy, reliability, token efficiency |
| [CoverUp: Coverage-Guided LLM-Based Test Generation](https://arxiv.org/abs/2403.16218) | Pizzorno & Berger | 2024 | Iterative feedback loop (coverage → re-prompt) achieves 80% vs 47%; feedback architecture is the key pattern |
| [AutoCodeRover: Autonomous Program Improvement](https://www.researchgate.net/publication/383959416_AutoCodeRover_Autonomous_Program_Improvement) | (authors unconfirmed) | 2024 | 22% SWE-bench-lite; agentic loop with search + verify outperforms single-pass LLM |
| [Automated Test Generation Using LLM Based on BDD: Comparative Study](https://www.scitepress.org/Papers/2025/136836/136836.pdf) | (authors unconfirmed) | 2025 | BDD test generation comparison (ChatGPT/Gemini/Grok/Copilot) — [SOURCE UNVERIFIED, PDF binary] |
