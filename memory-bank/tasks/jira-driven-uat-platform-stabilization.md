---
legacy_id: jira-driven-uat-platform-stabilization
---
# jira-driven-uat-platform-stabilization: Jira-Driven UAT Platform Stabilization

**Complexity**: Level 4 (Enterprise/Architectural)
**Status**: COMPLETE
**Roadmap Link**: FEAT-106
**Branch**: feature/FEAT-106-uat-platform-stabilization

## Task Description

Master stabilization initiative to evolve vQA from an experimental LLM-loop agent into a production-grade, Jira-driven UAT platform. Synthesized from empirical data (Week 2 baseline: 0/10 cards passing due to expired auth + selector collisions) and three independent architecture evaluations.

The work is structured into 4 sprints:

1. **Sprint 0 — Empirical Grounding**: Resolve two hard blockers (expired Playwright auth state, `input[type='password']` strict-mode selector collision). Run QA-170 true baseline.

2. **Sprint 1 — Wire the Wiring Gap**: Connect four disconnected components to the linear pipeline — AC Parser wiring, Jira Posting fix, Multi-Signal Stagnant UI Detection, FAIR Quality Gate wiring.

3. **Sprint 2 — A11y Tree + Dynamic Selectors**: Replace brittle static `selectors.json` (28 selectors, ≤20% coverage) with dynamic A11y tree discovery — snapshot capture, augmented spec generation, powered self-healing.

4. **Sprint 3 — Golden 10 Benchmark + Iteration**: Run all 10 golden cards, document every failure, achieve ≥40% AC item pass rate, update self-healing rates from `[THEORETICAL]` to `[EMPIRICAL]`.

### Dependencies

- **linear-pipeline-execution-engine-rewrite-spec** (BUILD_COMPLETE): Linear Pipeline Execution Engine Rewrite — provides the Generate → Validate → Execute → Analyze DAG that this task stabilizes.

---

## User Journey Definition

**Feature Type**: Infrastructure / Platform Stabilization
**Creative Phase Required**: No (the master plan already received 3 independent architecture reviews)

### NFR Verification (Infrastructure Features)
- **Test method**: Run the golden_10 benchmark corpus and verify per-AC-item pass/fail:
  ```bash
  python3 -m backend.engine.linear_runner \
    --corpus tests/benchmarks/golden_10_data.json \
    --tenant vpromedia \
    --output tests/benchmarks/golden_10_results.json
  ```
  Plus unit tests:
  ```bash
  pytest tests/test_linear_ac_parser_wiring.py tests/test_jira_posting_linear.py tests/test_stagnant_ui_logic.py tests/test_ui_delta.py tests/test_fair_gate_linear.py tests/test_a11y_discovery.py tests/test_a11y_spec_generation.py tests/test_self_healing_detection.py -v
  ```
- **Success metrics**:
  - Auth state regenerated — Playwright sessions run without login-redirect failures
  - AC Parser wired — `card["expected_steps"]` is non-empty for tickets with raw AC text
  - Jira Posting works — `POST /run/{id}/post-to-jira` returns 200 for linear pipeline runs
  - ≥40% AC item pass rate on golden_10 corpus (150 AC items denominator)
  - Self-healing success rates updated from `[THEORETICAL]` to `[EMPIRICAL]`
- **Observable at**:
  - `tests/benchmarks/golden_10_results.json` — per-card, per-AC-item pass/fail
  - Backend logs showing 4-signal stagnant UI detection
  - Backend logs showing FAIR quality gate scores

---

## Acceptance Criteria

### AC-1: Auth State Regeneration
**Priority**: MUST
**Given** the Playwright auth state file exists at `playwright/storage/vpromedia_auth.json`
**When** a linear pipeline run is started
**Then** Playwright sessions run against `two-test.vcreative.net` without login-redirect failures and cookies are non-expired.

