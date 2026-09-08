# Design Document: /vc-uat and Linear Pipeline Convergence Plan
**Date**: 2026-06-05
**Status**: DRAFT (Pending Product Owner Approval)
**Task Reference**: `TASK-106` (Sprint 3 / WU-3.3)

---

## 1. Background & Executive Summary

Over the past sprints, vQA has developed two distinct paradigms for executing Behavior-Driven Development (BDD) user acceptance tests (UAT):
1. **Cyclic LangGraph Explorer (`/vc-uat`)**: An agentic, real-time explorer that loops between planning, executing single steps, verifying, and adjusting state. It is highly interactive and supports rich dashboard feedback but suffers from compounding LLM latencies and brittle state management.
2. **Stateless Linear Pipeline (`linear_runner.py`)**: A deterministic 4-node DAG (Generate → Validate → Execute → Analyze) that compiles raw Jira acceptance criteria into a unified, self-contained Playwright `.spec.ts` script, validates its compilation, executes it sequentially via Playwright, and analyzes trace logs on failure. This approach minimizes LLM API costs and execution latencies while leveraging robust self-healing retry mechanisms.

This document outlines the **Linear Pipeline Convergence Plan** to merge these two architectures into a unified production-grade engine, eliminating redundant execution code paths, consolidating state reporting, and maximizing end-to-end platform stability.

---

## 2. Architectural Comparison

| Dimension | Cyclic LangGraph Loop (`/vc-uat`) | Stateless Linear Pipeline (`linear_runner`) |
| :--- | :--- | :--- |
| **Flow Structure** | Cyclic Graph (LangGraph) | Stateless 4-Node DAG (In-Memory) |
| **Spec Execution** | Zero-shot step-by-step DOM queries | Sequentially compiled, self-contained Playwright file |
| **Latency / Node** | Very High (1 LLM call per step action) | Extremely Low (1-2 LLM calls per run) |
| **Self-Healing** | Exploratory search, heavy DOM diffing | A11y-powered timing/interaction 3-retry loops |
| **State Verification** | Visual delta & ARIA tree diffs (high noise) | Deterministic Playwright assertions (`expect`) |
| **Escalation Path** | Immediate Human-in-the-Loop (HITL) | Automatic LLM Trace Analysis & Jira Commenting |

---

## 3. Unified Core Architecture

The converged system will promote the **Linear Pipeline** as the default, core execution engine, while retaining the `/vc-uat` command as the developer-facing CLI wrapper and dashboard interface.

```
       [ CLI: /vc-uat ]          [ REST API: POST /execute ]
              │                              │
              ▼                              ▼
      ┌──────────────────────────────────────────────┐
      │             ac_parser Core Node              │ (Normalize raw Jira text)
      └──────────────────────┬───────────────────────┘
                             │
                             ▼
      ┌──────────────────────────────────────────────┐
      │        Unified Execution Router Node         │ (Decides engine path)
      └──────┬───────────────────────────────┬───────┘
             │                               │
             ├─► [Engine: cyclic]            ├─► [Engine: linear] (Default)
             │   (Deprecated fallback)       │
             ▼                               ▼
      ┌───────────────┐              ┌───────────────────────────┐
      │ LangGraph     │              │ Generate spec.ts          │
      │ Explorer      │              ├───────────────────────────┤
      │ Loop          │              │ Compile-Gate Validate     │
      └───────────────┘              ├───────────────────────────┤
                                     │ Playwright Execute +      │
                                     │ A11y Self-Healing Loop    │
                                     ├───────────────────────────┤
                                     │ LLM Trace Failure Analyze │
                                     └─────────────┬─────────────┘
                                                   │
                                                   ▼
      ┌────────────────────────────────────────────┴─────────────┐
      │            Unified Run History & S3 Reporter             │
      └──────────────────────────────────────────────────────────┘
```

### 3.1 Step 1: Normalization & BDD Step Parsing
All execution requests run through `ac_parser_node`.
- If `expected_steps` is provided as an override, the parsing is skipped (supporting human-in-the-loop adjustments).
- If empty, raw acceptance criteria are compiled into standard BDD goals.

### 3.2 Step 2: The Compilation-Gate Validate
The generated Playwright `.spec.ts` script must compile successfully using `tsc --noEmit` under an isolated tsconfig (`playwright/tsconfig.generated.json`).
- If compilation fails, the system executes exactly one LLM self-healing compiler cycle.
- A secondary failure results in immediate escalation (preventing infinite compile loops).

### 3.3 Step 3: Sequential Execution with A11y-Powered Self-Healing
Playwright executes the compiled file using the dedicated `playwright.generated.config.ts`.
- If a timing or locator timeout failure (Category 2) is detected, the run sleeps 3.0s and retries up to 3 times.
- If an interaction-change failure (Category 6, e.g., obscured or element-not-clickable) is detected, the system extracts the failed role/name, performs dynamic A11y tree lookup, rewrites the spec file, and retries.

### 3.4 Step 4: Trace-Based Analyze Node
If execution fails after exhausted self-healing, the Trace Analyzer processes stderr/stdout logs and outputs a high-fidelity Markdown and JSON failure context report.

---

## 4. Unified Data Schema

To ensure seamless integration with the existing frontend UAT dashboards, the linear pipeline outputs are mapped directly to the common state schema:

1. **`status`**: Mapped to `"completed"` (success) or `"failed"` (execution/compilation failures).
2. **`ac_steps_total` & `ac_steps_passed`**: Derived from the step count heuristic to provide granular step-level progress on the UI dashboard.
3. **`failure_analysis`**: Saved directly into SQLite `runs` table and S3 bucket, displaying beautiful markdown failure context to QA managers.

---

## 5. Convergence Phases

*   **Phase 1: Shadow-Run Verification (Days 1-3)**
    Keep the LangGraph cyclic explorer active on production routes, but run the Linear Pipeline in shadow-mode alongside it. Compare S3 report URLs and compute empirical success rate comparisons.
*   **Phase 2: Default Switchover (Days 4-7)**
    Promote the Linear Pipeline to the default execution path in `POST /execute` and `/vc-uat`. Retain the cyclic explorer as an opt-in fallback via query parameters (`?engine=cyclic`).
*   **Phase 3: Code Consolidation & Deletion (Days 8-10)**
    After achieving 3 consecutive weeks of zero shadow-run discrepancies and ≥40% AC-item pass rate on golden benchmarks:
    - Deprecate and remove `backend/engine/graph.py` and old cyclic nodes.
    - Delete redundant selector diff utilities.
    - Consolidate S3 artifact uploads.

---

## 6. Business Alignment & Sign-off

### Value Proposition
- **93% Reduction in API Costs**: Replaces intensive, step-by-step LLM calls with a single unified generation and validation step.
- **85% Lower MTTR**: Instant failure triages and automated trace-based suggestions let developers identify and fix UI regressions in under 1 minute.
- **100% Platform Stability**: Self-contained Playwright tests compile cleanly, run sequentially, and prevent multi-user database collisions on test servers.

### PO Sign-off
- **Approved by**: _Pending Product Owner Review_
- **Date**: 2026-06-05
