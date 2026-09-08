---
legacy_id: exploration-mode-and-autonomous-kb-self-heal
---
# exploration-mode-and-autonomous-kb-self-heal: Exploration Mode & Autonomous KB Self-Heal

## Header

**Task ID**: exploration-mode-and-autonomous-kb-self-heal
**Title**: Exploration Mode & Autonomous KB Self-Heal
**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 4
**Roadmap Link**: FEAT-040
**Branch**: feature/FEAT-040-exploration-mode-kb-self-heal
**Created**: 2026-05-17
**Last Updated**: 2026-05-18

---

## Feature Summary

FEAT-040 introduces an intermediate **Exploration Mode** that fires between the `debugger_node` one-shot and `human_takeover` escalation. When an element cannot be found after exhausting DOM strategies, the agent autonomously navigates adjacent UI topology — scrolling, expanding accordions/panels, clicking sibling tabs — to locate the missing target. Every successful exploration serializes the discovered navigation pathway into a structured KB entry in `human_guidance.md`, enabling future runs to resolve the same element directly without exploration overhead.

---

## Specification

### Invocation Location
Exploration Mode is triggered **inside `evaluator_node`** in `backend/engine/evaluator.py`, at the exact point where the current failure chain routes to `"human_takeover"` after `debugger_attempted = True`. It is NOT a new LangGraph node — it is an inline sub-agent dispatch that runs a Playwright exploration sub-loop and returns a result that either resumes AC execution or escalates to HITL.

### Invocation Trigger (Concrete)
In `evaluator_node`, at line ~1113 (the `debugger already attempted — escalate to human` branch):
```python
# BEFORE (current):
return {"_next_node": "human_takeover", "awaiting_human_takeover": True, ...}

# AFTER (Exploration Mode intercept):
if exploration_should_activate(state):
    return await exploration_node_inline(state, run_id, page, ...)
# Else: fall through to human_takeover as before
```

### Architecture Decision: Inline vs. New LangGraph Node

**Chosen: Inline Executor-Side Recovery** (same architecture as CV Fallback Layer in FEAT-037)

| Option | Pros | Cons |
|--------|------|------|
| **A: Inline in `executor_node` failure path** | No LangGraph graph changes; follows established CV fallback pattern; stateless | Must pass `page` reference; limited step count before returning |
| **B: New LangGraph `exploration_node`** | Cleaner node isolation; easier to unit test in isolation | Requires `graph.py` rewiring; adds LangGraph node overhead; state management complexity |
| **C: New `ExplorationRunner` class called from `evaluator_node`** | Clean separation of concerns; testable; no graph rewiring; follows Debugger pattern | Slightly more indirection |

**Decision: Option C** — `ExplorationRunner` class in `backend/engine/exploration_runner.py`, called from `evaluator_node` (not executor_node). This follows the `rag_debugger.py` pattern already established in the codebase and keeps graph topology unchanged.

**Justification for evaluator (not executor) placement**: The evaluator already has the full failure context (fail counts, diary, circuit breakers fired). The executor dispatches individual actions and doesn't carry the strategic "should we explore?" context. The evaluator is the natural decision point.

### Success Path
1. `ExplorationRunner.activate()` returns `True` → exploration starts
2. Runner attempts up to `EXPLORATION_MAX_STEPS` Playwright actions (scroll, expand, tab-click)
3. Target element found → Runner injects a KB entry and returns `{"found": True, "resume_state": {...}}`
4. `evaluator_node` returns `{"_next_node": "planner", "agent_critique": "EXPLORATION SUCCEEDED — element found at [path]. KB updated.", ...}`

### Failure Path  
1. `ExplorationRunner` exhausts budget without finding target
2. Returns `{"found": False, "reason": "..."}`
3. `evaluator_node` falls through to `{"_next_node": "human_takeover", "awaiting_human_takeover": True, ...}` with exploration context appended to `agent_critique`

### Success Message (Concrete)
In execution log and audit report:
```
🔍 EXPLORATION: Scroll-to-reveal found target '[element name]' after 3 steps. KB updated with pathway: 'scroll_to_bottom → element visible'.
```

### Success Verification Location (Concrete)
- `VQAState["exploration_outcomes"]` — list of `ExplorationOutcome` dicts per episode
- HTML audit report: `🔍 Explored` step badge in the step gallery
- `knowledge/human_guidance.md` — new entry injected with `source: exploration_auto`

