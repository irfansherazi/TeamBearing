---
legacy_id: execution-performance-overhaul-high-throughput-pipeline-engi
---
# execution-performance-overhaul-high-throughput-pipeline-engi: Execution Performance Overhaul — High-Throughput Pipeline Engine

## Header

**Status**: COMPLETE
**Phase**: BUILD
**Complexity**: Level 4
**Roadmap Link**: FEAT-060
**Branch**: feature/FEAT-060-execution-performance-overhaul
**Created**: 2026-05-31
**Owner**: Engineering

---

## Execution State

**Build Status**: COMPLETE (All 4 Phases) — ARCHIVED
**Phase Being Built**: DONE — Archived
**Phase Number**: 4 of 4 COMPLETE
**Is Multi-Phase**: YES
**Build Started**: 2026-05-31T11:45:39-05:00
**Phase 4 Completed**: 2026-05-31T17:22:00-05:00
**Reflection Completed**: 2026-05-31T17:35:00-05:00
**Creative Completed**: 2026-05-31T10:58:00-05:00

### Current Build Step
**Step**: IDLE — Archive complete
**Status**: COMPLETE

### Completed Steps (Phase 1 + Phase 2 + Phase 3 + Phase 4)
- [Phase 1] All steps: COMPLETE (`58007a9`)
- [Phase 2] Step 3 — Test Writer: COMPLETE (69 new tests across 3 files)
- [Phase 2] Step 4 — Coding Agent: COMPLETE (3 components + config + planner/executor wiring)
- [Phase 2] Step 5 — Code Review: COMPLETE (9 files reviewed, all APPROVED)
- [Phase 2] Step 6 — Tests GREEN: 145/145 total tests passing (76 P1 + 69 P2), 0 regressions
- [Phase 2] Step 7 — Commit + Push: COMPLETE (`4c913af`)
- [Phase 3] Step 3 — Test Writer: COMPLETE (80 new tests across 3 files)
- [Phase 3] Step 4 — Coding Agent: COMPLETE (DependencyAnalyzer + RunOrchestrator + SpeculativePlanner + config + state)
- [Phase 3] Step 5 — Code Review: COMPLETE (3 new source files APPROVED, 2 modified files APPROVED)
- [Phase 3] Step 6 — Tests GREEN: 1088 total suite passing (145 P1+P2 + 80 P3 + existing), 0 new regressions
- [Phase 3] Step 7 — Commit + Push: COMPLETE (`425baf8`)
- [Phase 4] Step 3 — Test Writer: COMPLETE (71 new tests across 3 files)
- [Phase 4] Step 4 — Coding Agent: COMPLETE (PromptAssembler + TimingDB + TimeoutProfiler + confidence-gated HITL)
- [Phase 4] Step 5 — Code Review: COMPLETE (6 files reviewed, 1 cleanup applied, all APPROVED)
- [Phase 4] Step 6 — Tests GREEN: 71/71 Phase 4 tests PASS; 1167/1191 suite PASS (24 pre-existing infra failures confirmed)

### Phase 4 Test Summary
- `tests/test_prompt_assembler.py`: 16 tests (all PASS)
- `tests/test_confidence_gated_hitl.py`: 16 tests (all PASS)
- `tests/test_timeout_profiler.py`: 39 tests (all PASS)
- **Total Phase 4**: 71 tests GREEN
- Pre-existing failures (not caused by Phase 4): 24 (test_playwright_run_security, test_vnc_api — confirmed pre-existing on main)

### Phase 4 Files Delivered
- **NEW**: `backend/engine/prompt_assembler.py` (P4A — step-scoped system prompt builder)
- **NEW**: `backend/storage/timing_db.py` (P4C — SQLite per-action timing persistence)
- **NEW**: `backend/engine/timeout_profiler.py` (P4C — adaptive P95×2 timeout ceilings)
- **NEW**: `backend/storage/__init__.py` (storage package init)
- **MODIFIED**: `backend/config.py` (+6 Phase 4 feature flags: step_scoped_prompts_enabled, confidence_gated_hitl_enabled, confidence_hitl_threshold_low/high, adaptive_timeouts_enabled, timing_db_path)
- **MODIFIED**: `backend/engine/state.py` (+`_verifier_confidence: float` field + initialization)
- **MODIFIED**: `backend/engine/verifier.py` (+`_verifier_confidence` emitted on all verdict return paths)
- **MODIFIED**: `backend/engine/evaluator.py` (+confidence-gated HITL: 3-band routing at HITL threshold)

