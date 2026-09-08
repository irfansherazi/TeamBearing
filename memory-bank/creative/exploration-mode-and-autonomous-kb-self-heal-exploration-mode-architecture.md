# Architecture Decision: Exploration Mode & Autonomous KB Self-Heal

**Created**: 2026-05-17
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: exploration-mode-and-autonomous-kb-self-heal
**Feature**: FEAT-040

---

## Context

### System Requirements

- Introduce an **intermediate recovery tier** between the `debugger_node` one-shot and `human_takeover` escalation
- Autonomously navigate adjacent UI topology (scroll, expand accordions, click sibling tabs) to locate missing target elements
- Every successful exploration must serialize the discovered navigation pathway into a structured KB entry in `knowledge/human_guidance.md`
- Future runs must resolve the same element directly via KB retrieval — eliminating redundant exploration overhead
- No new LangGraph node additions — the graph topology in `graph.py` must remain unchanged
- All budget constants (max steps, min failure threshold, feature flag) must be configurable via environment variables

### Technical Constraints

- Must reuse the `PlaywrightContextManager` `page` reference retrieval pattern already established in `human_takeover_node`
- Must follow the `rag_debugger.py` (`RagDebugger` class) structural pattern — a standalone class with a `.should_activate()` method and a `.run()` method
- `evaluator_node` is the decision point (has full failure context: `debugger_attempted`, `action_fail_count`, `failure_diary`)
- KB injection must target `knowledge/human_guidance.md` without modifying the existing TF-IDF KB loader
- All Playwright interactions must use semantic locators (`get_by_role`, `aria-expanded`, ARIA queries) — not CSS selectors

### Non-Functional Requirements

- **Latency**: Maximum 8 additional Playwright actions per exploration episode (`EXPLORATION_MAX_STEPS=8`)
- **Observability**: All exploration steps logged with `[run_id]` prefix; `exploration_outcomes` field appended to `VQAState` for API queryability
- **Resilience**: All Playwright exceptions caught and converted to `found=False` — exploration never crashes the run
- **Cost Efficiency**: Zero LLM calls during exploration — deterministic ARIA/DOM queries only (LLM enrichment of KB entries deferred to future enhancement)
- **Deduplication**: KB injection blocked when `TRIGGER_CONDITION` already exists in `human_guidance.md`

---

## Component Analysis

### Core Components

| Component | Purpose | Responsibilities |
|-----------|---------|------------------|
| `ExplorationRunner` | Orchestrates exploration episode | `should_activate()` gate, strategy dispatch, KB injection, result assembly |
| `ScrollToRevealStrategy` | Viewport scroll recovery | Incremental `window.scrollBy(0, 300)` + element visibility check after each scroll |
| `ExpandCollapsedParentStrategy` | Accordion/panel expand | Query `aria-expanded="false"` triggers, click each, re-check target |
| `ClickSiblingTabStrategy` | Tab-panel navigation | Query `[role="tab"]` excluding active, click each, re-check target |
| `ExplorationOutcome` TypedDict | State persistence schema | Carries `ac_step_index`, `strategy_used`, `steps_taken`, `found`, `kb_injected`, `target_element`, `error_message` |
| `evaluator_node` (modified) | Activation decision point | Intercepts HITL escalation when `should_activate()=True`, merges `ExplorationOutcome` into `VQAState` |
| `reporter_node` (modified) | Audit observability | Renders `🔍 Explored` badge in step gallery + exploration summary footer |

### Component Interactions

```
evaluator_node
  └── [after debugger_attempted=True, before human_takeover]
       ├── ExplorationRunner.should_activate(state) → bool
       └── ExplorationRunner.run(page) → ExplorationResult
             ├── ScrollToRevealStrategy.execute(page, target)
             ├── ExpandCollapsedParentStrategy.execute(page, target)
             ├── ClickSiblingTabStrategy.execute(page, target)
             └── _inject_kb_entry(pathway) → writes human_guidance.md
```

