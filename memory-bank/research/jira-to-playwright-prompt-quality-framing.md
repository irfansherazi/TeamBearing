# Spike Framing Brief: jira-to-playwright-prompt-quality

**Source**: ad-hoc topic
**Date**: 2026-07-15
**Framing agent**: bmb:spike-framing-agent (Phase 0)

---

## Research Objectives

Reduce the uncertainty around why vQA's two-stage LLM pipeline (BDD Normalizer → JSON Compiler)
produces unreliable Playwright test plans from Jira AC text, and identify which interventions —
prompt engineering, model upgrade, structured output enforcement, retrieval augmentation, or
human-in-the-loop checkpoints — are most likely to close the quality gap at acceptable cost and
latency. The spike must surface concrete, applicable techniques that respect the existing LangGraph
+ AWS Bedrock (Claude 3.5 Sonnet) architecture rather than requiring a wholesale rewrite.

---

## Research Questions

1. What are the specific failure modes in the current two-stage AC parsing pipeline (BDD Normalizer
   → JSON Compiler), and which failure mode accounts for the largest share of bad test-plan output?
2. What prompt engineering techniques — structured output enforcement, chain-of-thought, few-shot
   exemplars, self-consistency, or constrained generation — have demonstrated measurable accuracy
   gains for requirement-to-test-plan translation tasks on LLMs at Claude 3.5 Sonnet capability level?
3. Would upgrading to Claude 3.5/3.7 Sonnet with extended thinking, or switching to a structured
   output API (JSON mode / tool-use forcing), produce reliably better JSON Compilation fidelity
   without unacceptable latency or cost increases?
4. What are the design options for a human-in-the-loop (HITL) checkpoint between AC parsing and
   test execution — specifically, what is the minimum viable review UI that lets a QA engineer
   correct a bad test plan before execution proceeds?
5. Are there OSS or commercial pipeline components (e.g., LangChain output parsers, Instructor,
   Guardrails AI, DSPy) that solve structured output + retry logic for LLM-to-JSON workflows and
   could be layered on top of the existing Bedrock calls without replacing the planner?

---

## Ambiguity Profile

| Dimension            | Level  | Key Question |
|----------------------|--------|--------------|
| Requirements         | HIGH   | Which specific behaviors define "quality" for a test plan — correct step sequence, correct verifications, correct component mapping, or all three equally? |
| Technical feasibility | MEDIUM | Do prompt-only improvements have a ceiling that requires model upgrade or architectural change to clear? |
| Existing-solutions   | HIGH   | What OSS libraries or prompt patterns already solve LLM-to-structured-JSON fidelity for test-plan generation at production quality? |
| Architecture         | HIGH   | Should the HITL checkpoint be a new LangGraph node, a pre-execution review gate in the frontend, or an async review flow — and how does each option interact with batch mode? |
| Data/evaluation      | HIGH   | How will improvement be measured — what benchmark dataset and metrics constitute "reliable" AC parsing, and does the existing Golden 10 dataset cover AC parsing quality specifically? |
| Integration/codebase | MEDIUM | The two-stage parser is in `ac_parser.py` + `prompts.py`; how much refactoring is safe without destabilizing the planner/executor that depend on the JSON schema? |
| Effort-estimation    | MEDIUM | Prompt tuning is cheap; a new HITL review node or model swap has unknown cost — what is the likely engineering effort for each intervention tier? |

_Omitted (low ambiguity): Safety/compliance — no regulatory risk; internal tool, AWS Bedrock data residency already established._

---

## Activated Lanes  (Spike Depth: deep)

_Score: 4 HIGH dimensions → depth = deep (≥3 HIGH threshold met)._

| Lane                   | Status   | Reason |
|------------------------|----------|--------|
| Academic / SOTA        | ACTIVATE | Requirements: HIGH — need to understand what "quality" means in test-plan generation; Data/evaluation: HIGH — evaluation methodology for LLM-to-test-plan pipelines is an active research area |
| OSS / Production       | ACTIVATE | Existing-solutions: HIGH — libraries like Instructor, DSPy, Guardrails AI, LangChain output parsers are directly relevant; need production evidence of real-world reliability gains |
| Practitioner Discourse | ACTIVATE | (default-on) Effort-estimation: MEDIUM — practitioner blogs, case studies, and community threads are the best source for real-world prompt tuning ROI and HITL design patterns |
| Official Docs          | ACTIVATE | Existing-solutions: HIGH + Integration/codebase: MEDIUM — AWS Bedrock structured output APIs, Claude tool-use / JSON mode docs, and Playwright test-plan schema patterns need official sourcing |
| Internal / Codebase    | ACTIVATE | (default-on) Architecture: HIGH — `ac_parser.py`, `prompts.py`, `ac_quality_gate.py`, `vision_analyzer.py`, and the LangGraph node graph are directly in scope; the benchmark script is the evaluation baseline |