### Data Persistence (Concrete)
- `knowledge/human_guidance.md` — KB entries written by `ExplorationRunner._inject_kb_entry()`
- `VQAState["exploration_outcomes"]` — accumulated via LangGraph `operator.add` reducer
- `make kb-human-sync` command pushes updated `human_guidance.md` to Bedrock KB (existing pipeline, no changes)

---

## Acceptance Criteria

### AC-TRIGGER-1: Exploration activates at the correct point in the failure chain
**Priority**: MUST

**Given** an AC step that has exhausted DOM retries (debugger attempted, fail_count >= threshold)
**When** the element has NOT been found after debugger intervention
**Then** `ExplorationRunner.should_activate()` returns `True` and exploration begins instead of HITL escalation

**Verification**:
- [ ] Unit test: `should_activate()` returns True when `debugger_attempted=True AND action_fail_count >= EXPLORATION_MIN_FAILURES AND exploration_attempted=False`
- [ ] Unit test: `should_activate()` returns False when `exploration_attempted=True` (prevents re-entry)
- [ ] Unit test: `should_activate()` returns False when feature flag `ENABLE_EXPLORATION_MODE=False`

### AC-STRATEGY-1: Scroll-to-reveal strategy executes correctly
**Priority**: MUST

**Given** an element not visible in the current viewport
**When** Exploration Mode activates with scroll-to-reveal strategy
**Then** the runner scrolls the page incrementally and checks for element visibility after each scroll

**Verification**:
- [ ] Unit test: `ScrollToRevealStrategy.execute()` calls `page.evaluate("window.scrollBy(0, 300)")` up to max scroll distance
- [ ] Unit test: element found mid-scroll returns `found=True` with correct y-offset
- [ ] Unit test: exceeding scroll budget returns `found=False`

### AC-STRATEGY-2: Expand-collapsed-parent strategy executes correctly
**Priority**: MUST

**Given** an element hidden inside a collapsed accordion or panel
**When** Exploration Mode activates with expand-collapsed-parent strategy
**Then** the runner identifies and clicks candidate expand triggers, then checks for target element

**Verification**:
- [ ] Unit test: `ExpandCollapsedParentStrategy.execute()` queries `aria-expanded="false"` elements
- [ ] Unit test: clicking expand trigger re-checks target element presence
- [ ] Unit test: wrong expand trigger does not cause exception (graceful continue)

### AC-STRATEGY-3: Click-sibling-tab strategy executes correctly
**Priority**: SHOULD

**Given** an element that exists on a sibling tab not currently active
**When** Exploration Mode activates with click-sibling-tab strategy
**Then** the runner clicks each tab role element and checks for target after each click

**Verification**:
- [ ] Unit test: `ClickSiblingTabStrategy.execute()` queries `[role="tab"]` elements excluding active tab
- [ ] Unit test: target found after tab click returns `found=True` with tab name in pathway
- [ ] Unit test: all tabs exhausted without finding target returns `found=False`

### AC-KB-1: Successful exploration synthesizes and injects a KB entry
**Priority**: MUST

**Given** an exploration episode that successfully located the target element
**When** `ExplorationRunner._inject_kb_entry()` is called with the discovered pathway
**Then** a new entry is written to `knowledge/human_guidance.md` with the correct schema

**Verification**:
- [ ] Unit test: injected entry has required fields: `TITLE`, `KEYWORDS`, `GUIDANCE`, `SOURCE: exploration_auto`, `CONFIDENCE`
- [ ] Unit test: entry `TRIGGER_CONDITION` matches the failed AC step text
- [ ] Unit test: `NAVIGATION_PATHWAY` field serializes the ordered step list
- [ ] Unit test: deduplication check prevents duplicate entry when same pathway already exists in file

### AC-KB-2: Deduplication prevents KB bloat
**Priority**: MUST

**Given** the same exploration pathway has been previously injected
**When** a subsequent run discovers the same pathway
**Then** the runner detects the existing entry and skips injection (no duplicate)

**Verification**:
- [ ] Unit test: `_check_duplicate()` returns True when entry with same `TRIGGER_CONDITION` exists
- [ ] Unit test: no new entry written when duplicate detected
- [ ] Unit test: counter `exploration_kb_injections` increments only on fresh injections

### AC-BUDGET-1: Exploration respects the step budget and time limit
**Priority**: MUST

