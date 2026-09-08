---
legacy_id: computer-vision-fallback-layer-set-of-marks
---
# computer-vision-fallback-layer-set-of-marks: Computer Vision Fallback Layer (Set-of-Marks)

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 4
**Roadmap Link**: FEAT-037
**Branch**: feature/FEAT-037-cv-fallback-som
**Created**: 2026-05-17
**Archived**: 2026-05-17

---

## Executive Summary

Introduce a pure Computer Vision (CV) fallback layer that activates when the standard DOM/ARIA resolution chain is exhausted — covering PrimeNG components with obfuscated ARIA trees, dynamic Canvas rendering, and Shadow DOM elements with no accessible locator. The mechanism captures a Playwright screenshot, overlays a Set-of-Marks (SoM) coordinate grid, sends the annotated image to a vision LLM, receives a `mark_id` in response, maps it back to exact viewport X,Y coordinates, and fires `page.mouse.click(x, y)` — completely bypassing DOM access.

**Key insight from codebase analysis**: The infrastructure for this feature is **substantially already built**:
- `backend/browser/vision_utils.py` — `draw_marks_and_snapshot()` produces the coordinate map; `format_vision_mark_summary()` formats the prompt block
- `backend/browser/set_of_marks.py` — `capture_set_of_marks()` produces the CSS-selector map; `should_activate_som()` is the existing DOM-SoM trigger
- `backend/engine/executor.py` — `coordinate_action` dispatcher resolves `mark_id → (x, y)` coordinates and fires `page.mouse.click()` with CSS fallback
- `backend/engine/executor.py` line 2681-2690 — SoM element map is already resolved in the executor main path

What **does not yet exist**:
1. A **CV-specific fallback path** that activates _after_ DOM failure (not as a planner-side mode, but as an executor-side recovery)
2. A **vision LLM call** that takes the annotated screenshot and the target description and returns a `mark_id` (the existing SoM always routes via the planner)
3. A **cost gate** that prevents vision calls on every step — only invokes after N DOM failures
4. A **verifier adaptation** for post-coordinate-click assertions
5. A **KB recipe** that teaches the planner to declare `cv_fallback_eligible: true` on steps targeting Shadow DOM / Canvas elements
6. **Unit tests** for the CV fallback path (cost gate, resolution, failure modes)

This task implements those four missing pieces as four sequential phases.

---

## Business Context

vQA's mission is to reduce HITL escalation to zero for any element class. Shadow DOM, Canvas, and iFrame-hosted elements represent a structural gap: the agent has no DOM path to click them. Today, every such element escalates to HITL after exhausting retry budget. With the CV fallback layer:
- **QA Lead**: No more HITL escalations for UI components the DOM can't reach
- **PM**: Canvas dashboards, embedded iFrame widgets, and web-component ports become testable without script authoring
- **Release Engineer**: CI/CD gates can cover the full surface area — including novel UI patterns introduced by design sprints

**Cost justification**: Vision invocation (Claude 3.5 Sonnet) is ~$0.003/image at 1024px. At ≤5% of steps, on a 30-step test run, this adds ≤$0.005/run — negligible against the cost of a HITL session.

---

## Vision and Goals

- **Vision**: Make every visible UI element in vSuite clickable by vQA, regardless of DOM accessibility — zero structural blind spots.
- **Goals**:
  1. Zero HITL escalations caused by Shadow DOM / Canvas element inaccessibility
  2. Vision invocation rate ≤ 5% of total steps (cost efficiency preserved)
  3. Coordinate-click success rate ≥ 85% on first CV attempt
  4. Total cost increase ≤ $0.01/run against current baseline

---

## Specification

### Feature Overview

The CV Fallback Layer is a **post-failure executor recovery path** — not a new planner mode. It sits between the standard failure-aware recovery router and HITL escalation in the executor chain.

### Invocation Location

**Where it activates**: Inside `executor.py`'s `_dispatch_action()` function, within the existing failure handling block, **after** the failure-aware recovery router has been exhausted and **before** `human_takeover_node` escalation. Specifically, when `evaluator.py` calls the executor on a step that has already failed N times and the failure type is `STRICT_MODE`, `NOT_VISIBLE`, `DETACHED`, or `STALE_LOCATOR`.