---

## Description

Transform vQA from a reactive, strictly-sequential agent into a high-throughput execution engine.

**Current Baseline (measured)**:
- Average see-think-act cycle: ~4.5s per turn
- Per-step time (AC step including all turns): ~45s end-to-end
- Token usage: ~15k tokens per turn
- LLM verifier called on 100% of steps
- Fixed SPA hydration delays on every page transition

**Target (FEAT-060)**:
- ≤ 10s average per AC step (60–70% reduction)
- ≤ 5k tokens per turn (60%+ reduction via compression + caching)
- LLM verifier bypassed on ≥ 40% of AC steps
- ≥ 3 concurrent tickets with no state cross-contamination
- HITL escalation rate reduction ≥ 30%

---

## Acceptance Criteria

### AC-ENTRY-1: Feature Gate Safety
- **Given** any FEAT-060 sub-feature is deployed
- **When** the corresponding `ENABLE_*` environment variable is set to `false`
- **Then** the system behaves identically to the pre-FEAT-060 baseline (zero regression)

### AC-HAPPY-1: Tiered Model Routing Correct
- **Given** an AC step involving a deterministic action (click, fill, navigate) with no ambiguity
- **When** the planner processes it on the first attempt
- **Then** Tier 1 (Haiku) is used and the action executes successfully within 3s

### AC-HAPPY-2: Prompt Compression Reduces Token Count
- **Given** a planner turn that previously consumed 15k tokens
- **When** ARIA differential diffing + rolling context summarization are active
- **Then** average token count per turn is ≤ 6k (measured via Bedrock usage metadata)

### AC-HAPPY-3: Playwright-Native Assertion Bypass
- **Given** an AC step with an unambiguous deterministic assertion (e.g., `toHaveText`, `toBeVisible`)
- **When** the Playwright assertion sequence passes
- **Then** the LLM verifier is NOT called, and the step is marked VERIFIED in the audit report

### AC-HAPPY-4: SPA Hydration Event-Driven
- **Given** a page transition in the Angular/PrimeNG application
- **When** the Angular `isStable()` event fires before the 2s fallback timeout
- **Then** execution proceeds without invoking the fixed-delay wait

### AC-HAPPY-5: Prompt Caching Reduces Cost
- **Given** a run with 5+ AC steps using the same static system prompt
- **When** Anthropic prompt caching is active
- **Then** Bedrock usage shows cache read tokens for ≥ 60% of input tokens in turns 2+

### AC-HAPPY-6: Parallel Ticket Execution — No State Cross-Contamination
- **Given** N=3 concurrent tickets dispatched to the RunOrchestrator
- **When** all 3 execute simultaneously with isolated browser contexts
- **Then** each produces a correct, independent audit report and VQAState shows no field cross-contamination

### AC-HAPPY-7: Adaptive Timeout Profiling — Dynamic Ceiling
- **Given** a `click` action type with a P95 timing of 800ms from historical runs
- **When** the dynamic timeout profiler is active
- **Then** the Playwright timeout for that action type is set to ≤ 2× P95 (≤ 1600ms), not the hardcoded worst-case

### AC-EDGE-1: Speculative Plan Discarded on Failure
- **Given** a speculative plan is being generated for step N+1
- **When** step N fails and changes the expected page state
- **Then** the speculative plan is discarded and a fresh plan is generated for the corrected state

### AC-EDGE-2: Parallel AC Steps — Dependent Steps Serialized
- **Given** an AC card with 6 steps where steps 3 and 4 both depend on step 2
- **When** the dependency DAG is computed
- **Then** steps 1, 2, 3, 4, 5, 6 are executed with only independent steps parallelized (no race on shared state)

### AC-EDGE-3: Confidence-Gated HITL — Mid-Range Retry
- **Given** a verifier call returns confidence=0.55 (mid-range: 0.4–0.7) AND iteration_count < threshold
- **When** the confidence-gated escalation evaluates
- **Then** a lightweight retry with an alternate strategy fires instead of HITL escalation