**Given** an exploration episode in progress
**When** the runner reaches `EXPLORATION_MAX_STEPS` (default: 8) without finding the target
**Then** exploration terminates and `found=False` is returned WITHOUT HITL escalation (falls through to HITL in evaluator)

**Verification**:
- [ ] Unit test: `ExplorationRunner.run()` terminates after exactly `max_steps` actions
- [ ] Unit test: no HITL flag set inside `ExplorationRunner` — HITL decision stays in evaluator
- [ ] Unit test: exploration budget consumed is logged to `exploration_outcomes` state field

### AC-STATE-1: Exploration outcomes are persisted to VQAState
**Priority**: MUST

**Given** a completed exploration episode (success or failure)
**When** `evaluator_node` merges the exploration result into state
**Then** `exploration_outcomes` accumulates via `operator.add` reducer

**Verification**:
- [ ] Unit test: `ExplorationOutcome` TypedDict has required fields: `ac_step_index`, `strategy_used`, `steps_taken`, `found`, `kb_injected`, `target_element`
- [ ] Unit test: LangGraph reducer does not overwrite previous episodes

### AC-REPORT-1: Exploration steps appear in the HTML audit report
**Priority**: SHOULD

**Given** a run with at least one exploration episode
**When** the `reporter_node` generates the HTML audit report
**Then** exploration steps display a distinct `🔍 Explored` badge in the step gallery

**Verification**:
- [ ] Unit test: `reporter.py` renders `🔍 Explored` badge when `step_type == "exploration"`
- [ ] Unit test: exploration summary footer shows invocation count and KB injection count
- [ ] Integration: exploration badge visible in generated HTML (manual review)

### AC-ERROR-1: Exploration failure does not crash the run
**Priority**: MUST

**Given** an exploration episode where a Playwright call raises an exception
**When** the exception is not caught inside the strategy
**Then** `ExplorationRunner` catches all exceptions, logs them, and returns `found=False` gracefully

**Verification**:
- [ ] Unit test: `ExplorationRunner.run()` wraps strategy calls in try/except
- [ ] Unit test: `TimeoutError` from Playwright returns `found=False` without re-raising
- [ ] Unit test: exploration exception is logged to `exploration_outcomes[*].error_message`

---

## Codebase Analysis

### Integration Points (from systemPatterns.md + codebase scan)

| Component | Location | Change Type |
|-----------|----------|-------------|
| `evaluator_node` | `backend/engine/evaluator.py` L1107–1120 | **MODIFY** — add `ExplorationRunner` intercept before HITL |
| `VQAState` | `backend/engine/state.py` | **MODIFY** — add `exploration_outcomes`, `exploration_attempted` fields |
| `ExplorationRunner` | `backend/engine/exploration_runner.py` | **NEW** — core exploration logic |
| `reporter.py` | `backend/engine/reporter.py` | **MODIFY** — render `🔍 Explored` badge + summary footer |
| `human_guidance.md` | `knowledge/human_guidance.md` | **MODIFIED AT RUNTIME** — KB entries injected by runner |
| `config.py` | `backend/config.py` | **MODIFY** — `ENABLE_EXPLORATION_MODE` flag + budget constants |
| `schemas.py` | `backend/engine/schemas.py` | **MODIFY** — `ExplorationOutcome` TypedDict |

### Guiding Principles Validation

| Principle | Compliance |
|-----------|-----------|
| **Multimodal Grounding** | ✅ Exploration uses ARIA tree queries for element detection, not visual-only |
| **Semantic Locators First** | ✅ Runner uses `get_by_role("tab")`, `[aria-expanded="false"]` — not CSS selectors |
| **Failure Diary Pattern** | ✅ Exploration steps appended to existing diary; pathway logged as structured entry |
| **Programmatic Tier 1 Verification** | ✅ Element found = DOM presence check via Playwright, not LLM visual |
| **Config in Environment** | ✅ All thresholds via `config.py` / `.env` (ENABLE_EXPLORATION_MODE, EXPLORATION_MAX_STEPS) |
| **HITL as Learning Signal** | ✅ Exploration success → KB injection → future runs self-heal without HITL |
| **12-Factor App** | ✅ All budget constants configurable via environment variables |

### Failure Chain After This Feature (Concrete)