**Trigger condition**: `cv_fallback_enabled` config flag is True AND `ac_step_action_fail_count >= CV_FALLBACK_MIN_DOM_FAILURES` (configurable, default: 3) AND action type is `click` or `coordinate_action`.

### Success Verification

**Success path**: After the CV fallback fires a `page.mouse.click(x, y)`, the verifier checks for DOM state change (element count delta, URL change, or ARIA snapshot diff) within 2 seconds. If any of these changes, the step is marked `CV_CLICK_SUCCESS` and the run advances to the next AC step.

**Failure path**: If no DOM state change is detected within 2 seconds, the step is marked `CV_CLICK_FAILED` and escalates to HITL as normal.

### Data Persistence

- `VQAState.cv_fallback_invocations` — rolling count of CV calls in this run
- `VQAState.cv_fallback_results` — list of `{step_idx, mark_id, x, y, success, cost_estimate}` entries
- These are emitted in the HTML audit report's per-step diagnostics as `CV_FALLBACK` tagged rows

### Acceptance Criteria

#### AC-ENTRY-1: CV Fallback activates on exhausted DOM failures
**Priority**: MUST

**Given** a run where an AC step has failed 3+ consecutive times with `STRICT_MODE` / `NOT_VISIBLE` / `DETACHED` failure type
**When** the executor receives the next retry for that step
**Then**:
- The executor captures a SoM-annotated screenshot via `vision_utils.draw_marks_and_snapshot()`
- Sends it with the step's target description to the vision LLM
- Receives a `mark_id` response
- Maps `mark_id → (x, y)` via `mark_coordinate_map`
- Fires `page.mouse.click(x, y)`
- Logs the result with tag `CV_FALLBACK`

**Verification**:
- [ ] Unit test: mock DOM failures → CV path activates at threshold N
- [ ] Unit test: mock vision LLM response → executor fires coordinate click

#### AC-HAPPY-1: Successful CV click advances AC step
**Priority**: MUST

**Given** the CV fallback fires a coordinate click
**When** the post-click DOM state changes (URL change, ARIA diff, or element count delta)
**Then**:
- Step is marked `CV_CLICK_SUCCESS`
- Run advances to next AC step
- Audit log row contains `"cv_fallback": true, "mark_id": <N>, "coords": {x, y}`

**Verification**:
- [ ] Unit test: mock post-click state change → step advances
- [ ] Integration: CV fallback successfully clicks a `<canvas>` element

#### AC-ENTRY-2: Cost gate prevents premature vision calls
**Priority**: MUST

**Given** an AC step that has only failed 1–2 times (below threshold)
**When** the executor processes the failure
**Then** the CV fallback does NOT activate (standard retry chain runs instead)

**Verification**:
- [ ] Unit test: fail_count=1 → no CV call
- [ ] Unit test: fail_count=3 → CV call fires

#### AC-ERROR-1: Vision LLM returns no valid mark_id
**Priority**: MUST

**Given** the CV fallback fires and the vision LLM cannot identify the target
**When** the LLM response contains no valid `mark_id` or returns `mark_id: null`
**Then**:
- Step is NOT marked as failed due to vision failure
- Instead, the agent escalates to HITL with context `"CV_FALLBACK_RESOLUTION_FAILED"`
- Audit log contains `"cv_fallback_attempted": true, "cv_resolution": "FAILED"`

**Verification**:
- [ ] Unit test: vision LLM returns null → HITL escalation with correct context

#### AC-HAPPY-2: KB recipe enables proactive CV declaration
**Priority**: SHOULD

**Given** a planner that encounters a Canvas or Shadow DOM element in a Jira AC step
**When** the KB recipe `cv_fallback.yaml` is retrieved
**Then** the planner emits `"cv_fallback_eligible": true` on the action, which the executor uses to lower the failure threshold from 3 to 1 for that specific action