---

## Options Explored

### Option A: Inline Sub-Loop in `executor_node` Failure Path

- **Description**: Add exploration directly into `executor_node`'s `_dispatch_action` failure handler, co-located with the CV Fallback Layer
- **Pros**:
  - `executor_node` already has the `page` reference
  - Follows the CV Fallback pattern (FEAT-037/computer-vision-fallback-layer-set-of-marks)
  - No evaluator changes needed
- **Cons**:
  - `executor_node` lacks strategic failure context (`debugger_attempted`, total `action_fail_count` across the episode, `failure_diary`)
  - Exploration would activate too early — before the debugger RAG has had a chance to try
  - Architecturally incorrect: the executor dispatches individual actions; it doesn't carry "should we explore?" decision logic
- **Technical Fit**: Medium
- **Complexity**: Medium
- **Scalability**: Low (mixing concerns)

### Option B: New LangGraph `exploration_node`

- **Description**: Add a dedicated `exploration_node` to the LangGraph graph, wired between `evaluator_node` and `human_takeover_node`
- **Pros**:
  - Cleanest node isolation — each node has a single responsibility
  - Independently testable as a LangGraph node
- **Cons**:
  - Requires `graph.py` rewiring — violates the "no new nodes" constraint
  - Adds LangGraph node overhead (state snapshot, routing overhead)
  - Requires routing changes in both `evaluator_node` AND new `exploration_node` → more failure surface
  - Over-engineered for what is essentially an evaluator-side sub-loop
- **Technical Fit**: Low (violates graph topology constraint)
- **Complexity**: High
- **Scalability**: High (if nodes were needed at scale)

### Option C: `ExplorationRunner` Class Called from `evaluator_node` *(Selected)*

- **Description**: A standalone `ExplorationRunner` class in `backend/engine/exploration_runner.py`, instantiated and called from `evaluator_node` at the exact branch that currently returns `{"_next_node": "human_takeover"}`. Follows the `RagDebugger` class pattern established in `backend/engine/rag_debugger.py`.
- **Architecture Diagram**:
  ```
  evaluator_node (existing)
    │
    ├── [fail_count < 3] → planner
    ├── [fail_count == 3] → debugger_node
    └── [debugger_attempted=True, fail_count >= threshold]
          ├── [NEW] ExplorationRunner.should_activate() → True
          │     └── ExplorationRunner.run(page)
          │           ├── FOUND → return {"_next_node": "planner", exploration_outcomes: [...]}
          │           └── NOT FOUND → fall through to human_takeover
          └── [EXISTING] → {"_next_node": "human_takeover"}
  ```
- **Pros**:
  - No `graph.py` changes — zero LangGraph topology impact
  - `evaluator_node` has the correct strategic context (`debugger_attempted`, `action_fail_count`, failure type)
  - Mirrors `RagDebugger` pattern exactly (`.should_activate()` + `.run()`) — consistent with codebase conventions
  - Clean separation of concerns: `ExplorationRunner` is independently unit-testable
  - `page` reference retrievable from `PlaywrightContextManager` (already done by `human_takeover_node`)
- **Cons**:
  - Evaluator grows in responsibility — must obtain `page` reference
  - Slightly more indirection than Option A
- **Technical Fit**: High
- **Complexity**: Medium
- **Scalability**: High

---

## Evaluation Matrix

| Criteria | Option A (Executor Inline) | Option B (New Node) | Option C (Runner Class) |
|----------|---------------------------|---------------------|-------------------------|
| Correct Activation Context | Low | High | **High** |
| Graph Topology Impact | None | High (violates constraint) | **None** |
| Codebase Pattern Fit | Medium | Low | **High** |
| Unit Testability | Medium | High | **High** |
| Implementation Complexity | Medium | High | **Medium** |
| Observability | Medium | High | **High** |
| **Overall** | ❌ | ❌ | ✅ |

---

