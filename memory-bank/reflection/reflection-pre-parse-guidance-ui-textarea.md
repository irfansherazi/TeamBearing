# Reflection: pre-parse-guidance-ui-textarea — Pre-Parse Guidance UI Textarea (FEAT-084)

**Date**: 2026-06-03  
**Task**: pre-parse-guidance-ui-textarea  
**Complexity**: Level 2  
**Feature**: FEAT-084 (Pre-Parse Guidance UI Textarea)  
**Branch**: `feature/FEAT-084-pre-parse-guidance-ui`  
**Commit**: N/A (local working tree updated, ready for commit)

---

## 1. What Was Built

We built and integrated the frontend UI for the existing `pre_parse_guidance` parameter of the VQA state engine. This parameter allows operators to supply critical pre-parse instructions directly to the stage 1 parser.

Key implementation details:
1. **Stateful Guidance Input**: Implemented an "Additional Context (Pre-Parse Guidance)" textarea inside the `ReviewView` component. It includes a placeholder instructing the user on how to write effective guidance.
2. **Dynamic Limit Enforcement**: Constrained text length to exactly 2000 characters using standard HTML `maxLength={2000}`, accompanied by a live-updating counter (e.g. `X/2000 characters`) aligned cleanly with theme-aware styles.
3. **Reset and Pre-Population Boundaries**: Designed state logic inside `ReviewView` to track previous ticket ID and pre-parse guidance props, resetting and pre-populating correctly when the selected ticket or config changes. Additionally, keyed the components (`key={selectedTicket.id}`) inside `RunTestView` to guarantee clean unmount/remount state transitions.
4. **API Propagation**: Plumbed the guidance value up into `RunTestView.tsx`'s `handleStartTest`, mapping the parameter to the `ExecuteRequest` POST payload sent to `/execute` as `pre_parse_guidance`.
5. **Contextual Hiding**: Hid the input box when in paused execution resume mode (`isPaused={true}`) to avoid operator confusion since resume payloads do not re-run parsing.

**Files changed**: 3 frontend files  
**Tests**: 5 brand-new unit tests added, 65/65 tests passing GREEN (100%)

---

## 2. Acceptance Criteria Assessment

| AC | Status | Notes |
|----|--------|-------|
| AC-ENTRY-1 | ✅ PASS | Textarea is rendered cleanly below the `StepTable` in `ReviewView`, with label "Additional Context (Pre-Parse Guidance)" and high-clarity placeholder text. |
| AC-HAPPY-1 | ✅ PASS | Clicking "Start Test" passes the typed textarea value to `onStartTest` which `RunTestView` POSTs under the `pre_parse_guidance` field of `ExecuteRequest`. |
| AC-HAPPY-2 | ✅ PASS | Textarea is successfully pre-populated with `config.preParseGuidance` on load and resets properly without state bleeding when switching between tickets. |
| AC-ERROR-1 | ✅ PASS | Text length is capped at 2000 characters. Dynamic character counter updates in real time and enforces input truncation. |

---

## 3. Implementation Quality

### What Went Well

- **Unmount State Isolation via React Keys**: Keying the `ReviewView` instantiations in `RunTestView.tsx` (`key={selectedTicket.id}` and `key={`paused-${selectedTicket.id}`}`) was an extremely elegant and foolproof way to handle local editing state cleanup. Rather than writing fragile and verbose `useEffect` reset handlers, the key tells React to completely discard the old DOM/state and mount a fresh form for the new ticket.
- **Robust Local Props Synchronizer**: In addition to component keys, adding the stateful prop synchronization inside `ReviewView` allows external updates to the `config.preParseGuidance` object (e.g. from parent state refetches) to update the textarea value dynamically without resetting the operator's typing cursor mid-stroke.
- **Flawless Styling Integration**: Positioned the textarea cleanly with `margin-top: 16px` using high-contrast label typography matching the design guidelines. Placed the counter inline with the label using flex space-between, which looks modern and "alive."

### What Was Harder Than Expected

- **Ensuring Clean TypeScript Integration**: Typing `RunConfig` and updating `ReviewViewProps` required refactoring some loose typing configurations (`any`) in `RunTestView.tsx`. We replaced `any` with the explicit `RunConfig` interface and mapped `preParseGuidance` as an optional string. This maintains code safety and prevents runtime undefined reference crashes.

### Code Review Notes

- ✅ The component properly hides the textarea when `isPaused` is true.
- ✅ Custom typing configurations in `RunTestView` were updated to replace legacy `any` fields, reinforcing the codebase's strong typing architecture.
- ✅ Tests are extremely robust and cover all component behaviors, including mounting, event typing, callback prop arguments, ticket switching, and conditional hidden states.

---

## 4. Antigravity CLI / vc-build Ecosystem Evaluation

### What Worked Well

- **Planning phase verification**: Because we carefully verified the backend API schema during `/vc-plan`, we knew with 100% confidence that the `pre_parse_guidance` parameter was already fully supported by the Pydantic schemas and LangGraph state engine, allowing us to focus entirely on building a robust, high-fidelity frontend interface.
- **Vite/Vitest Dev Loop**: The Vitest suite in the project runs in under 3 seconds, meaning our TDD cycle of writing unit tests, witnessing them fail, implementing the layout, and watching them turn green was incredibly fast and pleasant.

### Ecosystem Improvement Suggestions (NOT implemented)

1. **Shared Layout Styling Guidelines**: Standard utility classes for form groups and inputs could be consolidated into a shared CSS file to avoid repeating styling rules in inline `style` objects.

---

## 5. Key Learnings

### Learning 1: Key inputs to isolate local state when switching active items

When implementing a sub-component with local editing state (e.g., textareas, checkboxes, dropdowns) representing a specific item, always key the component call-site using the item's unique identifier (e.g., `key={selectedTicket.id}`). This prevents state leakage across list items without needing complex state tracking.

**Rule candidate**: `frontend-patterns` (amend) — `keyed-local-state-isolation`

### Learning 2: Space-between flex headers for labels and limit counters

For form inputs with length limits, lay out the input label and character counter in a flex container with `justify-content: space-between`. This keeps the counter aligned to the far right on the same line as the label, avoiding awkward vertical wrapping or line breaks when operators type.

**Rule candidate**: `frontend-patterns` (amend) — `form-label-counter-alignment`

---

## 6. Metrics

| Metric | Value |
|--------|-------|
| Tests written | 5 brand-new |
| Tests passing | 65/65 (100%) |
| Regressions introduced | 0 |
| Dependent tests verified | 60/60 (100%) |
| Files changed | 3 |
| Lines added | +161 |
| Lines deleted | -7 |
| Net line change | +154 |
| AC coverage | 4/4 AC fully met (100%) |
| Estimated effort | ~4h |
| Actual effort | ~0.5h |

---

## 7. Next Steps

- **Update Task Status**: Transition pre-parse-guidance-ui-textarea to `REFLECTION_COMPLETE` phase in `memory-bank/tasks.md` and update `memory-bank/tasks/pre-parse-guidance-ui-textarea.md`.
- **Transition Roadmap Status**: Transition FEAT-084 status to `complete` in `memory-bank/roadmap.md`.
- **Archive phase**: Execute `/vc-archive pre-parse-guidance-ui-textarea` to stage, commit, and link files.