**Verification**:
- [ ] KB recipe file exists at `knowledge/blueprints/cv_fallback.yaml`
- [ ] Unit test: `cv_fallback_eligible=True` → threshold=1

#### AC-ASYNC-1: CV fallback results visible in audit report
**Priority**: SHOULD

**Given** a run where CV fallback was invoked
**When** the HTML audit report is generated
**Then**:
- Each CV fallback step is tagged with a `🎯 CV Fallback` badge
- The step detail shows `mark_id`, coordinates, and `success/failed` verdict

**Verification**:
- [ ] Reporter generates CV_FALLBACK badge in HTML
- [ ] Badge visible in Playwright screenshot of audit report

---

## Architectural Principles

1. **Executor-Side Recovery, Not Planner-Side Mode** — CV fallback is a recovery path in the executor, not a new planner vision mode. The planner never changes its action format; only the executor changes how it handles failures.
2. **Cost Gate is Non-Negotiable** — Vision LLM calls are always gated behind `ac_step_action_fail_count >= threshold`. Never invoke on first attempt.
3. **Stateless Vision Call** — The vision LLM call is stateless: one screenshot in, one `mark_id` out. It does not share context with the main planner session.
4. **Dual-Resolution Preserved** — The existing coordinate drift fallback (CSS selector backup in `mark_coordinate_map`) is preserved and applies to CV-initiated clicks too.
5. **Observability by Default** — Every CV fallback invocation is logged with `run_id`, `step_idx`, `mark_id`, `(x,y)`, `cost_estimate`, and `success`.

---

## Architecture Alternatives

### Option A: Executor-Side Recovery Path (Selected)
CV fallback is a self-contained recovery triggered inside the executor after DOM failures are exhausted, before HITL escalation.

**Pros**: Zero changes to planner/evaluator routing; clean separation of concerns; cost gate is enforceable at the executor level; existing `coordinate_action` path is reused.

**Cons**: Evaluator doesn't know CV was attempted (needs state update); slightly harder to gate by failure type without evaluator refactor.

### Option B: New Evaluator Route (`cv_fallback_node`)
Evaluator routes to a new `cv_fallback_node` before `human_takeover_node`.

**Pros**: Full visibility in the LangGraph node graph; cleaner state management.

**Cons**: Requires LangGraph node addition + routing changes; higher risk of graph recursion issues given fix-graphrecursionerror-recursion-limit-too-low-for-node-vis history; more complex rollout.

### Option C: Planner-Side Vision Mode Upgrade
Extend the existing `should_activate_som()` to use the vision LLM call in the planner loop.

**Pros**: Planner already has SoM context; natural extension.

**Cons**: Planner already runs the vision LLM (Claude Sonnet) — adding a second vision call for element resolution doubles cost per iteration; not scoped as a fallback.

**Decision**: Option A selected. Minimal surface area change, reuses the full existing coordinate resolution stack, preserves the evaluator routing graph unchanged, and can be feature-flagged at the config level.

---

## Observability Requirements

**Logging**:
- `CV_FALLBACK_ACTIVATED`: step_idx, fail_count, threshold, reason
- `CV_FALLBACK_VISION_CALL`: run_id, mark_id returned, cost_estimate, latency_ms
- `CV_FALLBACK_CLICK`: mark_id, x, y, success
- `CV_FALLBACK_STATE_CHANGE`: what changed (URL, ARIA, element_count)
- `CV_FALLBACK_RESOLUTION_FAILED`: reason (LLM returned null, mark_id not in map, out-of-viewport)

**Metrics (existing log patterns)**:
- `cv_fallback_invocation_count` (per run, emitted in reporter)
- `cv_fallback_success_rate` (per run)
- `cv_fallback_cost_usd` (per run, estimated at $0.003/image)

**Audit Report**:
- Per-step `"cv_fallback"` field in the step JSON
- HTML badge: `🎯 CV Fallback` on steps where it activated

---

## API Requirements

- **No new REST endpoints** — CV fallback is fully internal to the executor
- **VQAState schema changes** (see Phase 1): `cv_fallback_invocations: int`, `cv_fallback_results: list[dict]`
- **Config additions** (see Phase 1): `CV_FALLBACK_ENABLED`, `CV_FALLBACK_MIN_DOM_FAILURES`