## Observability Architecture

### Logging

- **Library**: Python `logging` (standard project logger), structured with `[run_id]` prefix on every entry
- **Format**: Consistent with existing vQA log patterns — `logger.info("[%s] EXPLORATION: %s", run_id, message)`
- **Log Points**:
  - `ExplorationRunner.should_activate()` — logs activation decision + reason
  - Each strategy step — logs action type, target element, outcome
  - `_inject_kb_entry()` — logs injection success or duplicate-detected
  - `ExplorationRunner.run()` catch-all — logs exception type on Playwright failure
- **Configuration**: Inherits `LOG_LEVEL` from existing environment variable (no new variables needed)

### State Observability

- `VQAState["exploration_outcomes"]` — list of `ExplorationOutcome` TypedDicts, accumulated via `operator.add` reducer
- Queryable via existing `GET /runs/{run_id}/status` endpoint (no new API surface required)

### Audit Report

- `reporter.py` renders `🔍 Explored` badge for steps where `step_type == "exploration"`
- Exploration summary footer: total exploration episodes, KB injections, success rate

### KB Observability

- Injected entries tagged with `SOURCE: exploration_auto` and `CONFIDENCE: 0.7` for human curation priority
- Deduplication guard: `TRIGGER_CONDITION` field used as dedup key in `_check_duplicate()`
- `make kb-human-sync` existing pipeline uploads updated `human_guidance.md` to Bedrock automatically

### Configuration Variables

| Variable | Purpose | Default |
|----------|---------|---------| 
| `ENABLE_EXPLORATION_MODE` | Feature flag — disable without code change | `True` |
| `EXPLORATION_MAX_STEPS` | Hard step budget per episode | `8` |
| `EXPLORATION_MIN_DOM_FAILURES` | Min `action_fail_count` before activation | `5` |

---

## Decision

**Chosen**: Option C — `ExplorationRunner` class in `backend/engine/exploration_runner.py`, called from `evaluator_node`

### Rationale

Option C is the only design that:
1. **Places the activation decision at the correct architectural tier** — the evaluator carries the strategic failure context that `should_activate()` requires (`debugger_attempted`, `action_fail_count`, failure classifier type). The executor and a new graph node both lack this.
2. **Preserves the existing LangGraph graph topology** — no `graph.py` changes, zero risk of routing regressions.
3. **Mirrors the established `RagDebugger` pattern** — the codebase already demonstrates the exact pattern (`rag_debugger.py`), reducing implementation uncertainty and ensuring consistency across the recovery tier.
4. **Maximizes unit testability** — `ExplorationRunner` is a plain Python class with mockable `page`, independently testable without LangGraph harness.

### Trade-offs Accepted

- `evaluator_node` must obtain the `page` reference — mitigated by reusing the `PlaywrightContextManager` look-up already present in `human_takeover_node` (copy existing pattern, no new infrastructure)
- KB entries are deterministically serialized (mechanical action log) rather than LLM-enriched — acceptable for MVP; richer natural-language synthesis deferred to future enhancement to keep cost predictable

---

## Implementation Guidelines

1. **File location**: `backend/engine/exploration_runner.py` — do NOT put in `backend/browser/` (browser infra) or `backend/kb/` (retrieval). This is engine-level recovery logic.
2. **Strategy registration**: Use a strategy list ordered by cost: `[ScrollToRevealStrategy, ExpandCollapsedParentStrategy, ClickSiblingTabStrategy]`. Each strategy implements `.execute(page, target) → ExplorationStepResult`.
3. **Page reference**: Retrieve from `PlaywrightContextManager.get_context(run_id).page` — the same pattern used in `human_takeover_node`. Do not pass `page` through `VQAState`.
4. **Failure type filtering in `should_activate()`**: Only activate for `TIMEOUT` and `NOT_VISIBLE` / `INVISIBLE` failure types. Do NOT activate for `AUTH_GATE_BLOCKED`, `STRICT_MODE`, `INTERCEPTED` — those are not UI-topology failures.
5. **KB entry schema**: Match the `## GUIDANCE ENTRY` heading pattern in `human_guidance.md` with required fields: `TITLE`, `KEYWORDS`, `TRIGGER_CONDITION`, `NAVIGATION_PATHWAY`, `GUIDANCE`, `SOURCE: exploration_auto`, `CONFIDENCE`, `CREATED`.
6. **No LLM calls**: Exploration is deterministic Playwright + ARIA — zero LLM invocations per episode.
7. **Exception isolation**: Every strategy call is wrapped in `try/except Exception` inside `ExplorationRunner.run()` — strategies must never crash the run.