---

## Deep Research Probes

| probe_id | research_question | ambiguity_dimension | insufficiency_rationale | expected_output_shape | recommended_run_mode |
|----------|-------------------|---------------------|-------------------------|-----------------------|----------------------|
| DRP-001  | What prompt engineering techniques — few-shot exemplars, chain-of-thought, self-consistency, or output-constrained generation — produce the largest measurable accuracy gains for LLM-driven requirement-to-structured-test-plan translation, and what benchmarks or evaluation frameworks exist to verify those gains? | Data/evaluation + Requirements | Academic literature on LLM test generation is rapidly evolving (2024–2026); normal OSS lane will surface libraries but may miss the most recent evaluation methodology papers (e.g., TestPilot, CoverAgent, AutoCodeRover) that directly address this problem shape. Cross-domain (SE testing + prompt engineering) means a single lane is unlikely to surface the full signal. | Prior-art survey: technique × accuracy-gain table, with cited evaluation datasets and metrics; highlight any techniques already partially implemented in vQA's `prompts.py` | agent-run |
| DRP-002  | What are the practical build-vs-buy options for enforcing structured JSON output from Claude via AWS Bedrock — specifically, does Bedrock's tool-use / function-calling API enforce schema compliance deterministically, and how does Instructor or equivalent compare in real-world JSON Compiler fidelity? | Existing-solutions + Architecture | The question is highly AWS-Bedrock-specific (not generic OpenAI tool-use). Bedrock's converse API tool-use schema enforcement behavior is not well-documented in community blogs; official docs are dense and version-sensitive. The internal codebase uses `ChatBedrockConverse` from `langchain-aws`, adding an abstraction layer whose behavior under tool-use needs verification. | Build-vs-buy map: native Bedrock tool-use vs. Instructor vs. Guardrails AI vs. LangChain output parser — with schema enforcement guarantees, retry behavior, latency cost, and Bedrock compatibility column | agent-run |
| DRP-003  | What HITL checkpoint designs exist for LLM-to-test-plan pipelines — specifically, what is the minimum viable review interface that allows a QA engineer to inspect, edit, and approve a structured test plan before execution, and what has been validated in production tools? | Architecture + Requirements | HITL in AI test generation is underexplored in academic literature; practitioner discourse is fragmented across Slack, Discord, and company engineering blogs. The vQA codebase already has a rich HITL subsystem (human_takeover_node, TakeoverPanel, HITL copilot) but it operates at execution time, not at parse time — the design space for a pre-execution review gate is distinct and may require new frontend patterns not covered by existing memory-bank creative docs. | Design pattern survey: 3–5 HITL checkpoint patterns ranked by implementation complexity; identify which patterns fit the existing LangGraph node graph and React dashboard without requiring new infrastructure | human-assist |

---

## MCP Availability

| Server        | Status      | Affected lane | Notes |
|---------------|-------------|---------------|-------|
| arxiv         | UNAVAILABLE | Academic / SOTA → WebSearch fallback | Not present in available MCP tool list |
| github-search | UNAVAILABLE | OSS/Production → WebSearch fallback | Not present in available MCP tool list |
| context7      | UNAVAILABLE | Official Docs → WebFetch fallback | Not present in available MCP tool list |
| WebSearch     | available   | All lanes (fallback) | Confirmed via ToolSearch; covers practitioner and OSS lanes directly |

All three research MCP servers are unavailable. Lanes will operate in degraded mode using WebSearch
and WebFetch. Academic coverage may be thinner than ideal — DRP-001 is flagged `agent-run` partly
to compensate via deeper targeted searching.

---

## Recommendation

**proceed** — the question is well-formed, the codebase is clearly scoped (`ac_parser.py`,
`prompts.py`, LangGraph node graph), 4 dimensions are HIGH which justifies deep mode, and three
actionable deep-research probes exist to cover the most uncertain slices. The team should activate
all five lanes and run DRP-001 and DRP-002 as agent-run probes before scheduling DRP-003, which
benefits from human review of existing HITL design patterns in the codebase first.