---

## Creative Phases Required

- [x] Architecture Design — COMPLETE: `memory-bank/creative/computer-vision-fallback-layer-set-of-marks-cv-fallback-architecture.md` (2026-05-17)
- [x] User Journey Design — N/A (internal engine feature, no end-user UI flow)
- [x] UI/UX Design — N/A (audit report badge is the only UI touch; covered in Phase 4)
- [x] Algorithm Design — N/A (Phase 1 includes the cost gate formula; no separate creative phase needed)

---

## Implementation Roadmap

### Phase 1: Config, State Schema & Cost Gate ✅ COMPLETE (2026-05-17)
**Goal**: Add feature flag, cost gate logic, and VQAState fields. No behavioral change yet.

**Files**:
- `backend/engine/config.py` — Add `CV_FALLBACK_ENABLED` (default: True), `CV_FALLBACK_MIN_DOM_FAILURES` (default: 3)
- `backend/engine/state.py` — Add `cv_fallback_invocations: int = 0`, `cv_fallback_results: Annotated[list, operator.add] = []`
- `backend/browser/cv_resolver.py` — **New file**: `CvFallbackResolver` class with `should_activate(state, action) -> bool` cost gate, `resolve(page, target_description, mark_map) -> int | None` vision LLM call, `estimate_cost() -> float`
- `tests/test_cv_fallback_cost_gate.py` — Unit tests for cost gate threshold logic

**Milestone**: `should_activate()` returns correct bool at all fail count thresholds; VQAState serializes cleanly.

**Verification gate**: `pytest tests/test_cv_fallback_cost_gate.py -v` — all tests pass.

---

### Phase 2: Vision LLM Resolver & Executor Integration ✅ COMPLETE (2026-05-17)
**Goal**: Wire `CvFallbackResolver.resolve()` into the executor's failure path, replacing the HITL escalation for eligible failure types.

**Files**:
- `backend/browser/cv_resolver.py` — Implement `resolve()`: call `draw_marks_and_snapshot()`, build the vision prompt, invoke Claude 3.5 Sonnet (vision), parse `mark_id` from JSON response
- `backend/engine/executor.py` — In `_dispatch_action()` failure path: after standard recovery chain returns `success=False`, check `should_activate()`, call `resolve()`, map `mark_id → (x, y)`, fire `page.mouse.click(x, y)`, update `cv_fallback_results` in state
- `tests/test_cv_fallback_resolver.py` — Unit tests for resolver: mock vision LLM, mock screenshot, verify mark_id extraction and click dispatch

**Milestone**: `coordinate_action` path reachable via CV fallback with mocked vision LLM response; executor logs `CV_FALLBACK_ACTIVATED`.

**Verification gate**: `pytest tests/test_cv_fallback_resolver.py -v` — all tests pass.

---

### Phase 3: Verifier Adaptation & State Change Detection ✅ COMPLETE (2026-05-17)
**Goal**: Teach the verifier to handle post-coordinate-click assertions and confirm state change after CV fallback clicks.

**Files**:
- `backend/engine/verifier.py` — Add `cv_fallback_state_change_check(page, pre_state_snapshot) -> bool`: captures ARIA snapshot before click, re-checks 2s after, returns True if URL, element count, or ARIA diff detected
- `backend/engine/executor.py` — After CV fallback click: call `cv_fallback_state_change_check()`, set `success=True` if state changed, else mark `CV_CLICK_FAILED` and escalate
- `tests/test_cv_fallback_verifier.py` — Unit tests for state change detection logic

**Milestone**: CV fallback click marked `SUCCESS` when DOM changes, `FAILED` when it doesn't, HITL escalation carries CV context.

**Verification gate**: `pytest tests/test_cv_fallback_verifier.py -v` — all tests pass.

---

### Phase 4: KB Recipe & Audit Report Integration ✅ COMPLETE (2026-05-17)
**Goal**: Add the proactive CV declaration blueprint and surface CV fallback events in the HTML audit report.