### AC-NFR-1: Zero Regression in AC Pass Rate
- **Given** the full FEAT-060 implementation is active
- **When** the Golden 10 benchmark dataset is run
- **Then** AC step pass rate is ≥ 90% (baseline maintained, no regression)

### AC-NFR-2: Token Cost Baseline Measurable
- **Given** a controlled benchmark run with FEAT-060 Phase 1 active
- **When** Bedrock usage metadata is aggregated
- **Then** token cost per step is logged to `metrics.py` and comparable to pre-FEAT-060 baseline

---

## Clarifications Needed

None — requirements are fully specified in FEAT-060 roadmap entry with concrete success metrics.

---

## Specification

### System Context

vQA is a LangGraph state machine (10 nodes) with a See-Think-Act loop. Each action invokes Claude via AWS Bedrock, captures a Playwright screenshot + ARIA tree, and appends to an audit log. The planner (`planner.py`, ~4600 LOC) already has a two-tier escalation (Haiku → Sonnet), but no true routing layer, no prompt caching, and no parallel execution.

**Current Model Routing**:
- Default: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Tier 1/2 proxy)
- Auto-escalation: `us.anthropic.claude-sonnet-4-20250514-v1:0` after `auto_escalate_threshold` (default 3) retries

**Current Performance Bottlenecks** (identified):
1. Every planner turn sends full ARIA tree + full screenshot (~15k tokens)
2. LLM verifier called on every AC step — even simple DOM-checkable conditions
3. Fixed `wait_for_timeout` calls scattered across executor/verifier (30+ instances)
4. Sequential ticket execution — one ticket at a time in the LangGraph
5. Full system prompt re-sent every turn (no caching)
6. KB pre-fetch happens after action completes (sequential dead time)

### Implementation Architecture

**Four-Phase Delivery** (each phase is independently deployable with feature flags):

#### Phase 1: Loop Latency & LLM Optimization (Foundation)
*Estimated impact: 40–50% latency reduction per turn*

**Item 1 — Full Three-Tier Model Routing** (`backend/engine/planner.py`, `backend/engine/model_router.py` [NEW])
- Extract routing logic into `ModelRouter` class
- Tier 1 (Haiku): deterministic actions (click, fill, navigate, scroll, wait) with no visual ambiguity
- Tier 2 (Sonnet): planning with partial context, recipe disambiguation, multi-match resolution  
- Tier 3 (Sonnet Vision full): HITL escalation, SoM CV fallback, GenAI assertions only
- Routing driven by `action_type` + `confidence_score` field in `PlannerAction` schema
- Feature flag: `MODEL_ROUTER_ENABLED` (default `true`)

**Item 2 — Prompt Compression Pipeline** (`backend/engine/planner.py`, `backend/browser/aria_diff.py` [NEW])
- Stage (a): ARIA differential diffing — compute delta between previous and current ARIA tree, only transmit changed nodes
- Stage (b): Screenshot resolution downscaling — 1280×800 → 640×400 for Tier 1 actions (full res only for Tier 2/3)
- Stage (c): Rolling context summarization — after every 5 turns, compress action history into `<session_summary>` block
- Target: 15k → 5k tokens per turn
- Feature flag: `PROMPT_COMPRESSION_ENABLED` (default `true`)

**Item 3 — Speculative Pre-fetch** (`backend/engine/graph.py`, `backend/kb/prefetcher.py` [NEW])
- After planner emits action, begin pre-fetching next AC step's KB context (selector RAG + domain enrichment) in `asyncio.create_task()`
- Cache result in `VQAState.prefetch_cache` (dict keyed by step index)
- If prefetch not ready when needed, fall back to synchronous fetch
- Feature flag: `SPECULATIVE_PREFETCH_ENABLED` (default `true`)

#### Phase 2: Context Overhead Reduction (Efficiency)
*Estimated impact: 25–35% cost reduction, ~500ms latency per cached turn*

**Item 4 — Dynamic System Prompt Caching** (`backend/engine/planner.py`)
- Leverage Anthropic's `cache_control` breakpoints in the Bedrock converse API
- Mark static sections (tool schemas, global rules, recipe library) with `"cachePoint": {"type": "default"}`
- Only dynamic context (current AC step, ARIA diff, action history) re-sent each turn
- Expected: 60–80% reduction in input token cost on turns 2+
- Feature flag: `PROMPT_CACHING_ENABLED` (default `true`)

