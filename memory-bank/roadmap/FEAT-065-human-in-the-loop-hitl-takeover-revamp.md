---
legacy_id: FEAT-065
version: next
linked_tasks: []
status: complete
---

### FEAT-065: Human-in-the-Loop (HITL) Takeover Revamp
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Revamp the "agent needs help" workflow. Root cause analysis identified six concrete failure points that make the current controls non-functional and unintuitive:
    1. **`TakeoverPanel` is not a modal** — it renders inline in `RunTestView`, below the fold and competing with the running view. Users on other dashboard tabs (Archive, KB) receive no notification at all.
    2. **Screenshot-proxy interaction is broken by design** — the user clicks a static, stale image. Actions POST to `/interact` but there is no confirmation the click reached the browser, and the image never refreshes to show the result.
    3. **noVNC is unavailable in most configs** — the live iframe only renders when `execution_mode == "interactive"` AND the VNC URL builds successfully. In the default/local config `vncUrl` is `null`, leaving users with only the broken screenshot-proxy fallback.
    4. **Action capture already works — but silently** — `_inject_click_capture_listener` in `human_takeover.py` already records every click, keypress, scroll, and form-change the user makes in the headed Chromium window via a JS `expose_function` bridge. However, `_on_human_action()` never broadcasts these events back to the frontend. The operator has no indication their actions are being recorded and the captured sequence is only processed on "Done".
    5. **No cross-tab notification** — the `human_takeover` WebSocket event sets state in `RunTestView`, but if that component is unmounted (user navigated away), the event is silently dropped and the 5-minute timeout clock runs unnoticed.
    6. **CSS uses hardcoded hex values** — the entire `.takeover-*` block (3000+ lines in `index.css`) uses `rgba(17, 14, 30, 0.95)`, `#fbbf24`, `#e2e8f0`, etc. with zero `var(--color-*)` token usage. All colors are wrong in light mode.
- **Implementation Approach**:
    1. **Replace noVNC with Playwright CDP Screencast** — use `page.context.new_cdp_session(page)` + `cdp.send("Page.startScreencast", {format: "jpeg", quality: 70, everyNthFrame: 1})` to stream live JPEG frames at 10-30fps directly over the existing WebSocket connection. This eliminates the VNC server, websockify, and noVNC iframe entirely. Works in both headed and headless modes with no additional infrastructure.
    2. **Real-Time Action Echo** — in `_on_human_action()`, after appending to `_human_action_sequence`, call `_WS_BROADCAST_FN` with a new `hitl_action_recorded` event carrying the serialized action and current sequence length. After each action, take a fresh `page.screenshot()` (~200ms delay) and push a `hitl_screenshot_update` event so the UI auto-refreshes showing the settled post-action state.
    3. **Replace Static Controls with Live Recording Feed** — the `TakeoverPanel` keyboard/scroll strip (Type, Enter, Tab, Esc, Scroll Up/Down) should be replaced or supplemented with a live "Recording" feed that shows each captured action as it happens: `✅ click on 'CLIENT column header'`, `✅ fill 'search-input' → "Josh"`. The operator can delete bad steps from the list before clicking Done.
    4. **Global HITL Modal + Cross-Tab Banner** — convert `TakeoverPanel` to a `position: fixed` full-viewport overlay (z-index 9999) with a semi-transparent backdrop, ensuring it is visible regardless of scroll position or active tab. Add a persistent "🤚 Agent Needs Help" banner to the global nav that appears on all pages and deep-links back to the takeover view.
    5. **Surface Browser Dialogs** — register `page.on("dialog", handle_dialog)` during takeover. When a native `alert/confirm/prompt` fires, broadcast a `browser_dialog` WebSocket event to the UI. Render a dialog intercept panel so the operator can Accept/Dismiss without switching to the browser window (unblocks file picker and credential dialog scenarios).
    6. **Post-Action State Confirmation** — add `page.wait_for_load_state("networkidle", timeout=2000)` in the `/interact` endpoint after every injected click to ensure the returned screenshot reflects a settled post-navigation state rather than a mid-render frame.
    7. **Theme via CSS tokens** — replace all hardcoded hex values in `.takeover-*` CSS with `var(--surface-*)`, `var(--text-*)`, `var(--accent)`, `var(--border)` tokens scoped under `[data-theme="light"]` / `[data-theme="dark"]` selectors.
    8. **Timeout Warning** — add a 60-second countdown warning broadcast before the 5-minute takeover timeout expires so the operator is not surprised by a silent run termination.
- **Acceptance Criteria**:
    - AC-1: HITL UI follows the active Light/Dark theme via CSS custom property tokens (no hardcoded hex values in `.takeover-*` rules).
    - AC-2: A `position: fixed` HITL modal is visible regardless of scroll position or active dashboard tab.
    - AC-3: A persistent global nav banner (`🤚 Agent Needs Help`) appears on all pages during an active takeover and dismisses when the takeover is resolved.
    - AC-4: The live Playwright CDP screencast (`Page.startScreencast`) streams JPEG frames to the takeover panel at ≥10fps, replacing the static screenshot proxy.
    - AC-5: Each user action in the headed browser (click, type, scroll) is echoed to the vQA UI in real time as a recorded step entry within 500ms of occurring.
    - AC-6: The UI displays a live "Recording" feed showing the captured action sequence. The operator can delete individual steps before clicking Done.
    - AC-7: Post-action screenshots are automatically pushed to the UI after every injected interaction, showing the settled page state.
    - AC-8: Native browser dialogs (`alert`, `confirm`, `prompt`) are intercepted via `page.on("dialog")` and surfaced as an inline panel in the takeover UI with Accept/Dismiss controls.
    - AC-9: A 60-second countdown warning is displayed before the 5-minute takeover timeout, with a "Extend Time" option.
    - AC-10: One-click "Done — Resume Agent" correctly serializes the full captured sequence via `AutorecordSerializer`, writes to `learned_workflows.json`, `human_guidance.md`, and `vSuite-actions.md`.
- **Key Files**:
    - `backend/engine/human_takeover.py` — `_on_human_action()`, `_inject_click_capture_listener()`, `human_takeover_node()`
    - `backend/api/routes.py` — `/interact` endpoint, `_broadcast_human_takeover()`
    - `backend/browser/context.py` — `BrowserManager`, CDP session attachment
    - `frontend/src/components/TakeoverPanel.tsx` — full UI rebuild
    - `frontend/src/index.css` — `.takeover-*` CSS block (lines ~3192-3721)
    - `frontend/src/components/RunTestView.tsx` — global overlay + nav banner
- **Linked Tasks**: None
- **Branch**: feature/FEAT-065-hitl-revamp
- **Created**: 2026-06-01
- **Updated**: 2026-06-01 (detailed root cause analysis + Playwright CDP approach)

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