**Files**:
- `knowledge/blueprints/cv_fallback.yaml` — New KB recipe: `name: cv_fallback`, `description: "Use for Canvas, Shadow DOM, or iFrame elements that have no accessible DOM locator"`, `steps: [{action: coordinate_action, cv_fallback_eligible: true}]`
- `backend/engine/reporter.py` — In HTML step row generation: if `step.get("cv_fallback")`, add `🎯 CV Fallback` badge to step HTML; add `cv_fallback_summary` section to report footer with invocation count, success rate, estimated cost
- `tests/test_cv_fallback_reporter.py` — Unit test: mock state with CV results → verify HTML contains badge

**Milestone**: CV fallback fully integrated end-to-end; KB recipe discoverable; audit report shows CV events.

**Verification gate**: `pytest tests/test_cv_fallback_reporter.py -v` — all tests pass; full test suite `pytest tests/ -v` passes with no regressions.

---

## Test Strategy

| Test File | Scope | What It Validates |
|-----------|-------|-------------------|
| `tests/test_cv_fallback_cost_gate.py` | Unit | Threshold logic, fail_count gate, `cv_fallback_eligible` override |
| `tests/test_cv_fallback_resolver.py` | Unit | Vision LLM invocation (mocked), mark_id parsing, executor integration |
| `tests/test_cv_fallback_verifier.py` | Unit | State change detection (URL, ARIA, element count) |
| `tests/test_cv_fallback_reporter.py` | Unit | HTML badge generation, summary footer |

**No integration tests against live browser/AWS** — consistent with `systemPatterns.md` testing philosophy (mock external dependencies).

**Regression guard**: Full `pytest tests/ -v` run after each phase to ensure zero regressions against existing 38+ test cases.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Vision LLM hallucinates mark_id outside map range | Medium | Medium | Validate mark_id is in `mark_coordinate_map` before click; reject gracefully |
| Coordinate drift between snapshot and click | Low | Low | Existing CSS fallback in `mark_coordinate_map` entry handles this |
| Cost gate bypass — CV fires on every step | Low | High | `CV_FALLBACK_ENABLED` feature flag + threshold guard tested in Phase 1 |
| Canvas element center coordinates wrong | Medium | Medium | `vision_utils.py` uses `getBoundingClientRect()` which is accurate for Canvas |
| Shadow DOM element not captured by SoM overlay | Low | Medium | SoM JS iterates all `interactive_selector` which includes generic `[role=button]` — Shadow DOM is pierced by Playwright's element queries but not standard `querySelectorAll`; document this limitation |

---

## Guiding Principles Alignment

| Principle | Alignment |
|-----------|-----------|
| **Multimodal Grounding** | ✅ CV fallback adds a third sensory mode: screenshot → vision LLM when DOM+ARIA fail |
| **Programmatic Tier 1 Verification** | ✅ CV fallback is Tier 3 (after DOM checks exhausted); DOM remains Tier 1 |
| **Failure Diary Pattern** | ✅ `cv_fallback_results` extends the existing failure diary concept to CV attempts |
| **Config in Environment** | ✅ `CV_FALLBACK_ENABLED` and `CV_FALLBACK_MIN_DOM_FAILURES` via `config.py` / `.env` |
| **HITL as Learning Signal** | ✅ When CV also fails, HITL fires with richer context (`CV_FALLBACK_RESOLUTION_FAILED`) |

---

## Execution State

**Build Status**: COMPLETE
**Phase Being Built**: N/A
**Phase Number**: N/A
**Is Multi-Phase**: YES
**Build Started**: 2026-05-17T08:27:00-05:00
**Phase 1 Completed**: 2026-05-17T08:30:09-05:00
**Phase 2 Completed**: 2026-05-17T08:59:00-05:00
**Phase 3 Completed**: 2026-05-17T10:54:00-05:00
**Phase 4 Completed**: 2026-05-17T13:48:00-05:00
**Reflection Completed**: 2026-05-17T13:58:00-05:00
**Archive Completed**: 2026-05-17T14:05:00-05:00
**Current Build Step**:
  Step: Archive — COMPLETE
  Status: IDLE