**Item 5 — Playwright-Native Assertion Bypass** (`backend/engine/verifier.py`, `backend/engine/assertion_compiler.py` [NEW])
- `AssertionCompiler` parses AC step text → generates Playwright assertion sequence
- Before invoking LLM verifier: run compiled assertions; if ALL pass → mark VERIFIED, skip LLM call
- Patterns: `toHaveText()`, `toBeVisible()`, `toContainText()`, `toHaveValue()`, `toHaveCount()`
- Only falls through to LLM verifier on: ambiguous visual state, toast messages, semantic checks
- Target: bypass LLM on ≥ 40% of AC steps
- Feature flag: `NATIVE_ASSERTION_ENABLED` (default `true`)

**Item 6 — SPA Hydration Fast-Path** (`backend/engine/executor.py`, `backend/browser/spa_hydration.py` [NEW])
- Replace fixed-delay strategy with event-driven wait
- Listen for Angular `ApplicationRef.isStable()` hook via `page.evaluate()` JavaScript injection
- PrimeNG `p-progressBar` disappearance via MutationObserver
- Fall back to fixed timeout (2s) if stability event does not fire
- Feature flag: `SPA_HYDRATION_EVENT_DRIVEN` (default `true`)

#### Phase 3: Horizontal Scaling & Parallelism (Throughput)
*Estimated impact: 2–3× throughput improvement*

**Item 7 — Parallel AC Step Execution** (`backend/engine/graph.py`, `backend/engine/dependency_analyzer.py` [NEW])
- `DependencyAnalyzer` computes data-flow dependency DAG from parsed AC steps
- Steps with no shared state dispatched to separate Playwright browser contexts concurrently via `asyncio.gather()`
- Shared-state steps serialized via topological sort of DAG
- `VQAState` updated with `parallel_step_groups: list[list[int]]` for the execution engine
- Feature flag: `PARALLEL_STEPS_ENABLED` (default `false` — opt-in for Phase 3)

**Item 8 — Parallel Ticket Execution** (`backend/engine/run_orchestrator.py` [NEW], `backend/api/routes.py`)
- `RunOrchestrator` maintains pool of N Playwright browser contexts (configurable via `PARALLEL_TICKET_POOL_SIZE`, default 3)
- Multiple Jira tickets from same run queue dispatched to different contexts simultaneously
- Each context has its own `VQAState`, isolated session storage, independent LLM call budget
- Results merged into unified run report via `RunReportAggregator`
- Redis state store required when `PARALLEL_TICKETS_ENABLED=true`
- Feature flag: `PARALLEL_TICKETS_ENABLED` (default `false` — opt-in)

**Item 9 — Speculative Plan Generation** (`backend/engine/planner.py`, `backend/engine/speculative_planner.py` [NEW])
- While Phase-N action executes in Playwright, begin generating plan for Phase-N+1 in background `asyncio.Task`
- If current action fails and changes expected state → discard speculative plan (poison signal)
- If current action succeeds → apply speculative plan immediately, eliminating one LLM round-trip per step
- Feature flag: `SPECULATIVE_PLANNING_ENABLED` (default `false` — opt-in for Phase 3)

#### Phase 4: Prompt Engineering & Adaptive Intelligence (Polish)
*Estimated impact: 30–50% per-turn token reduction, 30–50% HITL reduction*

**Item 10 — Step-Scoped System Prompts** (`backend/engine/planner.py`, `backend/engine/prompt_assembler.py` [NEW])
- Replace single monolithic system prompt with `PromptAssembler` that builds step-scoped prompts
- Each turn only receives recipe rules, KB context, and tool schemas relevant to predicted action type
- Global rules injected only on first turn and cached (complements Item 4)
- Feature flag: `STEP_SCOPED_PROMPTS_ENABLED` (default `true`)

**Item 11 — Confidence-Gated HITL** (`backend/engine/evaluator.py`, `backend/engine/verifier_node.py`)
- Replace binary HITL escalation with confidence-scored model
- LLM verifier returns `confidence: float` (0.0–1.0) alongside verdict
- `confidence < 0.4` AND `iteration_count > threshold` → HITL
- `confidence 0.4–0.7` → lightweight retry with alternate strategy
- `confidence > 0.7` → accept as VERIFIED
- Reduces unnecessary HITL by estimated 30–50%
- Feature flag: `CONFIDENCE_GATED_HITL_ENABLED` (default `true`)

