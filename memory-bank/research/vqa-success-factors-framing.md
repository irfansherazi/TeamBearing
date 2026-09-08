# Phase 0 Framing Brief — vqa-success-factors

**Source**: Ad-hoc topic  
**Framed**: 2026-07-16  
**Mode**: Classifier-driven (no override)

---

## Research Objectives

1. Identify the highest-leverage interventions that would reduce circuit-breaker and budget-cap firing frequency in production — moving the metric from "graceful termination" toward "rarely needed."
2. Determine the state of the art for AC parsing / ambiguous-requirement-to-testable-step translation in LLM-driven test generation pipelines, so vQA can adopt proven techniques rather than reinventing them.
3. Understand how production AI-agent systems bound and measure navigation reliability (action budgets, loop detection, self-correction), and what success rates are considered acceptable before the approach is deprecated.
4. Survey verifier reliability patterns in LLM-as-a-Judge pipelines — specifically how systems guard against false-positive verdicts that corrupt a run's final result.
5. Characterize the class of environment/credential fragility failures (role-specific, URL-specific, transient auth issues) and catalog mitigations that operate without human intervention.

---

## Research Questions

1. What prompt engineering, structured-output constraints, or multi-pass refinement techniques most reliably convert vague Jira acceptance criteria into unambiguous, atomic, testable steps — and what quality-gate thresholds indicate a step is safe to execute versus should be flagged for human review?
2. What action-budget sizes, loop-detection heuristics, and self-correction patterns do production LangGraph / ReAct agent systems use, and at what firing frequency does a circuit breaker indicate the agent strategy itself needs to change rather than the threshold?
3. How do LLM-as-a-Judge verifier pipelines prevent false positives (passing a step that did not complete), and what is the measured FP rate of visual-only verification versus DOM-programmatic-first tiered verification?
4. What credential-rotation, environment-health-check, and pre-flight validation patterns prevent environment-specific failures (wrong role, wrong URL, stale session) from propagating into test verdicts?
5. Is there empirical evidence — from academic benchmarks or production telemetry — for a "floor" AC quality score below which autonomous execution success rates drop to near-zero, and can that floor be measured cheaply enough to use as a run gate?

---

## Ambiguity Profile

| Dimension | Level | Key Question |
|---|---|---|
| Requirements | MEDIUM | The five factors are named but their relative priority and which to address first (AC parser vs. navigation vs. verifier) is unclear — there is no ordering criterion in the brief. |
| Technical feasibility | MEDIUM | Techniques for vague-AC-to-testable-step translation exist in research but it is unknown whether any achieve reliability high enough to reduce the HITL rate to the < 20% target without human review. |
| Existing-solutions | HIGH | It is unknown whether production-grade LLM test-generation systems (Meticulous, Reflect.run, proprietary pipelines) have published approaches to AC parsing quality, navigation budgets, or verifier reliability that vQA can borrow or adapt. |
| Architecture | HIGH | It is unknown whether the current 4-node-per-step LangGraph pipeline (documented as an anti-pattern in systemPatterns.md) is the structural root cause of the high circuit-breaker rate — versus prompt quality, verifier logic, or environment instability. |
| Data/evaluation | HIGH | No empirical baseline exists for circuit-breaker firing frequency per flow type, verifier FP rate, or AC quality score vs. execution success rate — making it impossible to prioritize interventions without guessing. |
| Integration/codebase | MEDIUM | The codebase already has ac_quality_gate.py, verifier.py tiering, and multiple circuit breakers — but the interaction and coverage gaps between them are not profiled; touching one may regress another. |
| Effort-estimation | MEDIUM | Each of the five factors could be a one-week prompt change or a six-week architectural rewrite; without knowing which solutions exist off-the-shelf, effort is unbounded. |
| Safety/compliance | LOW | — |

_Omitted (low ambiguity): Safety/compliance_

---

## Activated Lanes  (Spike Depth: deep)

**Depth rationale**: Three dimensions score HIGH (Existing-solutions, Architecture, Data/evaluation). Per the classifier threshold (≥3 HIGH → deep), all relevant lanes activate at full depth.

