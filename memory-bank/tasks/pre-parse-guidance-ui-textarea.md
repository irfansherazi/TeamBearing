---
legacy_id: pre-parse-guidance-ui-textarea
---
# pre-parse-guidance-ui-textarea: Pre-Parse Guidance UI Textarea

**Complexity**: Level 2
**Status**: COMPLETE
**Roadmap**: [FEAT-084: Pre-Parse Guidance UI Textarea](../roadmap.md#feat-084-pre-parse-guidance-ui)
**Branch**: feature/FEAT-084-pre-parse-guidance-ui
**Worktree**: N/A

---

## Task Description

The `pre_parse_guidance` API field exists in `VQAState` and is read by the AC parser, but there is no UI input wired to it in the React frontend. This means operators have no way to supply custom pre-parse instructions before a run.

To solve this, we will add an "Additional Context" textarea to `ReviewView` that allows operators to enter guidance. This guidance will be submitted as `pre_parse_guidance` in the run initiation payload.

---

## User Journey Definition

**Feature Type**: End-User Feature
**Creative Phase Required**: No

### Invocation Method (End-User Features)
- **Location**: `ReviewView` component (`frontend/src/components/ReviewView.tsx`)
- **Element**: A textarea labeled "Additional Context" positioned above the "Start Run" button.
- **Visibility**: Visible when the run is being configured / reviewed (not shown in paused execution resume mode unless requested, but here visible for editing queued runs).
- **Navigation**: Visible as soon as a ticket is selected and steps are previewed in the "Review" screen.

### Success Criteria (End-User Features)
- **User sees**: An "Additional Context" textarea with a placeholder and a live character counter showing `X/2000 characters`.
- **User can verify at**: Upon starting a run, the submitted text is sent as `pre_parse_guidance` in the POST payload to `/execute`.
- **Data persisted**: Sent to the backend and stored in the execution state's `pre_parse_guidance` field.

### Acceptance Criteria

#### AC-ENTRY-1: Operator can find the Additional Context textarea
**Priority**: MUST

**Given** an operator has selected a ticket and is on the Step Review page (`ReviewView`)
**When** they look below the Step Table and above the start buttons
**Then** they see an "Additional Context" textarea with placeholder text.

**Verification**:
- [ ] Textarea is rendered below the `StepTable`.
- [ ] Textarea has label "Additional Context (Pre-Parse Guidance)".
- [ ] Textarea contains helpful placeholder text.

#### AC-HAPPY-1: Guidance is submitted on run initiation
**Priority**: MUST

**Given** an operator has typed "Use Sort By dropdown for sorting" in the Additional Context textarea
**When** they click "Start Test" or "Resume Test"
**Then** the text value is sent as `pre_parse_guidance` in the run initiation/execution POST payload.

**Verification**:
- [ ] Clicking "Start Test" includes the textarea value in the payload sent to `/execute`.
- [ ] API successfully receives the parameter and saves it in the run state.

#### AC-HAPPY-2: Pre-populated with existing guidance
**Priority**: MUST

**Given** a queued run or a ticket that already has pre-parse guidance configured in `runConfig`
**When** the operator loads the review page for that run
**Then** the textarea is pre-populated with the existing guidance text.

**Verification**:
- [ ] Textarea matches `config.preParseGuidance` on load.
- [ ] Changing tickets properly resets or updates the textarea value.

#### AC-ERROR-1: Enforces character limit
**Priority**: MUST

**Given** an operator typing a very long instruction
**When** the character count approaches 2000 characters
**Then**
  - The counter updates dynamically (e.g. `1995/2000 characters`).
  - Input is truncated or capped at exactly 2000 characters.

**Verification**:
- [ ] Character counter displays current length out of 2000.
- [ ] Entering more than 2000 characters is blocked/truncated.

---

## Test Strategy

### Approach
- **Emphasis**: Balanced unit and integration testing. We will add unit tests to `ReviewView.test.tsx` to verify the rendering, character counter, pre-population, and callback arguments.
- **Target test count**: 4 unit tests.

### File Organization
- **Extend existing**: `frontend/src/components/__tests__/ReviewView.test.tsx` to include testing for the textarea rendering, state change, and form submission.

### What NOT to Test
- Backend AC parsing execution — covered by existing backend unit tests for the Stage 1 BDD normalizer.

### Per-Phase Test Guidance
- Phase 1: Verify the UI elements render correctly with character limit (2 tests).
- Phase 2: Verify state integration and `onStartTest` passes the typed guidance (2 tests).

---

## Implementation Plan

### Subtasks
- [x] Subtask 1: Refactor `ReviewViewProps` and update `ReviewView` to support a stateful textarea with a 2000-char cap and counter.
- [x] Subtask 2: Update `RunTestView` to capture the guidance from `ReviewView` and pass it under `pre_parse_guidance` in the `ExecuteRequest` payload.
- [x] Subtask 3: Add new unit tests to `ReviewView.test.tsx`.
- [x] Subtask 4: Verify the compilation and test suite run successfully.

### Files to Modify
- `frontend/src/components/ReviewView.tsx` - Add textarea, character counter, and handle local state.
- `frontend/src/components/RunTestView.tsx` - Update `handleStartTest` and prop calls to pass `pre_parse_guidance`.
- `frontend/src/components/__tests__/ReviewView.test.tsx` - Add unit tests for the new guidance input.

### Dependencies
- None.

### Observability Requirements
- **Applies**: No.

### API Requirements
- **REST API**: Yes (already exists on the backend schemas and routes as `pre_parse_guidance`).

---

## Execution State

**Build Status**: COMPLETED
**Last Completed**: 2026-06-03
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- [x] Subtask 1: Stateful guidance textarea with 2000-char cap and counter.
- [x] Subtask 2: Pass guidance back to RunTestView and send as pre_parse_guidance.
- [x] Subtask 3: Unit tests in ReviewView.test.tsx.
- [x] Subtask 4: Verified compilation and all tests passing.
ce.
- [x] Subtask 3: Unit tests in ReviewView.test.tsx.
- [x] Subtask 4: Verified compilation and all tests passing.