**Item 12 — Adaptive Timeout Profiling** (`backend/engine/timeout_profiler.py` [NEW], `backend/storage/timing_db.py` [NEW])
- Track per-action-type P95 timing from historical runs in SQLite (`timing.db`)
- `TimeoutProfiler.get_timeout_ceiling(action_type)` → returns P95 × 2 as dynamic timeout
- Fallback: hardcoded values (preserved for first N runs until P95 is established)
- `executor.py` and `recipe_runner.py` use `TimeoutProfiler` instead of hardcoded ms values
- Feature flag: `ADAPTIVE_TIMEOUTS_ENABLED` (default `false` — opt-in after data collection)

---

## Implementation Roadmap

### Sub-tasks (recommended execution order)

**Phase 1 (Build Sprint 1)**:
1. execution-performance-overhaul-high-throughput-pipeline-engi-P1A: `ModelRouter` class + updated routing in `_invoke_planner_with_tools()`
2. execution-performance-overhaul-high-throughput-pipeline-engi-P1B: `AriaDiff` differential diffing + screenshot downscaling
3. execution-performance-overhaul-high-throughput-pipeline-engi-P1C: Rolling context summarization in `prompt_budget.py`
4. execution-performance-overhaul-high-throughput-pipeline-engi-P1D: `KBPrefetcher` speculative pre-fetch via `asyncio.create_task()`

**Phase 2 (Build Sprint 2)**:
5. execution-performance-overhaul-high-throughput-pipeline-engi-P2A: `cache_control` breakpoints in planner Bedrock call
6. execution-performance-overhaul-high-throughput-pipeline-engi-P2B: `AssertionCompiler` + verifier bypass path
7. execution-performance-overhaul-high-throughput-pipeline-engi-P2C: `SpaHydration` event-driven fast-path

**Phase 3 (Build Sprint 3 — requires Phase 1+2 stable)**:
8. execution-performance-overhaul-high-throughput-pipeline-engi-P3A: `DependencyAnalyzer` + parallel AC step execution
9. execution-performance-overhaul-high-throughput-pipeline-engi-P3B: `RunOrchestrator` + parallel ticket pool
10. execution-performance-overhaul-high-throughput-pipeline-engi-P3C: `SpeculativePlanner` background task

**Phase 4 (Build Sprint 4)**:
11. execution-performance-overhaul-high-throughput-pipeline-engi-P4A: `PromptAssembler` step-scoped prompt builder
12. execution-performance-overhaul-high-throughput-pipeline-engi-P4B: Confidence score in verifier + evaluator escalation logic
13. execution-performance-overhaul-high-throughput-pipeline-engi-P4C: `TimeoutProfiler` SQLite store + executor wiring

---

## Test Strategy

### Unit Tests (pytest)

| Test File | Coverage |
|-----------|----------|
| `tests/test_model_router.py` | Routing decisions for each tier, auto-escalation boundaries |
| `tests/test_aria_diff.py` | Delta computation correctness, empty delta edge case |
| `tests/test_prompt_compression.py` | Token count before/after compression, summarization trigger |
| `tests/test_assertion_compiler.py` | Pattern matching, bypass decision (skip LLM vs fall-through) |
| `tests/test_spa_hydration.py` | Event-driven path, timeout fallback, stability detection |
| `tests/test_dependency_analyzer.py` | DAG construction, topological sort, independent step detection |
| `tests/test_run_orchestrator.py` | Pool management, state isolation, report aggregation |
| `tests/test_confidence_gated_hitl.py` | Confidence bands, mid-range retry vs escalation |
| `tests/test_timeout_profiler.py` | P95 computation, dynamic ceiling, fallback to hardcoded |

### Integration Tests (benchmark)

```bash
# Baseline: pre-FEAT-060 token usage + timing
python scripts/benchmark_pipeline.py --full --tag pre-feat-060

# After each phase: compare token cost + timing
python scripts/benchmark_pipeline.py --full --tag post-phase-1
```

### Benchmark Metrics (AC-NFR-2)

