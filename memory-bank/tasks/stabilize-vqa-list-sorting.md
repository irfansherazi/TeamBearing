---
legacy_id: stabilize-vqa-list-sorting
---
# stabilize-vqa-list-sorting: Stabilize vQA list sorting

**Complexity**: Level 3
**Status**: COMPLETE
**Archived**: memory-bank/archive/archive-stabilize-vqa-list-sorting.md
**Completed**: 2026-05-15
**Roadmap**: FEAT-031
**Branch**: feature/FEAT-031-stabilize-vqa-list-sorting
**Worktree**: .worktrees/FEAT-031

## Task Description

Stabilize vQA list sorting automation by adding data-testid attributes and aria-sort indicators to the vSuite UI, while implementing loop-breaking circuit breakers in the vQA engine to prevent recursion timeouts.

## Specification

**Feature Type**: NFR/Infrastructure
**Creative Exploration Needed**: No

### Verification Method
- **Test method**: Execute vQA tests targeting sort operations (e.g., List Views in vSuite2.0).
- **Success metrics**: Sort operations execute without GraphRecursionError timeouts.
- **Observable at**: vQA HTML audit reports and backend engine console logs.
- **Verification frequency**: On-deploy (headless batch runs).

### Acceptance Criteria

#### AC-VERIFY-1: Circuit breaker prevents infinite loops
**Priority**: MUST
**Given** a list view sorting operation where the planner fails to find or interact with the sort header
**When** the agent attempts to retry the sort action
**Then** a loop-breaking circuit breaker limits retries and safely aborts or escalates without hitting Python recursion limits (`GraphRecursionError`).

#### AC-VERIFY-2: vSuite UI supports deterministic sort identification
**Priority**: MUST
**Given** a PrimeNG table or custom list view in vSuite2.0
**When** the DOM is rendered
**Then** sortable column headers contain explicit `data-testid` (e.g., `data-testid="sort-header-[col]"`) and standard `aria-sort` attributes.

#### AC-VERIFY-3: vQA planner recognizes sort indicators
**Priority**: MUST
**Given** a list view with updated sort indicators
**When** the vQA planner receives the ARIA tree and screenshot
**Then** it successfully correlates the column to the `data-testid`/`aria-sort` and issues the correct click action.

### Scope Boundaries
- **In scope**: Adding `data-testid` and `aria-sort` attributes to sortable headers in the `vsuite2.0` Angular frontend. Implementing a recursion circuit breaker in the vQA evaluator/executor.
- **Out of scope**: Modifying non-sorting PrimeNG components or other vQA pipelines.
- **Dependencies**: Requires synchronized deployment of `vsuite2.0` changes before vQA can reliably use the new attributes, though the circuit breaker in vQA is independent.

### Implementation Guide Required
No.

## Test Strategy

### Approach
- **Emphasis**: balanced
- **Target test count**: 8

### File Organization
- **New test files**: `tests/engine/test_circuit_breaker.py`
- **Extend existing**: `tests/engine/test_evaluator.py`, `vsuite2.0/src/app/shared/components/table/table.component.spec.ts`

### What NOT to Test
- We will not test the Angular framework's ability to render bindings, only that our bindings are present.

### Per-Phase Test Guidance
- Phase 1: 4 tests — circuit breaker triggers, iteration limits, error logging.
- Phase 2: 4 tests — sort headers render `data-testid` and `aria-sort`.

## Implementation Plan

### Overview
Stabilize the sorting actions in vQA by updating the target UI (vSuite2.0) with reliable locators (`data-testid`, `aria-sort`) and updating the vQA engine with a circuit breaker to prevent infinite loops during recursive state checks.

### Requirements
#### Functional
- Add `data-testid` to vsuite2.0 table headers.
- Add `aria-sort` attributes to indicate current sort state.
- Implement loop-breaker in vQA evaluator routing.

#### Non-Functional
- Prevent `GraphRecursionError` timeouts.

### Component Analysis
#### New Components
- None.

#### Affected Components
- `vsuite2.0`: Shared table components or specific list view components containing PrimeNG table headers.
- `vQA backend/engine/evaluator.py`: Retry routing logic to include strict iteration depth limits.

### Implementation Roadmap
- [x] Phase 1: Implement circuit breakers in vQA evaluator.
- [x] Phase 2: Update vSuite UI with data-testid and aria-sort indicators.
- [ ] Phase 3: Validate sorting reliability through E2E tests.

### Dependencies & Risks
- Risk: vQA evaluator circuit breaker might trigger too early on complex pages. → Mitigation: Tune threshold to be higher than typical recovery loops but lower than recursion limit (e.g., 5-10 retries).

### Observability Requirements
- **Applies**: Yes
- **Logging**:
  - Business event logging: Log `CIRCUIT_BREAKER_TRIPPED` in `evaluator.py` when recursion limit is reached.
- **Tracing**: N/A
- **Metrics**: N/A
- **Configuration**: None.

### API Requirements
- **REST API**: No
- **GraphQL API**: No

### Creative Phases Required
- [ ] Architecture design

### Work Items

#### WI-020-001: vQA Circuit Breaker
**Status**: Pending
**Dependencies**: None
**Files**: `backend/engine/evaluator.py`
**Implementation**: Add iteration tracking and strict retry limits for sort-related actions.

#### WI-020-002: vSuite2.0 Sort Indicators
**Status**: Pending
**Dependencies**: None
**Files**: `vsuite2.0/src/app/...`
**Implementation**: Update PrimeNG table header templates to bind `data-testid` and `aria-sort`.

## Creative Phases
(None required)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO
**Build Started**: 2026-05-15T16:09:00Z
**Phase Number**: 3 of 3
**Is Multi-Phase**: YES

### Current Build Step
**Step**: REFLECTION
**Status**: COMPLETE

### Completed Steps
- Step 0.1 Agent Rules Check: COMPLETE (2026-05-15T16:09:00Z) - Index updated
- Step 0.5 Git Setup Agent: COMPLETE (2026-05-15T16:09:00Z) - Worktree verified
- Step 0.6 Phase Gate: COMPLETE (2026-05-15T16:09:00Z) - Passed
- Step 1 Read Task Context: COMPLETE (2026-05-15T16:09:00Z) - Phase 3 identified
- Step 2 Load Context: COMPLETE (2026-05-15T16:09:00Z) - Level 3 rules loaded
- Step 3 Test Writer Agent: COMPLETE (2026-05-15T16:10:30Z) - Output: Created 1 test file with 2 tests covering sorting validation.
- Step 4 Coding Agent: COMPLETE (2026-05-15T16:15:30Z) - Output: 0 implementation files created, fixed E2E test files.
- Step 5/6 Test Execution: COMPLETE (2026-05-15T16:15:40Z) - Output: 2/2 tests passed
- Step 7 Integration Verification: COMPLETE (2026-05-15T16:18:40Z) - Benchmarks and tests passed
- Step 9 Documentation Agent: COMPLETE (2026-05-15T16:18:50Z) - Output: Updated progress.md

### Sub-Agents
### Sub-Agent: Reflection Agent
**Agent Type**: Reflection
**Status**: COMPLETE
**Agent ID**: inline
**Completed**: 2026-05-15T16:19:16Z
**Output**: memory-bank/reflection/reflection-stabilize-vqa-list-sorting.md

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A
**Notes**: Ready for /archive