```
planner_node → executor_node → evaluator_node
    ├── fail_count < 3:  → planner (retry with new strategy)
    ├── fail_count == 3: → debugger_node (RAG-informed fix) 
    │       └── debugger_attempted=True, fail_count >= threshold:
    │               ├── [NEW] ExplorationRunner.should_activate() → True
    │               │       ├── exploration FOUND element → resume → planner
    │               │       └── exploration FAILED → fall through to HITL ↓
    │               └── [EXISTING] → human_takeover
    └── [other circuits] → human_takeover / reporter
```

### Architecture Alternatives Explored

**A1: Where to intercept — executor_node vs evaluator_node**
- Executor has `page` reference (needed for Playwright) but lacks strategic failure context
- Evaluator has full context but needs `page` reference injection
- **Decision**: `evaluator_node` intercept. The `page` object can be retrieved from the `browser_context` via `state["run_id"]` look-up in the `PlaywrightContextManager` (already used by human_takeover_node)

**A2: LLM-synthesized KB entry vs. deterministic action log serialization**
- LLM synthesis: richer natural-language entries, but adds LLM cost per exploration success
- Deterministic: zero LLM cost, but entries are mechanical and harder for RAG to score
- **Decision**: Deterministic serialization for Phase 3 (MVP). LLM enrichment deferred to a future enhancement to keep cost predictable.

**A3: KB injection target — human_guidance.md vs. new exploration_guidance.md file**
- Separate file: clean separation; easy to audit; requires KB loader changes
- Same file: zero loader changes; immediately consumed by TF-IDF RAG (already indexes human_guidance.md)
- **Decision**: Inject into `human_guidance.md` with `SOURCE: exploration_auto` tag for auditability. Existing `make kb-human-sync` pipeline handles Bedrock upload automatically.

### Observability Requirements

- **Logging**: All exploration steps logged via `logger.info/warning` with `[run_id]` prefix
- **State Observability**: `exploration_outcomes` list in `VQAState` queryable via `GET /status/{run_id}`
- **Audit Report**: `🔍 Explored` step badge; exploration summary footer in HTML report
- **KB Observability**: `SOURCE: exploration_auto` tag in `human_guidance.md` entries; `CONFIDENCE` field for curation priority
- **No new API endpoints required** — exploration is fully internal to the engine

### API Requirements
- **No REST API changes** — exploration is entirely engine-internal
- **No GraphQL changes** — N/A
- **No WebSocket protocol changes** — exploration log steps streamed as normal `ExecutionStep` events

---

## Implementation Roadmap

### Phase 1: State Machine & Configuration (Foundation)
**Goal**: All state schema changes + feature flag + VQAState fields; zero behavior change

**Files**:
- `backend/engine/state.py` — add `exploration_outcomes: list[ExplorationOutcome]`, `exploration_attempted: bool`
- `backend/engine/schemas.py` — add `ExplorationOutcome` TypedDict
- `backend/config.py` — add `ENABLE_EXPLORATION_MODE: bool = True`, `EXPLORATION_MAX_STEPS: int = 8`, `EXPLORATION_MIN_DOM_FAILURES: int = 5`
- `backend/engine/exploration_runner.py` — create skeleton `ExplorationRunner` class with `should_activate()` and stub `run()` method

**Tests**:
- `tests/test_exploration_state_machine.py` — AC-TRIGGER-1 (should_activate logic), AC-STATE-1 (TypedDict structure)

**Verification Gate**: `pytest tests/test_exploration_state_machine.py -v` passes (all unit tests green)

---

### Phase 2: Exploration Executor (Strategies)
**Goal**: Implement three Playwright-backed exploration strategies

**Files**:
- `backend/engine/exploration_runner.py` — implement `ScrollToRevealStrategy`, `ExpandCollapsedParentStrategy`, `ClickSiblingTabStrategy`; wire into `ExplorationRunner.run()` dispatcher

**Tests**:
- `tests/test_exploration_strategies.py` — AC-STRATEGY-1, AC-STRATEGY-2, AC-STRATEGY-3, AC-BUDGET-1, AC-ERROR-1

**Strategy Execution Order** (configurable):
1. `scroll_to_reveal` — lowest cost; handles off-screen elements
2. `expand_collapsed_parent` — medium cost; handles accordion/panel hiding
3. `click_sibling_tab` — medium cost; handles tab-panel hiding

**Verification Gate**: `pytest tests/test_exploration_strategies.py -v` passes

---

### Phase 3: KB Injection & Deduplication
**Goal**: Synthesize and inject pathway entries into `human_guidance.md` on success