Track per-phase in `benchmark_report.json`:
- `avg_tokens_per_turn`: target ≤ 6000 (Phase 1 complete)
- `avg_seconds_per_ac_step`: target ≤ 10s (all phases complete)
- `verifier_bypass_rate`: target ≥ 0.40 (Phase 2 complete)
- `hitl_rate`: target 30% reduction vs baseline
- `ac_step_pass_rate`: must stay ≥ 0.90 at all times

---

## Guiding Principle Compliance

| Principle | Compliance | Notes |
|-----------|------------|-------|
| Multimodal Grounding | ✅ Maintained | Tier 1 downscales for speed; Tier 2/3 retain full resolution |
| Semantic Locators First | ✅ Maintained | AssertionCompiler uses Playwright semantic assertions, not CSS |
| Failure Diary Pattern | ✅ Maintained | Speculative plans purged on failure before adding to diary |
| Programmatic Tier 1 Verification | ✅ Extended | AssertionCompiler is a direct extension of this principle |
| Config in Environment | ✅ Enforced | All 12 sub-features gated by feature flags in `config.py` |
| HITL as Learning Signal | ✅ Maintained | Confidence-gated HITL does not remove HITL; it reduces false triggers |

**Potential Deviations**:
- **Parallel Ticket Execution** (Item 8) requires Redis state store — deviates from single-container default. Requires explicit `state_store=redis` + `PARALLEL_TICKETS_ENABLED=true`. Documented as a deployment upgrade.
- **SQLite Timing DB** (Item 12) adds a new persistence layer. Will be co-located in the `memory/` directory alongside accepted tests. No schema migration required (new table).

---

## Open Questions / Decisions for Human Review

> [!IMPORTANT]
> **Q1 — Parallel Ticket Context Isolation**: Phase 3 parallel ticket execution requires browser context isolation. Current `graph.py` creates one Playwright context per run. Should the `RunOrchestrator` manage its own Playwright `browser.new_context()` pool, or should it delegate context creation to the existing `graph.py` setup flow (single context per LangGraph invocation)?
>
> **Recommendation**: `RunOrchestrator` manages its own context pool independently. Each ticket gets a fresh `browser.new_context()` from a shared `Browser` instance. This is cleaner than threading context management through LangGraph.

> [!IMPORTANT]
> **Q2 — Dependency DAG Source**: For Phase 3 parallel AC step execution, how should the `DependencyAnalyzer` detect data dependencies? Options:
> 1. **Heuristic**: Steps sharing variable references (e.g., extracted values) or same target UI component are considered dependent
> 2. **LLM-based**: Short LLM call at parse time to label step dependencies
> 3. **Conservative default**: Only parallelize explicit "Verify" steps (read-only operations) — no write operations parallelized
>
> **Recommendation**: Option 3 (conservative default) for Phase 3 initial rollout — parallelizes verification-only steps which have clear read-only semantics. Promotes to Option 1 heuristics in a follow-up.

> [!IMPORTANT]
> **Q3 — Phase Delivery Order**: All 4 phases are independently deployable. Should they be built as separate tasks (4 task files, 4 PRs) or as one monolithic execution-performance-overhaul-high-throughput-pipeline-engi build with phases as internal milestones?
>
> **Recommendation**: 4 separate build tasks (light-mode-dark-mode-toggle through jira-and-execution-engine-reliability-polish), one per phase. Each phase ships independently, gets its own PR, and can be measured against metrics before the next phase begins. This is a Level 4 risk mitigation strategy.

---

## Creative Phases

**Creative Phase Required**: YES (Level 4)

| Phase | Status | Output |
|-------|--------|--------|
| [x] Architecture Design — `RunOrchestrator` + context pool (Phase 3) | COMPLETE | `memory-bank/creative/execution-performance-overhaul-high-throughput-pipeline-engi-run-orchestrator-architecture.md` |
| [x] Algorithm Design — `DependencyAnalyzer` DAG (Phase 3) | COMPLETE | `memory-bank/creative/execution-performance-overhaul-high-throughput-pipeline-engi-dependency-analyzer-algorithm.md` |

