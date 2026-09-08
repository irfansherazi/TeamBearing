---
legacy_id: FEAT-105
version: next
linked_tasks: [linear-pipeline-execution-engine-rewrite-spec, linear-pipeline-execution-engine-rewrite-spec]
status: planned
---

### FEAT-105: Linear Pipeline Execution Engine Rewrite
- **Version**: next
- **Status**: planned
- **Review**: ARCHITECTURAL SIGN-OFF (APPROVED) — 2026-06-04 · Principal Engineer
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: Complete architectural overhaul of the vQA execution engine. Transitions from a non-deterministic, cyclic real-time LLM planning loop (0/10 benchmark success on complex SPAs) to a linear, deterministic **Generate → Validate → Execute → Analyze** pipeline. LLMs are used strictly offline: pre-run test generation and post-run failure analysis — never for real-time DOM traversal.

  **Pipeline DAG (4 steps)**:
  1. **Generate Node** — LLM receives normalized BDD steps + tenant-isolated selector mappings + Context helper interfaces (e.g., `SearchHelper.ts`) and produces a complete, self-contained Playwright `.spec.ts` test file.
  2. **Validate Node (Type Gate)** — Runs `npx tsc --noEmit` on the generated spec. Allows exactly one LLM auto-fix retry on compilation failure; halts with `COMPILE_FAILED` on second failure.
  3. **Execute Node** — Runs the spec via headless Playwright against staging. On strict-mode collision, injects a scoped-locator correction prompt to the Generate node (exactly one regeneration attempt). Escalates to human code reviewer on second failure.
  4. **Analyze Node** — On test failure, a secondary LLM parses Playwright trace logs + `selectors.json` to produce human-readable AC-level failure reports.

  **Multi-Tenancy Architecture**:
  - Tenant-partitioned directory structure (`tenants/{tenant_id}/vqa.config.json`, `selectors.json`, `helpers/`)
  - BM25 RAG context strictly hard-fenced per tenant; full helper inject fallback for <10-file corpora
  - Selector RAG limited to top-5 BM25 hits (<200 tokens); compile-time `TenantSelectorKey` union type generated from `selectors.json` to catch LLM hallucinations at the Type Gate

  **Custom Playwright Selector Engine** (`vqaEngine`):
  - Replaces `addInitScript` dynamic DOM tagging (vulnerable to Angular microtask races)
  - **Pure stateless function (~38 LoC)** — zero local variables, zero MutationObservers, zero caches
  - Priority chain: `data-vqa-id` → `aria-label` exact match → `input[placeholder]` exact match
  - Multi-tier legacy fallback via `_isStandardSelector()` supports CSS and `text=` queries on un-tagged pages; emits `VQA_SELECTOR_FALLBACK` JSON warning to track tagging debt
  - Search root scoped to active PrimeNG overlay (`.p-sidebar`, `.p-dialog`, `[role="dialog"]`) when present; falls back to full document

  **Milestones**:
  - Week 1: Linear pipeline merged, LangGraph loop deleted, Compilation Gate validated (>90% compile rate on 50-card corpus)
  - Week 2: Helper RAG wired, SearchHelper unit tests passing, Playwright runner active (~30–40% pass rate baseline)
  - Week 4: Strict-mode loop active, Analyze node active, 80% completion rate on 50-card corpus

  **Pre-condition Gate**: `tests/benchmarks/corpus_50.json` must be committed and signed off by the Product Owner before Week 1 metrics are measured.
- **Acceptance Criteria**:
  - AC-1: LangGraph real-time planning loop is deleted; `core/pipeline.ts` executes the linear Generate→Validate→Execute→Analyze DAG as a single consolidated module.
  - AC-2: Validate block runs `npx tsc --noEmit` and allows exactly one LLM auto-fix retry; marks run `COMPILE_FAILED` on second failure. Selector keys validated at runtime against `selectors.json` schema (no build-time code generation step).
  - AC-3: Custom `vqaEngine` Playwright selector is registered as a **pure stateless function**; resolves `data-vqa-id`, `aria-label`, `input[placeholder]`, and provides legacy CSS/`text=` fallback via `_isStandardSelector()`.
  - AC-4: Strict-mode collision in Execute triggers exactly one scoped-locator regeneration; second failure escalates to human reviewer — no infinite loops.
  - AC-5: BM25 retrieval for selector RAG injects only top-5 results (<200 tokens); falls back to full inject when helper corpus <10 files.
  - AC-6: `analyze` block maps Playwright stack trace failures to AC-step level in a human-readable failure report.
  - AC-7: `tests/benchmarks/corpus_50.json` corpus is frozen and PO-signed before Week 1 metrics are recorded.
  - AC-8: Week 4 benchmark achieves ≥80% end-to-end pass rate on the 50-card corpus against a controlled staging environment.
- **Build Guardrails** (non-negotiable, from Principal Engineer sign-off):
  - **LoC Ceiling**: Total production code in `core/` must not exceed **350 Lines of Code** at completion.
  - **Retry Discipline**: Validate self-heal loop and Execute disambiguation loop are each limited to exactly **1 retry**; a third attempt must throw a structured hard exception and escalate to human review.
  - **Structured Logging Only**: All stdout must be OpenTelemetry-compliant single-line JSON (`timestamp`, `level`, `node`, `message`, `tenant_id`). Raw `console.log` is prohibited.
  - **Test Coverage**: 100% statement and branch coverage required on runtime validator logic and all conditional paths in `vqaEngine.ts`.
  - **Zero State in `vqaEngine.ts`**: No local variables, caches, or event listeners may ever be introduced into the selector logic.
- **Key Files** (~318 LoC production / ~400 LoC tests):
  - `core/pipeline.ts` (New — unified 4-step DAG, 280 LoC)
  - `core/selectors/vqaEngine.ts` (New — pure stateless selector resolver, 38 LoC)
  - `core/types/TenantAuth.ts` (New — tenant auth interface contract)
  - `tests/core/pipeline.spec.ts` (New — unit tests: compile failures, retry limits, DAG boundaries)
  - `tests/core/vqaEngine.spec.ts` (New — 100% branch coverage: standard, overlay, legacy fallback paths)
  - `tenants/vpromedia/vqa.config.json` (New — tenant base configuration)
  - `tenants/vpromedia/selectors.json` (New — sidecar locator map with semantic descriptions)
  - `tenants/vpromedia/helpers/SearchHelper.ts` (New — deterministic autocomplete helper)
  - `tests/benchmarks/corpus_50.json` (New — locked PO-signed benchmark corpus)
  - `package.json` (Modify — add `tsx`, `vitest` runners)
- **Source Plan**: `.agent-logs/rewrite-planning/2026-06-03-dvq-re-check-loop-evaluator-integration-plan.md`
- **Interrogation Report**: `.agent-logs/interrogations/FEAT-105-interrogation-report.md`
- **Linked Tasks**: [linear-pipeline-execution-engine-rewrite-spec](tasks/linear-pipeline-execution-engine-rewrite-spec.md)
- **Branch**: feature/FEAT-105-linear-pipeline-rewrite
- **Created**: 2026-06-04