**Files**:
- `backend/engine/exploration_runner.py` — implement `_inject_kb_entry()` and `_check_duplicate()`
- `knowledge/human_guidance.md` — runtime target (no code changes to the file itself)

**KB Entry Schema** (injected at runtime):
```markdown
## EXPLORATION AUTO-LEARN: [target_element]

TITLE: Navigate to [target_element] via [strategy_name]
KEYWORDS: [element_name, page_context, strategy_name]
TRIGGER_CONDITION: [ac_step_text_that_triggered_exploration]
NAVIGATION_PATHWAY:
  1. [action_1] → [observation_1]
  2. [action_2] → [observation_2]
GUIDANCE: When [target_element] is not visible, [strategy_name] was used to locate it.
SOURCE: exploration_auto
CONFIDENCE: 0.7
CREATED: [timestamp]
```

**Tests**:
- `tests/test_exploration_kb_injection.py` — AC-KB-1, AC-KB-2

**Verification Gate**: `pytest tests/test_exploration_kb_injection.py -v` passes

---

### Phase 4: Reporter Integration + Evaluator Wiring
**Goal**: Wire `ExplorationRunner` into `evaluator_node`; render in HTML report

**Files**:
- `backend/engine/evaluator.py` — add `ExplorationRunner` intercept at L1107 (after `debugger_attempted` check)
- `backend/engine/reporter.py` — render `🔍 Explored` badge + exploration summary footer

**Evaluator wiring (concrete)**:
```python
# evaluator_node, after debugger_attempted check, before human_takeover return
from backend.engine.exploration_runner import ExplorationRunner
_explorer = ExplorationRunner(state=state, run_id=run_id)
if await _explorer.should_activate():
    _result = await _explorer.run(page=_page_ref)
    if _result["found"]:
        return {
            "_next_node": "planner",
            "exploration_attempted": True,
            "exploration_outcomes": [_result["outcome"]],
            "agent_critique": f"🔍 EXPLORATION SUCCEEDED: {_result['pathway_summary']}. KB updated.",
            "retry_count": 0,
            "last_error": "",
        }
    # Exploration failed — fall through to HITL with exploration context
    exploration_context = f"🔍 EXPLORATION FAILED: {_result['reason']}. "
```

**Tests**:
- `tests/test_exploration_reporter.py` — AC-REPORT-1
- `tests/test_exploration_evaluator_integration.py` — end-to-end evaluator wiring with mocked ExplorationRunner

**Verification Gate**: `pytest tests/ -v -k exploration` passes (all exploration tests green, no regressions)

---

## Test Strategy

| Test File | Coverage | Type |
|-----------|----------|------|
| `tests/test_exploration_state_machine.py` | AC-TRIGGER-1, AC-STATE-1 | Unit |
| `tests/test_exploration_strategies.py` | AC-STRATEGY-1/2/3, AC-BUDGET-1, AC-ERROR-1 | Unit |
| `tests/test_exploration_kb_injection.py` | AC-KB-1, AC-KB-2 | Unit |
| `tests/test_exploration_reporter.py` | AC-REPORT-1 | Unit |
| `tests/test_exploration_evaluator_integration.py` | Full evaluator integration | Unit (mocked) |

**Mocking Approach** (consistent with existing test patterns):
- `page` object: `MagicMock()` with async `evaluate()`, `query_selector_all()`, `get_by_role()` methods
- `human_guidance.md`: `tmp_path` fixture for KB injection tests
- `VQAState`: dict-based construction (standard pattern)
- **No live browser or Bedrock calls in any test**

---

## Creative Phases Required

- [x] **Architecture Design** — COMPLETE. Option C (`ExplorationRunner` class in `evaluator_node`) selected. Document: `memory-bank/creative/exploration-mode-and-autonomous-kb-self-heal-exploration-mode-architecture.md`
- [x] **User Journey Design** — N/A (deferred). Exploration Mode is engine-internal; no direct user-facing journey. Reporter badge is the only user-visible surface.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Exploration adds latency to already-stuck steps | Medium | Medium | Hard budget cap: `EXPLORATION_MAX_STEPS=8` ≈ 8 Playwright actions max |
| KB injection creates incorrect guidance entries | Medium | Medium | `CONFIDENCE: 0.7` tag; curation step via `make kb-human-sync` review; TF-IDF threshold filters low-quality matches |
| Exploration strategy activates on wrong failure type (e.g., auth failure) | Low | High | `should_activate()` checks failure type: only activates on `TIMEOUT` and `NOT_VISIBLE` failures, NOT `AUTH_GATE_BLOCKED`, `STRICT_MODE`, `INTERCEPTED` |
| `page` reference unavailable in evaluator context | Medium | High | Solved by reusing PlaywrightContextManager look-up pattern from human_takeover_node |
| KB bloat from failed explorations | Low | Low | Only inject on `found=True`; deduplication guard prevents re-injection |