| Lane | Status | Reason |
|---|---|---|
| Academic / SOTA | ACTIVATE | Architecture HIGH + Data/evaluation HIGH: literature on LLM agent loop reliability, verifier grounding, and AC quality measurement is directly relevant and may surface evaluation frameworks not yet in the codebase. |
| OSS / Production | ACTIVATE | Existing-solutions HIGH: Meticulous, Reflect.run, testRigor, and open-source LangGraph agent repos may have published or open-sourced circuit-breaker thresholds, verifier designs, or AC parsing pipelines worth borrowing. |
| Practitioner Discourse | ACTIVATE | (default-on) + Effort-estimation MEDIUM: blog posts, conference talks, and Discord/Slack archives from AI agent practitioners are the primary source for "what actually works in production" on SPA navigation and LLM-as-a-Judge reliability. |
| Official Docs | ACTIVATE | Integration/codebase MEDIUM + Existing-solutions HIGH: LangGraph docs (circuit-breaker / recursion limit patterns), Playwright docs (deterministic wait patterns), and AWS Bedrock docs (token budget / context window management) are in-scope given the codebase's specific dependencies. |
| Internal / Codebase | ACTIVATE | (default-on) + Architecture HIGH: the current circuit-breaker configuration, verifier thresholds, and AC quality gate thresholds live in the codebase and must be baselined before any external research can be applied. Internal telemetry from run logs is the only source for empirical firing-frequency data. |

---

## Deep Research Probes

| probe_id | research_question | ambiguity_dimension | insufficiency_rationale | expected_output_shape | recommended_run_mode |
|---|---|---|---|---|---|
| DRP-001 | What techniques — structured prompting, chain-of-thought decomposition, ambiguity detection classifiers, or multi-agent review — most reliably convert under-specified natural-language acceptance criteria into atomic, unambiguous, machine-executable test steps, and what AC quality thresholds predict execution failure with >80% precision? | Data/evaluation + Requirements | Normal OSS/practitioner lanes will surface high-level advice ("be more specific") but are unlikely to surface empirically validated quality thresholds or classifier designs. This is a cross-domain question spanning NLP quality estimation and software testing that sits between academic NLP and practitioner QA tooling — a gap neither lane covers well alone. Sparse public data on commercial tools (Meticulous does not publish internals). | Ranked list of techniques with measured precision/recall on AC quality prediction; candidate quality-gate thresholds (score → execution success rate); reference implementations or papers. | human-assist |
| DRP-002 | In production LangGraph / ReAct agent systems navigating stateful SPAs, what action-budget sizes and loop-detection heuristics are used, at what firing frequency does a circuit breaker indicate the navigation strategy itself needs architectural change, and what self-correction patterns (model escalation, KB injection, deterministic fallback) have documented success rates? | Architecture + Existing-solutions | The Compounding Pipeline Depth Anti-Pattern in systemPatterns.md names this as a known failure class but provides no evidence-based remediation. Practitioner discourse covers ReAct loops generically; SPA-specific (Angular/PrimeNG) navigation budget research is sparse. Cross-domain: agent systems research + SPA test automation + LangGraph-specific implementation patterns — no single lane covers all three. | Circuit-breaker configuration table (budget size, firing threshold, recommended action); architectural alternatives ranked by documented success rate on SPA navigation; evidence on whether model escalation alone recovers stuck agents. | human-assist |

---

## MCP Availability

| Server | Status | Affected Lane |
|---|---|---|
| WebSearch | available | OSS/Production, Practitioner Discourse — primary fallback for all external research |
| WebFetch | available | Official Docs, OSS/Production — fetch specific documentation pages and GitHub repos |
| arxiv | UNAVAILABLE (not probed — not in environment) | Academic / SOTA → WebSearch fallback for paper discovery |
| github-search | UNAVAILABLE (not probed — not in environment) | OSS/Production → WebSearch + gh CLI fallback |
| context7 | UNAVAILABLE (not probed — not in environment) | Official Docs → WebFetch fallback |

**Degradation assessment**: WebSearch + WebFetch cover the practitioner, OSS, and official-docs lanes adequately. The Academic lane degrades to keyword-based paper search rather than structured arxiv query — depth is reduced but not eliminated. Internal/Codebase lane is unaffected (filesystem reads). No probe is blocked by MCP absence.

---

## Recommendation

**proceed** — Three HIGH ambiguity dimensions with an established codebase, named success metrics, and available WebSearch/WebFetch tooling give the spike enough grounding to produce actionable findings. The primary risk is that Data/evaluation ambiguity (no empirical baseline for circuit-breaker firing frequency) means Phase 1 lanes should prioritize the Internal/Codebase lane first to establish a baseline before external research can be meaningfully applied.