### AC-2: AC Parser Wired to Linear Pipeline
**Priority**: MUST
**Given** a Jira ticket is fetched with raw AC text and no `expected_steps`
**When** `_execute_linear_run()` processes the card
**Then** `card["expected_steps"]` is non-empty — populated by `_stage_1_normalize` + `_stage_2_compile` from `ac_parser.py`.

### AC-3: Jira Posting for Linear Pipeline Runs
**Priority**: MUST
**Given** a linear pipeline run has completed (pass or fail)
**When** the user clicks "Post to Jira" on the Triage Panel
**Then** `POST /run/{id}/post-to-jira` returns 200 with the correct `failure_analysis` payload.

### AC-4: Multi-Signal Stagnant UI Detection
**Priority**: MUST
**Given** the verifier is checking for UI stagnation
**When** computing a delta between pre- and post-action state
**Then** 4 signals are used (URL, element count, ARIA snapshot, overlay markers) via a shared `ui_delta.py` utility.

### AC-5: FAIR Quality Gate Wiring (Log-Only MVP)
**Priority**: SHOULD
**Given** a ticket's AC has been parsed
**When** the FAIR quality gate runs
**Then** it logs the grade but does NOT block the pipeline.

### AC-6: A11y Tree Snapshot Capture
**Priority**: MUST
**Given** a target URL on `two-test.vcreative.net`
**When** the A11y discovery module runs
**Then** it captures ≥50 named elements from `page.accessibility.snapshot()` in <10 seconds.

### AC-7: A11y-Augmented Spec Generation
**Priority**: MUST
**Given** an A11y tree snapshot is available
**When** the generator node builds the LLM prompt
**Then** generated specs use `page.getByRole()` locators derived from the A11y tree context.

### AC-8: Self-Healing Categories 2 + 6
**Priority**: MUST
**Given** a Playwright spec execution failure
**When** the failure is classified as timing (Category 2) or interaction change (Category 6)
**Then** self-healing detects the pattern and retries with max 3 retries across all categories.

### AC-9: Golden 10 Benchmark
**Priority**: MUST
**Given** the golden_10 corpus of 10 cards (~150 AC items)
**When** the benchmark runner executes all 10 cards
**Then** 10 result entries are produced with per-AC-item pass/fail breakdown.

### AC-10: ≥40% AC Item Pass Rate
**Priority**: SHOULD (target)
**Given** the golden_10 benchmark results
**When** computing the overall pass rate
**Then** ≥40% AC items pass (60+ out of ~150).

### AC-11: Empirical Self-Healing Rates
**Priority**: MUST
**Given** the golden_10 benchmark completes
**When** reviewing self-healing retry outcomes
**Then** success rates are updated from `[THEORETICAL]` to `[EMPIRICAL]` labels.

### AC-12: vc-uat / Linear Pipeline Convergence Design
**Priority**: SHOULD
**Given** both `/vc-uat` and linear pipeline execution exist
**When** a convergence plan is requested
**Then** a design document is produced (approved before any code).

---

## Test Strategy

### Approach
- **Unit tests per work unit**: Each WU has its own dedicated test file.
- **Integration verification**: Golden_10 benchmark run validates end-to-end pipeline.
- **Regression safety**: Existing tests must continue to pass after every sprint.

### Test Files
- `tests/test_linear_ac_parser_wiring.py` (Sprint 1 — WU-1.1)
- `tests/test_jira_posting_linear.py` (Sprint 1 — WU-1.2)
- `tests/test_stagnant_ui_logic.py` (Sprint 1 — WU-1.3)
- `tests/test_ui_delta.py` (Sprint 1 — WU-1.3)
- `tests/test_fair_gate_linear.py` (Sprint 1 — WU-1.4)
- `tests/test_a11y_discovery.py` (Sprint 2 — WU-2.1)
- `tests/test_a11y_spec_generation.py` (Sprint 2 — WU-2.2)
- `tests/test_self_healing_detection.py` (Sprint 2 — WU-2.3)

### Full Regression
```bash
pytest tests/ -v --timeout=60
```