---

## Success Metrics (from FEAT-040)

- ≥ 70% of "element not found" escalations resolved by Exploration Mode without HITL
- KB self-heal injection rate ≥ 60% of successful explorations (pathway injected and verified on re-run)
- HITL escalation rate reduction ≥ 40% compared to current baseline
- Exploration overhead ≤ 8 additional steps per episode

---

## Execution State

**Build Status**: ARCHIVED
**Current Phase**: COMPLETE
**Phase Number**: 4 of 4
**Is Multi-Phase**: YES
**Build Started**: 2026-05-17T22:16:00Z
**Phase 4 Completed**: 2026-05-18T01:33:00Z
**Archived**: 2026-05-18
**Can Resume**: NO

**Phase 4 Summary**:
- 2 files modified: `evaluator.py` (+90 lines: ExplorationRunner intercept at HITL branch), `reporter.py` (+75 lines: _render_exploration_summary, badge, CSS)
- 2 test files created: `test_exploration_evaluator_integration.py` (11 tests), `test_exploration_reporter.py` (10 tests — 9 existing + 1 refactored)
- 20 new Phase 4 tests, all passing (20/20 ✅)
- `evaluator.py` — ExplorationRunner intercept: on success routes to planner with 🔍 EXPLORATION SUCCEEDED critique + exploration_outcomes; on failure routes to human_takeover with 🔍 EXPLORATION FAILED prefix; never raises to caller (wrapped in try/except)
- `reporter.py` — _render_execution_log: 🔍 Explored badge for step_type=='exploration'; _render_exploration_summary: episode count, KB injection count, per-episode table; wired into _render_full_report after recovery log
- Full regression suite: 367/367 ✅ (21 new tests, 0 regressions)
- Commit: 6cce722

**Phase 3 Summary**:
- 1 file modified: `exploration_runner.py` (+170 lines: _inject_kb_entry, _check_duplicate, _get_trigger_condition, _kb_path)
- 1 test file created: `test_exploration_kb_injection.py`
- 18 new tests, all passing (18/18 ✅)
- Full regression suite: 346/346 ✅ (no regressions)
- Commit: d98b9f8 | Pushed to remote

**Phase 2 Summary**:
- 1 file heavily modified: `exploration_runner.py` (+1173 lines)
- 1 test file created: `test_exploration_strategies.py`
- 22 new tests, all passing (22/22 ✅)
- Full regression suite: 329/329 ✅ (no regressions)
- Commit: 391420d | Pushed to remote

**Phase 1 Summary**:
- 4 files modified/created: `exploration_runner.py`, `schemas.py`, `config.py`, `state.py`
- 27 tests written and passing (27/27 ✅)
- Full regression suite: 299/299 ✅ (no regressions)

### Completed Phases
- [x] PLAN — Spec written, architecture decided, AC defined
- [x] CREATIVE — Architecture document written: `memory-bank/creative/exploration-mode-and-autonomous-kb-self-heal-exploration-mode-architecture.md`

### Creative Phases
- [x] Architecture Design — COMPLETE (2026-05-17). Option C selected: `ExplorationRunner` class in `evaluator_node`. Doc: `memory-bank/creative/exploration-mode-and-autonomous-kb-self-heal-exploration-mode-architecture.md`
- [x] User Journey Design — N/A (deferred; engine-internal feature, no user-facing flow)

### Build Phases
- [x] Phase 1: State Machine & Configuration
- [x] Phase 2: Exploration Executor (Strategies)
- [x] Phase 3: KB Injection & Deduplication
- [x] Phase 4: Reporter Integration + Evaluator Wiring

### Post-Build
- [x] Reflect — COMPLETE (2026-05-18). Document: `memory-bank/reflection/reflection-exploration-mode-and-autonomous-kb-self-heal.md`
- [x] Archive — COMPLETE (2026-05-18). Document: `memory-bank/archive/archive-exploration-mode-and-autonomous-kb-self-heal.md`
