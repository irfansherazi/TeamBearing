---
legacy_id: FEAT-064
version: next
linked_tasks: [jira-and-execution-engine-reliability-polish]
status: complete
---

  ### FEAT-064: Jira & Execution Engine Reliability Polish
  - **Version**: next
  - **Status**: complete ✅
  - **Priority**: high
  - **Complexity**: Level 4
  - **Description**: Fix Jira integration gaps, reduce notification noise, resolve execution loops, and ensure UI theme consistency.
    1. **Jira Integration Enhancements**: Modify `backend/jira/client.py` to fetch issue comments and include them in requirement extraction, prioritizing high-signal input like Playwright code or "TESTING" sections. Update `backend/jira/negotiator.py` to prevent duplicate "vQA Proposed Test Plan" comments and implement a manual "Confirm/Deny" gate (via `ask_user`) for AC Sync.
    2. **Execution Engine & Planner Fixes**: Investigate and relax the "STAGNANT UI detected" check in `backend/engine/verifier.py` to prevent aggressive looping on subtle UI changes (e.g., search panels). Adjust DOM culling in `backend/engine/planner.py` to ensure elements in overlays are not culled, resolving cases where the verifier thinks the UI hasn't changed.
    3. **Frontend UI Consistency**: Ensure that dropdown overlays (often rendered via Portals) correctly inherit the `[data-theme]` or CSS classes of the selected theme in the frontend.
  - **Acceptance Criteria**:
    - Jira comments are fetched and used for test planning
    - Duplicate test plan comments are prevented
    - AC Sync requires explicit user confirmation
    - Stagnant UI loops are resolved for overlay interactions
    - Overlay elements are correctly preserved in the accessibility tree
    - Dropdown themes match the application theme
  - **Linked Tasks**: jira-and-execution-engine-reliability-polish
  - **Branch**: feature/FEAT-064-jira-execution-polish
  - **Created**: 2026-06-01
