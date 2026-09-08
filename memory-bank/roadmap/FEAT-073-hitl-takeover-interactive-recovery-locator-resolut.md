---
legacy_id: FEAT-073
version: next
linked_tasks: []
status: planned
---

  ### FEAT-073: HITL Takeover: Interactive Recovery & Locator Resolution
- **Version**: next
- **Status**: planning
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: Translate VNC/CDP clicks and manual interventions during takeover back into native, standard Playwright locators for self-healing and macro generation.
    1. **Injected Standalone Selector Engine**: Compile a community-extracted version of Playwright’s native SelectorGenerator (such as `@mizchi/selector-generator`) and bundle it directly into vQA's injected takeover script (`injection.js`). When the user clicks an element during takeover, generate authentic, weighted Playwright locators directly inside the JS listener (e.g., `internal:role=button[name="Submit"i]`).
    2. **Backend Coordinate-to-Locator Resolution**: When a user clicks on the VNC stream or vQA dashboard, the frontend posts coordinates to `/runs/{run_id}/interact`. The Python backend uses Playwright's CDP channel to evaluate `document.elementFromPoint(x, y)` to get an ElementHandle, and runs a backend helper to derive the native locator representation of that handle.
    3. **Playwright Recorder Session**: When a takeover node activates, the backend triggers Playwright's internal recorder session. Instead of listening to JS click events, vQA subscribes directly to the Chromium recorder channel.
- **Acceptance Criteria**:
    - AC-1: Bundle a Playwright-compatible SelectorGenerator in `backend/browser/injection.js` to capture interactions and resolve them to authentic Playwright locators.
    - AC-2: Expose a Python CDP coordinate-to-locator service via `/runs/{run_id}/interact` using `document.elementFromPoint(x, y)`.
    - AC-3: Support an alternative Playwright Recorder Session that listens directly to the CDP recorder channel during active human takeover.
    - AC-4: Extracted locators match standard Playwright syntax and are fed as few-shot examples to the planner to improve self-healing.
- **Key Files**:
    - `backend/browser/injection.js`
    - `backend/engine/human_takeover.py`
    - `backend/api/routes.py`
    - `backend/browser/context.py`
- **Linked Tasks**: None
- **Branch**: feature/FEAT-073-hitl-locator-resolution
- **Created**: 2026-06-02