**Decisions Made**:
- **RunOrchestrator**: Option A — `asyncio.gather()` on N isolated `BrowserContext` objects. Zero changes to `graph.py`. Surgical `BrowserManager` extension (`injected_context` param).
- **DependencyAnalyzer**: Option A — Conservative Verify-Only parallelization. O(n) single-pass. READ-only steps (verify, assert) parallelized; WRITE steps always sequential.

Note: Phases 1 and 2 items are lower-risk and do not require dedicated creative exploration beyond this plan. The architecture + algorithm designs gate Phase 3 (parallel execution) specifically.

---

## Session Log

**2026-05-31**: execution-performance-overhaul-high-throughput-pipeline-engi created for FEAT-060 via `/vc-plan feat-060`. Planning phase initiated. Status: PLANNING.
**2026-05-31**: Value assessment completed via `/vc-value-check execution-performance-overhaul-high-throughput-pipeline-engi`. Recommendation: PROCEED (Phases 1+2 immediately; gate Phase 3 on results).

---

## Value Assessment

**Assessed**: 2026-05-31T10:44:05-05:00
**Assessor**: vc-value-check workflow

### Scores

| Axis | Score |
|------|-------|
| Strategic Value | High |
| User Impact | High |
| Build Confidence | High (with caveats) |

### Recommendation: PROCEED

**Rationale**: execution-performance-overhaul-high-throughput-pipeline-engi directly advances the primary performance NFRs (per-step cycle < 15s, batch throughput < 30 min) and crosses a critical adoption threshold — PM feedback drops from ~10 min to <2 min, converting vQA from a background batch job to an interactive co-pilot. The CI gate becomes a viable blocking rule for the first time. All 12 sub-features are independently gated with a <5 min rollback SLA, a pre-build benchmark snapshot is planned, and a canary strategy is defined. The phased delivery model (light-mode-dark-mode-toggle through jira-and-execution-engine-reliability-polish) substantially de-risks a Level 4 engagement.

**Risks flagged**:
- **AssertionCompiler false positives**: If bypass logic emits a too-lenient Playwright assertion, a broken feature receives a GREEN audit report — the highest business risk identified. A manual audit of 50 randomly sampled bypass steps is required before `NATIVE_ASSERTION_ENABLED` is set `true` by default.
- **Context amnesia**: Over-aggressive rolling summarization (Items 2/10) could cause the planner to forget critical constraints (e.g., "do not click Delete"). Explicit multi-turn constraint-adherence tests required.
- **Phase 3 parallelism blast radius**: RunOrchestrator + Redis + DependencyAnalyzer DAG touch 4 of 7 high-risk areas simultaneously. Phase 3 must be gated on Phase 1+2 production benchmark results.
- **Redis dependency gap**: `redis` and `hiredis` are missing from `backend/requirements.txt` — must be added before Phase 3 build begins.

**Suggested scope optimization**:
- PROCEED immediately with light-mode-dark-mode-toggle (Phase 1: Loop Latency & LLM Optimization) + production-readiness-hardening-and-execution-loop-prevention (Phase 2: Context Overhead Reduction). These 6 items deliver sub-10s/step and 60%+ token cost reduction with zero Redis dependency and no concurrency risk — approximately 70% of total FEAT-060 value.
- Hold verifier-integrity-and-anti-hallucination-guardrails (Phase 3: Parallelism) until Phase 1+2 are stable in production and the Golden 10 benchmark confirms ≥60% latency reduction.
- Consider interleaving FEAT-054 (Persona Switching) after Phase 2 ships to advance adoption breadth while Phase 3 is under design.

**Interview notes**:
- Primary KPI driver is speed (Time-to-test) — PM feedback loop from ~10 min → <2 min crosses the threshold where efficiency gain changes from negligible to 10×.
- CI gate is currently "warn-only" or disabled; FEAT-060 (even Phases 1+2 alone) is what makes it a practical blocking rule.
- Cost scaling is a compounding urgency — as the suite grows from Golden 10 → Golden 100, 15k tokens/turn becomes a budgetary constraint. Prompt caching + compression (Phase 1+2) are prerequisites for financially viable full regression suites.
- FEAT-054 (Persona Switching) is the highest-ROI alternative if adoption breadth (not speed) is the team's current bottleneck.
- The user confirmed Phases 1+2 alone likely satisfy the primary PM and CI gate KPIs — Phase 3 parallelism is additive throughput, not required for the core value delivery.
