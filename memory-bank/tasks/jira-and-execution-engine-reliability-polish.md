---
legacy_id: jira-and-execution-engine-reliability-polish
---
# jira-and-execution-engine-reliability-polish: Jira & Execution Engine Reliability Polish

**Complexity**: Level 4
**Status**: ARCHIVED
**Archive**: [archive-jira-and-execution-engine-reliability-polish.md](../archive/archive-jira-and-execution-engine-reliability-polish.md)
**Jira Issue**: N/A
**Issue Type**: Feature/Refactor
**Priority**: High
**Branch**: feature/FEAT-064-jira-execution-polish
**Worktree**: N/A
**Roadmap**: [FEAT-064: Jira & Execution Engine Reliability Polish](../roadmap.md#feat-064-jira--execution-engine-reliability-polish)

---

## Task Description

Reliability sweep across three pillars: Jira integration, execution engine (stagnant UI), and frontend theme consistency.

### 1. Jira Integration Enhancements
*   **Fetch Comments**: Modify `backend/jira/client.py` to fetch issue comments and implement an ADF-to-text converter.
*   **De-duplicate Plans**: Update `backend/jira/negotiator.py` to check for existing "vQA Proposed Test Plan" comments before posting new ones.
*   **Manual Confirmation for Sync**: Add a `requires_confirmation` gate to the AC Sync flow in `backend/jira/negotiator.py`.

### 2. Execution Engine & Planner Fixes
*   **Resolve Stagnant UI Loop**: Update `backend/engine/verifier.py` to use a multi-signal delta check (URL, count, aria-snapshot, overlay markers) to prevent false stagnant UI verdicts.
*   **Culling Adjustments**: Update `backend/engine/planner.py` to explicitly preserve elements in PrimeNG overlay portals during DOM culling.

### 3. Frontend UI Consistency
*   **Design Tokens**: Refactor hardcoded colors in `ExecutionPanel.tsx` and `TriagePanel.tsx` to use theme-aware CSS variables.

---

## Acceptance Criteria

- AC-JIRA-1: Backend fetches and uses Jira comments for test planning.
- AC-JIRA-2: ADF-to-text conversion is robust and handles complex ADF structures.
- AC-JIRA-3: No duplicate "vQA Proposed Test Plan" comments are posted.
- AC-JIRA-4: AC Sync requires user confirmation (HITL gate) before updating Jira.
- AC-ENGINE-1: "STAGNANT UI" check uses multi-signal delta to avoid loops on subtle transitions.
- AC-ENGINE-2: Overlay elements are preserved in the accessibility tree (no over-culling).
- AC-UI-1: Execution and Triage panels match the active theme (Light/Dark).
- AC-VAL-1: Unit tests verify ADF parser and stagnant UI logic.

---

## Affected Components

- `backend/jira/client.py`
- `backend/jira/negotiator.py`
- `backend/engine/verifier.py`
- `backend/engine/planner.py`
- `frontend/src/components/ExecutionPanel.tsx`
- `frontend/src/components/TriagePanel.tsx`
- `tests/test_jira_adf_parser.py`
- `tests/test_stagnant_ui_logic.py`

---

## Test Strategy

### Approach
- **Unit Testing**: Add tests for Jira ADF parsing and Stagnant UI multi-signal logic.
- **Integration Testing**: Simulate the AC sync HITL flow and verify de-duplication.
- **Manual Verification**: Verify theme consistency and engine reliability in the live dashboard.

---

## Implementation Roadmap

- [x] Phase 1: Research & Reproduction (Stagnant UI Loop)
- [x] Phase 2: Jira Reliability (ADF Parser & Comment Sync)
- [x] Phase 3: Execution Engine & Planner Fixes (Culling & Stagnant UI)
- [x] Phase 4: Frontend UI Consistency (Theme Injection)
- [x] Phase 5: Validation & Testing

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: ARCHIVE
**Current Step**: All phases complete and verified. Ready to archive.
**Can Resume**: NO