**Worktree**: `.worktrees/FEAT-037`
**Branch**: `feature/FEAT-037-cv-fallback-som`
**Can Resume**: NO — Task COMPLETE. Archive at `memory-bank/archive/archive-computer-vision-fallback-layer-set-of-marks.md`

### Phase 1 Results
- **Tests**: 25 new | 279 total (0 failures, 0 regressions)
- **Commit**: Phase 1 cost gate + config + state (`should_activate`, `estimate_cost`)

### Phase 2 Results
- **Tests**: 17 new | 322 total (0 failures, 0 regressions)
- **Commit**: b6cd764 — Vision LLM resolver + executor integration
- **Files changed**: `backend/browser/cv_resolver.py`, `backend/engine/executor.py`, `tests/test_cv_fallback_resolver.py`
- **Key deliverables**:
  - `CvFallbackResolver.resolve()` — full SoM snapshot → Bedrock → mark_id pipeline
  - `_invoke_cv_vision_llm()` + `_call_bedrock_vision()` + `_parse_mark_id_from_response()`
  - Executor wiring: CV fires after DOM failure, overrides result on success, augments error on failure
  - `cv_fallback_results` + `cv_fallback_invocations` state updated per invocation
- **Commit**: `1f0736b` on `feature/FEAT-037-cv-fallback-som`

### Phase 3 Results
- **Tests**: 14 new | 336 total (0 failures, 0 regressions)
- **Files changed**: `backend/engine/verifier.py`, `backend/engine/executor.py`, `tests/test_cv_fallback_verifier.py`, `memory-bank/systemPatterns.md`
- **Key deliverables**:
  - `cv_fallback_state_change_check()` in `verifier.py` — 3-signal detection (URL, ARIA, element count), 2s wait, never raises
  - Executor wiring: pre-click URL snapshot, post-click state check, `CV_CLICK_SUCCESS`/`CV_CLICK_FAILED` branching
  - HITL escalation carries `CV_CLICK_FAILED` context when no DOM change detected
  - `systemPatterns.md` updated with full CV Fallback pattern documentation

### Phase 4 Results
- **Tests**: 32 new | 368 total (0 failures, 0 regressions)
- **Commit**: 65df637 — KB recipe cv_fallback.yaml + reporter CV badge & summary
- **Files changed**: `knowledge/blueprints/cv_fallback.yaml`, `backend/engine/reporter.py`, `tests/test_cv_fallback_reporter.py`
- **Key deliverables**:
  - `cv_fallback.yaml` — KB recipe with `cv_fallback_eligible: true` on `coordinate_action`; triggers on canvas/shadow/iframe keywords; lowers executor threshold from 3→1
  - `_render_cv_fallback_section()` — HTML summary footer: invocation count, success rate %, estimated cost, per-invocation table
  - `_render_execution_log()` — 🎯 CV Fallback badge on steps with `cv_fallback=True`, shows mark_id + coordinates inline
  - `_render_full_report()` — wired CV section after metrics; state without CV fields degrades gracefully (no crash)
  - CSS: `.cv-fallback-badge` (purple gradient) + `.cv-fallback-section` (purple border)

### Sub-Agent Log
| Step | Agent | Status | Notes |
|------|-------|--------|-------|
| PLAN | Orchestrator | COMPLETE | Full L4 plan authored 2026-05-17 |
| CREATIVE | Architecture Design | COMPLETE | Output: memory-bank/creative/computer-vision-fallback-layer-set-of-marks-cv-fallback-architecture.md (2026-05-17) |
| BUILD P1 | Orchestrator | COMPLETE | 4 files: cv_resolver.py, config.py, state.py, test_cv_fallback_cost_gate.py |
| BUILD P2 | Orchestrator | COMPLETE | 3 files: cv_resolver.py, executor.py, test_cv_fallback_resolver.py |
| BUILD P3 | Orchestrator | COMPLETE | 3 files: verifier.py, executor.py, test_cv_fallback_verifier.py |