---

## Validation Checklist

- [x] Meets all system requirements (intermediate recovery tier, KB self-heal, no graph changes)
- [x] Respects technical constraints (PlaywrightContextManager pattern, RagDebugger pattern, semantic locators)
- [x] Addresses non-functional requirements (8-step budget, observability, resilience, zero LLM cost for exploration)
- [x] Technically feasible — pattern validated against `rag_debugger.py` and `human_takeover_node.py`
- [x] Risks identified and acceptable (see Risk Assessment below)
- [x] Complies with all Guiding Principles in `systemPatterns.md`:
  - **Semantic Locators First** ✅ — `get_by_role("tab")`, `[aria-expanded="false"]`, not CSS selectors
  - **Failure Diary Pattern** ✅ — exploration steps appended to diary; pathway logged as structured entry
  - **Programmatic Tier 1 Verification** ✅ — element found = DOM presence check via Playwright, not LLM visual
  - **Config in Environment** ✅ — all thresholds via `config.py` / `.env`
  - **HITL as Learning Signal** ✅ — exploration success → KB injection → future runs self-heal
  - **12-Factor App** ✅ — all budget constants via environment variables
- [x] Observability architecture defined
- [x] No distributed tracing required — exploration is intra-process
- [x] Logging strategy: inherits project logger with `[run_id]` prefix
- [x] No new metrics defined — success rate tracked via `exploration_outcomes` in state

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Exploration activates on wrong failure type (e.g., auth failure) | Low | High | `should_activate()` checks `failure_type` allowlist: only `TIMEOUT`, `NOT_VISIBLE`, `INVISIBLE` |
| `page` reference unavailable in evaluator context | Medium | High | Reuse `PlaywrightContextManager.get_context(run_id).page` from `human_takeover_node` |
| Exploration adds latency to already-stuck steps | Medium | Medium | Hard budget cap: `EXPLORATION_MAX_STEPS=8` ≈ 8 Playwright actions max |
| KB injection creates incorrect guidance entries | Medium | Medium | `CONFIDENCE: 0.7` tag; `make kb-human-sync` review step; TF-IDF threshold filters low-quality matches |
| KB bloat from repeated failed runs | Low | Low | Only inject on `found=True`; deduplication guard prevents re-injection of same `TRIGGER_CONDITION` |
| Playwright exception inside strategy crashes run | Low | High | All strategy calls wrapped in `try/except Exception` in `ExplorationRunner.run()` |

---

## Next Steps

1. **Phase 1**: Add `ExplorationOutcome` TypedDict to `schemas.py`, add `exploration_outcomes`/`exploration_attempted` fields to `VQAState`, add config constants, create `ExplorationRunner` skeleton with `should_activate()` and stub `run()`
2. **Phase 2**: Implement `ScrollToRevealStrategy`, `ExpandCollapsedParentStrategy`, `ClickSiblingTabStrategy` inside `exploration_runner.py`; wire into `run()` dispatcher
3. **Phase 3**: Implement `_inject_kb_entry()` and `_check_duplicate()` in `ExplorationRunner`
4. **Phase 4**: Wire `ExplorationRunner` into `evaluator_node`; add `🔍 Explored` badge and summary footer to `reporter.py`
