---
legacy_id: FEAT-060
version: next
linked_tasks: [execution-performance-overhaul-high-throughput-pipeline-engi]
status: complete
---

### FEAT-060: Execution Performance Overhaul — High-Throughput Pipeline Engine
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Transform vQA from a reactive, strictly-sequential agent into a high-throughput execution engine. The current "See-Think-Act" loop averages ~4.5s per turn, largely due to high-latency multimodal LLM calls, 15k+ token context overhead per turn, serial ticket/AC execution, redundant LLM-based verification, and fixed SPA hydration costs. The goal is a **60–70% reduction in end-to-end execution time**, targeting **sub-10s average time per AC step**.

    **Phase 1 — Loop Latency & LLM Optimization** (Foundation)
    1. **Tiered Model Routing**: Replace the single-model strategy with a three-tier routing layer. Tier 1 (fast/cheap — Haiku/Flash) handles deterministic actions (click, fill, navigate) where no visual ambiguity exists. Tier 2 (balanced — Sonnet) handles planning with partial context. Tier 3 (powerful — Opus/Sonnet Vision) is reserved exclusively for HITL escalations, Set-of-Marks CV fallback, and GenAI assertions. Routing logic driven by action type and confidence score, not hardcoded per-step.
    2. **Prompt Compression Pipeline**: Implement a multi-stage compression layer applied before every LLM call: (a) ARIA tree differential — only transmit DOM nodes that changed since the last screenshot (delta-diffing vs. full tree); (b) screenshot resolution downscaling from 1280×800 → 640×400 for planning calls (vision detail is wasted for click/fill actions); (c) rolling context summarization — after every 5 turns, compress the action history into a single `<session_summary>` block, dropping raw action logs. Target: reduce average tokens/turn from 15k → 5k.
    3. **Speculative Pre-fetch**: Immediately after the planner emits an action, begin pre-fetching the next AC step's KB context (selector RAG query + domain enrichment) in a background thread while the current action executes in Playwright. Eliminates the inter-step dead time between Playwright completion and LLM call start.

    **Phase 2 — Context Overhead Reduction** (Efficiency)
    4. **Dynamic System Prompt Caching**: Leverage Anthropic's prompt caching API (cache_control breakpoints) on the static portions of the system prompt (tool schemas, global rules, recipe library). Only the dynamic context (current AC step, ARIA diff, action history) is re-sent each turn. Expected: 60–80% reduction in input token cost and ~500ms latency reduction per cached turn.
    5. **Playwright-Native Assertion Bypass**: Before invoking the LLM verifier, attempt a deterministic Playwright assertion sequence derived from the AC step text (e.g., `expect(locator).toHaveText()`, `expect(locator).toBeVisible()`). If ALL assertions pass, mark the step VERIFIED and skip the LLM verifier call entirely. Only invoke the LLM verifier for steps where deterministic assertions are insufficient (ambiguous visual state, toast messages, semantic checks). Target: eliminate LLM verifier on ≥40% of AC steps.
    6. **SPA Hydration Fast-Path**: Replace the current fixed-delay strategy for SPA hydration (Angular/PrimeNG) with an event-driven wait: listen for the Angular `ApplicationRef.isStable()` hook and PrimeNG `p-progressBar` disappearance via MutationObserver. Only fall back to a fixed timeout if the stability event does not fire within 2s. Eliminates the hardcoded wait overhead on every page transition.

    **Phase 3 — Horizontal Scaling & Parallelism** (Throughput)
    7. **Parallel AC Step Execution** (Independent Steps): The AC parser detects data-flow dependencies between steps. Steps with no shared state (e.g., "Verify column A" and "Verify column B") are dispatched to separate, isolated Playwright browser contexts and executed concurrently. A dependency graph DAG governs execution order; only dependent steps are serialized. Expected: 2–3× throughput improvement on cards with ≥4 independent steps.
    8. **Parallel Ticket Execution**: Introduce a `RunOrchestrator` that maintains a pool of N Playwright browser contexts (configurable, default N=3). Multiple Jira tickets from the same run queue are dispatched to different contexts simultaneously. Each context has its own VQAState, isolated session storage, and independent LLM call budget. Results are merged into a unified run report at the end. Requires RunOrchestrator service, context pool manager, and a shared-state-safe report aggregator.
    9. **Speculative Plan Generation**: While Phase-N is executing, begin generating the plan for Phase-N+1 in the background. The "think" phase of the next step starts during the "act" phase of the current step. If the current action fails and changes the expected state, the speculative plan is discarded; otherwise it is applied immediately — eliminating one full LLM round-trip per step.

    **Phase 4 — Prompt Engineering & Adaptive Intelligence** (Polish)
    10. **Step-Scoped System Prompts**: Replace the single monolithic system prompt with dynamically assembled, step-scoped prompts. Each turn only receives the recipe rules, KB context, and tool schemas relevant to the predicted action type for that step. Global rules are injected only on the first turn and cached. Reduces per-turn token footprint by 30–50%.
    11. **Confidence-Gated HITL**: Replace binary HITL escalation (N consecutive failures → escalate) with a confidence-scored escalation model. Each verifier call returns a `confidence` score (0.0–1.0). Only escalate to HITL when `confidence < 0.4` AND `iteration_count > threshold`. Mid-confidence steps (0.4–0.7) trigger a lightweight retry with an alternate strategy rather than immediate escalation. Reduces unnecessary HITL interrupts by an estimated 30–50%.
    12. **Adaptive Timeout Profiling**: Track per-action-type P95 timing from historical runs (stored in a lightweight SQLite table). Use the P95 as the dynamic timeout ceiling for that action type, replacing all hardcoded `wait_for_selector` and `page.wait_for_timeout` calls. Eliminates the fixed worst-case waits that inflate execution time on fast-rendering environments.

- **Success Metrics**:
    - Average time per AC step ≤ 10s (baseline: ~45s end-to-end per step including LLM latency)
    - Token cost reduction ≥ 60% vs. current baseline (via caching + compression + verifier bypass)
    - Parallel ticket throughput: ≥ 3 concurrent tickets with no state cross-contamination
    - LLM verifier bypass rate ≥ 40% of AC steps (Playwright-native assertions)
    - Zero regression in AC step pass rate (must maintain ≥ 90% pass rate from v3.0.0 baseline)
    - HITL escalation rate reduction ≥ 30% (via confidence-gated escalation)
- **Phased Implementation**:
    - **Phase 1**: Tiered Model Routing + Prompt Compression Pipeline + Speculative Pre-fetch
    - **Phase 2**: Prompt Caching + Playwright-Native Assertion Bypass + SPA Hydration Fast-Path
    - **Phase 3**: Parallel AC Step Execution + Parallel Ticket Execution + Speculative Plan Generation
    - **Phase 4**: Step-Scoped Prompts + Confidence-Gated HITL + Adaptive Timeout Profiling
- **Linked Tasks**: execution-performance-overhaul-high-throughput-pipeline-engi
- **Branch**: feature/FEAT-060-execution-performance-overhaul
- **Created**: 2026-05-31
- **Completed**: 2026-05-31 ✅