---

## Implementation Roadmap

### Sprint 0: Empirical Grounding (Day 1)
- [x] **WU-0.1**: Auth Remediation + Selector Fix (BLOCKERS)
  - Regenerate `playwright/storage/vpromedia_auth.json` with fresh cookies
  - Fix `login-password-input` selector collision in `tenants/vpromedia/selectors.json`
- [x] **WU-0.2**: Run QA-170 True Baseline
  - Execute `python3 -m backend.engine.linear_runner --card QA-170 --tenant vpromedia`
  - Produce `sprint_0_baseline.md` artifact

### Sprint 1: Wire the Wiring Gap (Days 2-5)
- [x] **WU-1.1**: Wire AC Parser to Linear Pipeline
  - Modify `backend/api/routes.py` — call `_stage_1_normalize` + `_stage_2_compile`
  - Test: `tests/test_linear_ac_parser_wiring.py`
- [x] **WU-1.2**: Fix Jira Posting Integration
  - Add `failure_analysis` key to `_run_states` in `_execute_linear_run()`
  - Fix `post_triage_to_jira()` to read from both state locations
  - Test: `tests/test_jira_posting_linear.py`
- [x] **WU-1.3**: Multi-Signal Stagnant UI Detection
  - Create `backend/engine/ui_delta.py` (shared utility)
  - Update `verifier.py` to use `compute_ui_delta()`
  - Update `planner.py` overlay-aware DOM culling
  - Tests: `tests/test_stagnant_ui_logic.py`, `tests/test_ui_delta.py`
- [x] **WU-1.4**: Wire FAIR Quality Gate
  - Add `score_ac_quality()` call after AC parser in `_execute_linear_run()`
  - Test: `tests/test_fair_gate_linear.py`

### Sprint 2: A11y Tree + Dynamic Selectors (Days 6-10)
- [x] **WU-2.1**: A11y Tree Snapshot Capture
  - Create `backend/engine/a11y_discovery.py`
  - Test: `tests/test_a11y_discovery.py`
- [x] **WU-2.2**: A11y-Augmented Spec Generation
  - Modify `backend/engine/generator_node.py` — inject A11y tree into prompt
  - Wire A11y snapshot call in `_execute_linear_run()` before pipeline start
  - Test: `tests/test_a11y_spec_generation.py`
- [x] **WU-2.3**: A11y-Powered Self-Healing (Categories 2 + 6)
  - Expand `backend/engine/linear_bridge.py` — add `_detect_timing_failure()` and `_detect_interaction_change()`
  - Test: `tests/test_self_healing_detection.py`

### Sprint 3: Golden 10 Benchmark + Iteration (Days 8-12)
- [x] **WU-3.1**: Golden 10 Benchmark Run
  - Execute all 10 golden cards
  - Produce `golden_10_results.json`
- [x] **WU-3.2**: Failure Triage + Iteration
  - Categorize all failures by type
  - Compute per-category fix ROI
- [x] **WU-3.3**: vc-uat / Linear Pipeline Convergence Plan (design-only)
  - Produce convergence design document (no code)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: REFLECTION_COMPLETE
**Current Step**: Reflection complete, ready for archive
**Step Started**: 2026-06-05T11:20:00-05:00
**Can Resume**: YES

### Active Sub-Agents
(none)

### Completed Steps
- User Journey Design: COMPLETE (2026-06-05) - Output: `memory-bank/creative/jira-driven-uat-platform-stabilization-user-journey.md`
- Architecture Design: COMPLETE (2026-06-05) - Output: `memory-bank/creative/jira-driven-uat-platform-stabilization-architecture.md`
- Algorithm Design: COMPLETE (2026-06-05) - Output: `memory-bank/creative/jira-driven-uat-platform-stabilization-algorithm.md`
- Sprint 3 Benchmark & Convergence: COMPLETE (2026-06-05) - Output: `docs/linear_pipeline_convergence_plan.md`
