---
legacy_id: linear-pipeline-execution-engine-rewrite-spec
---
# linear-pipeline-execution-engine-rewrite-spec: Linear Pipeline Execution Engine Rewrite SPEC

**Complexity**: Level 4 (Enterprise/Architectural)
**Status**: BUILD_COMPLETE
**Roadmap**: [FEAT-105: Linear Pipeline Execution Engine Rewrite](../roadmap.md#feat-105-linear-pipeline-execution-engine-rewrite)
**Branch**: feature/FEAT-105-linear-pipeline-rewrite
**Worktree**: main (no worktree — building on feature branch directly)
**Interrogation Report**: [linear-pipeline-execution-engine-rewrite-spec-interrogation-report.md](../../.agent-logs/interrogations/linear-pipeline-execution-engine-rewrite-spec-interrogation-report.md)
**Creative Specs**: [linear-pipeline-execution-engine-rewrite-spec-algorithm.md](../creative/linear-pipeline-execution-engine-rewrite-spec-algorithm.md), [linear-pipeline-execution-engine-rewrite-spec-architecture.md](../creative/linear-pipeline-execution-engine-rewrite-spec-architecture.md), [linear-pipeline-execution-engine-rewrite-spec-user-journey.md](../creative/linear-pipeline-execution-engine-rewrite-spec-user-journey.md)

## Task Description

Complete architectural overhaul of the vQA execution engine. Transitions from a non-deterministic, cyclic real-time LLM planning loop (which produces 0/10 benchmark success on complex SPAs) to a linear, deterministic **Generate → Validate → Execute → Analyze** pipeline. LLMs are used strictly offline: pre-run test generation and post-run failure analysis — never for real-time DOM traversal.

### Pipeline DAG (4 steps):
1. **Generate Node** — LLM receives normalized BDD steps + tenant-isolated selector mappings + Context helper interfaces (e.g., `SearchHelper.ts`) and produces a complete, self-contained Playwright `.spec.ts` test file.
2. **Validate Node (Type Gate)** — Runs `npx tsc --noEmit` on the generated spec. Allows exactly one LLM auto-fix retry on compilation failure; halts with `COMPILE_FAILED` on second failure. Selector keys are validated at runtime against `selectors.json` schema (no build-time code generation step).
3. **Execute Node** — Runs the spec via headless Playwright against staging. On strict-mode collision, injects a scoped-locator correction prompt to the Generate node (exactly one regeneration attempt). Escalates to human code reviewer on second failure.
4. **Analyze Node** — On test failure, a secondary LLM parses Playwright trace logs + `selectors.json` to produce human-readable AC-level failure reports.

### Multi-Tenancy Architecture:
- Tenant-partitioned directory structure (`tenants/{tenant_id}/vqa.config.json`, `selectors.json`, `helpers/`)
- BM25 RAG context strictly hard-fenced per tenant; full helper inject fallback for <10-file corpora
- Selector RAG limited to top-5 BM25 hits (<200 tokens)

### Custom Playwright Selector Engine (`vqaEngine`):
- Replaces `addInitScript` dynamic DOM tagging (vulnerable to Angular microtask races)
- **Pure stateless function (~38 LoC)** — zero local variables, zero MutationObservers, zero caches
- Priority chain: `data-vqa-id` → `aria-label` exact match → `input[placeholder]` exact match
- Multi-tier legacy fallback via `_isStandardSelector()` supports CSS and `text=` queries on un-tagged pages; emits `VQA_SELECTOR_FALLBACK` JSON warning to track tagging debt
- Search root scoped to active PrimeNG overlay (`.p-sidebar`, `.p-dialog`, `[role="dialog"]`) when present; falls back to full document

---

## User Journey Definition

**Feature Type**: Architectural/Infrastructure
**Creative Phase Required**: Yes (Creative Architectural Sign-off Issued by Principal Engineer)

### NFR Verification (Infrastructure Features)
- **Test method**: Run the custom unit test suites:
  ```bash
  npx vitest tests/core/pipeline.spec.ts tests/core/vqaEngine.spec.ts
  ```
- **Success metrics**:
  - 100% statement and branch coverage on runtime validation and `vqaEngine.ts` conditional paths.
  - Settle on a locked, PO-signed benchmark corpus `tests/benchmarks/corpus_50.json` before Week 1 measurements.
  - End-to-end execution of the pipeline against the 50-card corpus, achieving ≥80% pass rate in Week 4.
  - Total production code inside `core/` (excluding tests) does not exceed **350 Lines of Code**.
- **Observable at**:
  - Single-line JSON structured logs on `stdout` conforming to OpenTelemetry schema:
    - Must contain `timestamp`, `level`, `node`, `message`, `tenant_id`
    - Contains `VQA_SELECTOR_FALLBACK` technical debt warning metric for legacy selector fallbacks

---

## Acceptance Criteria

### AC-1: LangGraph loop deletion and Consolidated Engine Pipeline
**Priority**: MUST
**Given** the new pipeline is invoked
**When** orchestrating execution
**Then**:
- The LangGraph cyclic execution loop files (`backend/engine/langgraph_loop.py` and `backend/browser/addInitScript_dynamic_tagging.ts`) are completely deleted.
- `core/pipeline.ts` executes the linear Generate→Validate→Execute→Analyze DAG as a single consolidated module under 280 LoC.

### AC-2: Validate Node with Strict 1-Retry Compiler Gate
**Priority**: MUST
**Given** a newly generated Playwright `.spec.ts` test file
**When** the compiler gate executes `npx tsc --noEmit`
**Then**:
- If compilation succeeds, the gate opens immediately.
- If compilation fails, the error output is sent back for exactly ONE auto-fix retry.
- If the second compilation attempt fails, the pipeline halts immediately, logging `COMPILE_FAILED`.
- All selector keys used in the test spec are validated at runtime against the schema in the tenant's `selectors.json` (no build-time code generation step).

### AC-3: Pure Stateless custom `vqaEngine` Selector resolver
**Priority**: MUST
**Given** Playwright executing selectors
**When** parsing `vqa=...` locators
**Then**:
- Custom `vqaEngine` resolves elements using the priority chain: `data-vqa-id` → `aria-label` exact match → `input[placeholder]` exact match.
- If standard selector operators (CSS, `text=`, class/id indicators) are present, it falls back to standard Playwright selection and emits a `VQA_SELECTOR_FALLBACK` warning log (JSON-formatted).
- Scopes search space automatically to active overlay subtree (`.p-sidebar`, `.p-dialog`, `[role="dialog"]`) if visible in DOM.
- No local state, caching, local variables, or mutation observers are introduced.

### AC-4: Strict-Mode Collision Auto-Regeneration Loop
**Priority**: MUST
**Given** Playwright executing the generated spec
**When** a strict-mode collision error is encountered (multi-element match)
**Then**:
- The error is captured and a structured parent-scoped correction prompt is sent back to the Generate node.
- Exactly ONE regeneration attempt is allowed.
- A second consecutive failure halts execution immediately and escalates to a human code reviewer.

### AC-5: High-Speed Token-Efficient Selector RAG
**Priority**: MUST
**Given** step generation for a tenant
**When** querying BM25 retrieval for selectors
**Then**:
- Query retrieves strictly the top 5 most semantically relevant selectors (<200 token budget).
- Full Helper Inject fallback is used if the tenant's helper corpus has fewer than 10 helper files.

### AC-6: Analyze Node Post-Run failure Translation
**Priority**: MUST
**Given** a test execution failure
**When** logging final results
**Then**:
- Secondary LLM parses Playwright trace logs and `selectors.json` to generate an AC-level human-readable failure report (e.g., mapping line-level stack traces back to scenario BDD steps).

### AC-7: Standard OpenTelemetry JSON Structured Logging
**Priority**: MUST
**Given** any stdout or warnings logged by the engine
**When** printed to console
**Then**:
- All output is structured as single-line JSON with keys: `timestamp`, `level`, `node`, `message`, `tenant_id`.
- No raw text or un-structured `console.log` statements are present.

### AC-8: Immutable PO-Signed 50-Card Baseline Corpus
**Priority**: MUST
**Given** benchmark runs in Week 1
**When** measuring baseline execution
**Then**:
- `tests/benchmarks/corpus_50.json` must be committed and signed off by the Product Owner before work begins.

---

## Test Strategy

### Approach
- **100% Statement & Branch Coverage**: Focus on full coverage of all logical branches in `core/selectors/vqaEngine.ts` and the runtime schema validator in `core/pipeline.ts`.
- **DAG Boundary Mocks**: Unit tests in `tests/core/pipeline.spec.ts` mocking compilation failures (exactly 1 retry), execution collisions, and state transitions to prevent any slow third-party API dependencies during unit execution.
- **Fast, Isolated Tests**: Tests run with `vitest` in under 100ms.

### File Organization
- **New Unit Test Files**:
  - `tests/core/pipeline.spec.ts`: Test pipeline execution boundaries, self-healing retries, and compilation gate behaviors.
  - `tests/core/vqaEngine.spec.ts`: Tests `vqaEngine` query and queryAll selectors against mock DOM structures (standard elements, PrimeNG dialog overlays, legacy fallbacks, fallback logging).

---

## Build Guardrails (Architectural Sign-off)

The following non-negotiable build guardrails from the [linear-pipeline-execution-engine-rewrite-spec Interrogation Report](../../.agent-logs/interrogations/linear-pipeline-execution-engine-rewrite-spec-interrogation-report.md) must be adhered to:
1. **LoC Ceiling Constraint**: The total production code inside the `core/` directory (excluding test suites) must not exceed **350 Lines of Code** at completion.
2. **Strict-Mode Loop Restraint**: The Validate Node self-healing loop and the Executor strict-mode disambiguation loop must be limited to **exactly one retry**. A third consecutive attempt must immediately fail with a hard, structured exception to prevent infinite loops.
3. **Pure Structured Logging**: Standard text-based console logging (e.g., raw `console.log` statements) is strictly prohibited in production modules. All stdout must be formatted as structured JSON lines conforming to OpenTelemetry (with keys `timestamp`, `level`, `node`, `message`, `tenant_id`, and `technical_debt_metrics` for legacy fallbacks).
4. **Near-100% Test Coverage**: You must achieve **100% statement and branch coverage** on the runtime schema validator logic inside the Validate Node and all conditional branches of the custom selector in `vqaEngine.ts`.
5. **No State in `vqaEngine.ts`**: The custom selector resolver must remain **100% stateless**. Under no circumstances may local variables, internal caches, or dynamic `MutationObserver` event listeners be introduced.

---

## Implementation Roadmap

- [x] **Phase 1: Foundation & Stateless Selector Resolver (WI-105-001)**
  - Implement `core/selectors/vqaEngine.ts` following PE final sign-off (~38 LoC).
  - Implement `core/types/TenantAuth.ts` strict multi-tenant interfaces.
  - Write `tests/core/vqaEngine.spec.ts` testing query, queryAll, active overlays, and legacy CSS/text= fallbacks.
  - Achieve 100% statement and branch coverage on `vqaEngine.ts`.
- [x] **Phase 2: Consolidated Engine Pipeline (WI-105-002)**
  - Implement `core/pipeline.ts` with Generate, Validate (tsc gate + runtime validation), Execute, and Analyze nodes (~280 LoC).
  - Implement strict 1-retry self-healing on Compile and Execute strict-mode collisions.
  - Integrate OpenTelemetry single-line JSON logging schema.
- [x] **Phase 3: Multi-Tenant Configs & Helper Library (WI-105-003)**
  - Establish `tenants/vpromedia/vqa.config.json` and `selectors.json`.
  - Implement `tenants/vpromedia/helpers/SearchHelper.ts` containing autocomplete and guard routines.
  - Create the locked, PO-signed `tests/benchmarks/corpus_50.json` corpus.
- [x] **Phase 4: Pipeline Unit and Verification Test Suite (WI-105-004)**
  - Write `tests/core/pipeline.spec.ts` to mock compilation, execution strict-mode errors, and verify exact-1 retry limits.
  - Verify that the total production code under `core/` does not exceed 350 Lines of Code.
  - Verify all unit and integration tests passing.

---

## Execution State

**Build Status**: COMPLETE
**Phase Being Built**: Phase 4 — Pipeline Unit and Verification Test Suite (WI-105-004)
**Phase Number**: 4 of 4 (ALL PHASES COMPLETE)
**Is Multi-Phase**: YES
**Build Started**: 2026-06-05T14:25:00Z
**Last Completed**: Phase 4 — Pipeline Unit and Verification Test Suite (WI-105-004)
**Can Resume**: NO

**Current Build Step**:
  Step: Step 11 — Git Completion
  Status: COMPLETE
  Completed: 2026-06-05T14:35:00Z

### Active Sub-Agents
(none)

### Completed Steps
#### Phase 1 (Foundation & Stateless Selector Resolver) — COMPLETE ✅
- Step 0: Parse Task ID — COMPLETE
- Step 0.1: Resumption Check — COMPLETE (fresh build)
- Step 0.5: Git Setup — COMPLETE (branch: feature/FEAT-105-linear-pipeline-rewrite)
- Step 0.6: Phase Gate — COMPLETE (all checks PASS)
- Step 1: Read Task Context — COMPLETE
- Step 2: Load Level 4 Context — COMPLETE
- Step 3: Test Writer — COMPLETE (tests/core/vqaEngine.spec.ts — 15 tests)
- Step 4: Coding Agent — COMPLETE (core/selectors/vqaEngine.ts 61 LoC, core/types/TenantAuth.ts 29 LoC)
- Step 5: Test Batching — COMPLETE (1 batch: vqaEngine)
- Step 6: Test Execution — COMPLETE (15/15 PASS, 100%/100% stmt/branch coverage)
- Step 7: Integration Verification — COMPLETE (27/27 PASS)
- Step 8: Code Review — COMPLETE (APPROVED, Security: PASS)
- Step 9: Documentation — COMPLETE (inline comments preserved, package.json scripts added)
- Step 10: Memory Bank — COMPLETE
- Step 11: Git Completion — COMPLETE (commit: 5ab94c5, branch: feature/FEAT-105-linear-pipeline-rewrite)

#### Phase 2 (Consolidated Engine Pipeline) — COMPLETE ✅
- Step 1: Read Task Context — COMPLETE (Phase 2 of 4)
- Step 2: Load Level 4 Context — COMPLETE
- Step 3: Tests — COMPLETE (tests/core/pipeline.spec.ts — 12 tests)
- Step 4: Coding Agent — COMPLETE (core/pipeline.ts 182 LoC)
- Step 5: Test Batching — COMPLETE (1 batch: pipeline)
- Step 6: Test Execution — COMPLETE (27/27 PASS — 12 pipeline + 15 vqaEngine)
- Step 7: Integration Verification — COMPLETE (27/27 PASS, 99.38%/80% stmt/branch)
- Step 8: Code Review — COMPLETE (APPROVED — branch coverage gaps deferred to Phase 4)
- Step 9: Documentation — COMPLETE
- Step 10: Memory Bank — COMPLETE
- Step 11: Git Completion — COMPLETE (commit: 24ce119, branch: feature/FEAT-105-linear-pipeline-rewrite)

#### Phase 4 (Pipeline Unit and Verification Test Suite) — COMPLETE ✅
- Step 1: Read Task Context — COMPLETE (Phase 4 of 4)
- Step 2: Load Level 4 Context — COMPLETE
- Step 3: Branch coverage analysis — COMPLETE (identified 13 uncovered branches in pipeline.ts)
- Step 4: Coding Agent — COMPLETE (null-guard fix: +1 LoC to pipeline.ts at line 157)
- Step 5: Test Batching — COMPLETE (1 batch: pipeline coverage)
- Step 6: Test Execution — COMPLETE (52/52 PASS — 24 pipeline + 15 vqaEngine + 13 searchHelper)
- Step 7: Integration Verification — COMPLETE (52/52 PASS, **100%/100%** stmt/branch ALL files)
- Step 8: Code Review — COMPLETE (APPROVED — Security: PASS, LoC: 271/350 ✅)
- Step 9: Documentation — COMPLETE
- Step 10: Memory Bank — COMPLETE
- Step 11: Git Completion — COMPLETE (branch: feature/FEAT-105-linear-pipeline-rewrite)

- Phase 1 (Foundation & Stateless Selector Resolver): COMPLETE ✅
- Phase 2 (Consolidated Engine Pipeline): COMPLETE ✅
- Phase 3 (Multi-Tenant Configs & Helper Library): COMPLETE ✅
- Phase 4 (Pipeline Unit and Verification Test Suite): COMPLETE ✅
