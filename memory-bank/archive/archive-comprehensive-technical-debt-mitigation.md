# comprehensive-technical-debt-mitigation: Comprehensive Technical Debt Mitigation Roadmap

**Complexity**: Level 4
**Status**: COMPLETE
**Jira Issue**: N/A
**Feature**: FEAT-049
**Priority**: High
**Branch**: feature/FEAT-049-tech-debt-mitigation
**Worktree**: .worktrees/comprehensive-technical-debt-mitigation

---

## Problem Statement

The vQA project has accumulated 35 tracked technical debt items (TD-001 to TD-035) across the engine, frontend, storage, and development processes. While the system is architecturally sound, these gaps create compounding maintenance costs, mask regressions, and prevent the system from scaling to multi-user/distributed environments.

This task provides a comprehensive, phased roadmap to eliminate all identified debt.

---

## Acceptance Criteria

### Phase 1: Engine Reliability & Quality Gates (Critical) - COMPLETED
- [x] **AC-GATE-1 (TD-004)**: `ruff` integrated into project; `vc-verify --lint` implemented; all `backend/` violations resolved.
- [x] **AC-HARDEN-1 (TD-003)**: `vision_mode_fail_count`, `_force_wait_before_next_action`, and `_force_wait_ms` added to `VQAState`.
- [x] **AC-HARDEN-2 (TD-003)**: `backend/engine/test_evaluator_hardening.py` and `backend/engine/test_hitl_thresholds.py` pass 100%.
- [x] **AC-IDEM-1 (TD-001/TD-014)**: `ActionRecipe` supports `_force_wait` signals; `recipe_runner.py` distinguishes between navigation and interaction; 4 blueprints retrofitted.

### Phase 2: State Integrity & Backend Architecture (High/Medium) - COMPLETED
- [x] **AC-STATE-1 (TD-002)**: Add `ac_steps_coverage_gap` to `VQAState`; remove gap parsing logic from `reporter.py`.
- [x] **AC-CONFIG-1 (TD-018)**: Implement `JIRA_AC_FIELDS` env-var override for project-specific field mappings.
- [x] **AC-TEST-1 (TD-012/TD-015/TD-019)**: Resolve `TestMatcher` class warning; enforce `anyio_mode = "auto"`; centralize `playwright_mocks.py`.
- [x] **AC-SER-1 (TD-013)**: Implement JSON-safe serialization fallback for `SelectorRAG` to ensure Python 3.13+ compatibility.

### Phase 3: Frontend & E2E Verification (High/Medium) - COMPLETED
- [x] **AC-FE-1 (TD-007)**: Establish Vitest/React-Testing-Library suite; achieve >50% coverage on core sidebar/log components.
- [x] **AC-WS-1 (TD-020/TD-032)**: Add Playwright E2E test for WebSocket handshake and iframe CORS headers.
- [x] **AC-EXPL-1 (TD-008/TD-033)**: Implement `test_exploration_live_page.py` with static fixture; track live exploration telemetry.
- [x] **AC-VNC-1 (TD-016)**: Implement time-based event debouncing in the VNC JS injection layer.

### Phase 4: Data & Automation - COMPLETED
- [x] **AC-REG-1 (TD-006)**: Create utility script to auto-populate `dropdown_registry.json` from Angular templates.
- [x] **AC-STORE-1 (TD-009/TD-010)**: Support `ACCEPTED_TESTS_DIR` for remote/shared storage; implement `last_used` pruning logic.
- [x] **AC-SHADOW-1 (TD-017)**: Update `VisionAnalyzer` and SoM overlay to pierce Shadow DOM internals for web components.
- [x] **AC-KB-1 (TD-022/TD-034/TD-035)**: Expand synonym maps; optimize RAG for short AC steps; implement per-step chunking for large blueprints.

### Phase 5: Code Hygiene & Process Polish (Low) - COMPLETED
- [x] **AC-PROC-1 (TD-011/TD-027/TD-028)**: Fix "Status Header Drift"; auto-sync `tasks.md`; fix Phase Gate conflicts.
- [x] **AC-CLEAN-1 (TD-005/TD-021/TD-023)**: Remove dead code in `failure_classifier.py`, `component_registry.py`, and `reflection-agent-prompt.md`.
- [x] **AC-TELE-1 (TD-025/TD-029/TD-030/TD-031)**: Standardize benchmark flags; export `vision_token_usage` to UI; implement PDF and CLIP-based Jira attachment support.

---

## Implementation Roadmap

### Phase 1: Engine Hardening & Quality Gates - COMPLETED
1.  **Engine Reliability (TD-004)**
    - [x] Add `ruff` to `backend/requirements.txt`.
    - [x] Create `pyproject.toml` with `ruff` configuration.
    - [x] Update `Makefile` with `ruff` linting target.
    - [x] Fix all existing `ruff` violations in `backend/`.
2.  **VQAState Hardening (TD-003)**
    - [x] Add `vision_mode_fail_count`, `_force_wait_before_next_action`, and `_force_wait_ms` to `VQAState` in `backend/engine/state.py`.
    - [x] Initialize new fields in `make_initial_state`.
    - [x] Update `evaluator.py` to increment `vision_mode_fail_count` and respect `_force_wait` flags.
3.  **Recipe Idempotency (TD-001 / TD-014)**
    - [x] Update `ActionRecipe` and `RecipeStep` in `backend/engine/recipe_runner.py` for `_force_wait`.
    - [x] Refactor `execute_recipe` to return force-wait signals.
    - [x] Retrofit `force_wait_before_next: true` in 4 major blueprints.
    - [x] Implement `verify_state_change` verification type (comprehensive-technical-debt-mitigation).

### Phase 2: Architectural Cleanup - COMPLETED
- [x] Refactor `VQAState` coverage gap tracking.
- [x] Clean up test suite warnings and boilerplate.
- [x] Implement environment-based Jira config.

### Phase 3: Verification Layer - COMPLETED
- [x] Scaffold frontend unit tests.
- [x] Create E2E WebSocket/CORS tests.
- [x] Implement VNC debounce.

### Phase 4: Data & Automation - COMPLETED
- [x] Build Angular-to-Registry scanner.
- [x] Implement shared storage and pruning for Replays.
- [x] Enhance Shadow DOM visibility.

### Phase 5: Polish - COMPLETED
- [x] Automated header/task-list sync (via `scripts/sync_tasks.py`).
- [x] Dead code removal (Failure Classifier, Component Registry).
- [x] Advanced vision/attachment features (PDF, CLIP-like ranking).
- [x] Standardized benchmark flags.

## Test Strategy
- **Static Analysis**: Project-wide `ruff` pass.
- **Unit Tests**:
    - `backend/engine/test_evaluator_hardening.py` (Must pass 100%)
    - `backend/engine/test_hitl_thresholds.py` (Must pass 100%)
- **Integration**: Blueprint execution verification for all 10+ interaction types.
- **E2E**: Live Playwright tests for exploration and connectivity (Phase 3).
