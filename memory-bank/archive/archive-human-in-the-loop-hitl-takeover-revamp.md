# human-in-the-loop-hitl-takeover-revamp: Human-in-the-Loop (HITL) Takeover Revamp

**Complexity**: Level 3
**Status**: REFLECTION_COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature/UI/UX
**Priority**: High
**Branch**: feature/FEAT-065-hitl-revamp
**Worktree**: N/A
**Roadmap**: [FEAT-065: Human-in-the-Loop (HITL) Takeover Revamp](../roadmap.md#feat-065-human-in-the-loop-hitl-takeover-revamp)

---

## Task Description

Revamp the "agent needs help" workflow to resolve theme inconsistency, clunky UX, and poor visibility.

### 1. Theme Consistency
*   **Theme Injection**: Ensure `TakeoverPanel`, `noVNC` container, and escalation alerts correctly inherit the `[data-theme]` attribute.
*   **Palette Alignment**: Update HITL-specific UI elements (buttons, status badges, instructions) to use theme-aware CSS variables.

### 2. UI/UX Visibility
*   **Global HITL Notification**: Implement a prominent, persistent notification (e.g., a modal overlay or a high-contrast banner in the main navigation) that appears when the agent escalates to HITL.
*   **Proactive State Feedback**: Update the dashboard to clearly distinguish between "Agent Thinking" and "Agent Needs Help" states at a glance.

### 3. Workflow Streamlining
*   **Takeover Handoff**: Refine the transition between autonomous execution and human control to reduce latency and visual jitter.
*   **One-Click Exit**: Simplify the process of returning control to the agent once the human intervention is complete.

---

## Acceptance Criteria

- AC-THEME-1: HITL UI (TakeoverPanel, alerts) follows the active Light/Dark theme.
- AC-VISIBILITY-1: HITL prompt is impossible to miss (modal or global banner).
- AC-VISIBILITY-2: Browser tab title or favicon indicates attention is required when in HITL state.
- AC-UX-1: noVNC handoff is stable and responsive with minimal lag.
- AC-UX-2: Transition into and out of takeover mode is intuitive and fast.
- AC-VAL-1: Smoke test verifies successful takeover and hand-back cycle.

---

## Affected Components

- `frontend/src/components/TakeoverPanel.tsx`
- `frontend/src/components/ExecutionLog.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/auth/AuthContext.tsx` (if theme state is there)
- `backend/engine/human_takeover.py`
- `backend/api/websocket.py`

---

## Test Strategy

### Approach
- **Manual Verification**: Exhaustive testing of the takeover flow in both Light and Dark modes.
- **Integration Testing**: Verify WebSocket signal liveness and UI state transitions.
- **Visual Regression**: Ensure no layout shifts or theme "leaks" during transition.

---

## Specification

### 1. Overview
Revamp the "agent needs help" workflow to resolve theme inconsistency, clunky UX, and poor visibility. This feature introduces a live CDP-based screencast, real-time action echoing, a global takeover modal, and theme-aware CSS tokens.

### 2. Invocation
- **Location**: Global app shell (`frontend/src/components/Dashboard.tsx`) and `RunTestView.tsx`.
- **Trigger**: Automatic escalation when the agent reaches a failure threshold or semantic stagnation (Amnesic Loop) via `human_takeover_node`.

### 3. Component Analysis

#### New Components
- `GlobalHitlBanner.tsx`: Persistent navigation banner for cross-tab notifications.
- `HitlRecordingFeed.tsx`: Real-time list of captured actions with deletion support.
- `BrowserDialogPanel.tsx`: UI for native `alert/confirm/prompt` interception.

#### Affected Components
- `backend/engine/human_takeover.py`: CDP screencast orchestration + event broadcasting.
- `backend/browser/context.py`: `BrowserManager` update for CDP session management.
- `backend/api/routes.py`: `/interact` endpoint state-wait hardening.
- `frontend/src/components/TakeoverPanel.tsx`: Full UI rebuild (CDP viewer + Recording feed).
- `frontend/src/components/Dashboard.tsx`: Global modal and banner integration.
- `frontend/src/index.css`: CSS variable refactor for `.takeover-*` styles.

---

## Acceptance Criteria

- **AC-THEME-1**: HITL UI follows the active Light/Dark theme via CSS custom property tokens (no hardcoded hex in `.takeover-*`).
- **AC-VISIBILITY-1**: A `position: fixed` HITL modal is visible regardless of scroll position or active dashboard tab.
- **AC-VISIBILITY-2**: A persistent global nav banner (`🤚 Agent Needs Help`) appears on all pages during active takeover.
- **AC-Screencast-1**: Live Playwright CDP screencast streams JPEG frames to the takeover panel at ≥10fps.
- **AC-Echo-1**: Each user action in the browser (click, type, scroll) is echoed to the UI in real time as a recorded step within 500ms.
- **AC-Dialog-1**: Native browser dialogs are intercepted and surfaced as an inline panel with Accept/Dismiss controls.
- **AC-Timeout-1**: A 60-second countdown warning is displayed before the 5-minute takeover timeout.
- **AC-Success-1**: One-click "Done" correctly serializes the full captured sequence and resumes the agent.

---

## Test Strategy

### Approach
- **Manual Verification**: Full end-to-end journey walk in both themes.
- **Integration Testing**: Verify WebSocket event flow (`hitl_action_recorded`, `hitl_screenshot_update`).
- **E2E Testing**: Playwright test to trigger HITL and verify modal visibility and screencast liveness.

---

## Implementation Roadmap

### Phase 1: Backend Foundation (CDP & Events)
- [x] Task 1.1: Implement CDP session attachment in `BrowserManager`.
- [x] Task 1.2: Add `Page.startScreencast` logic to `human_takeover_node`.
- [x] Task 1.3: Implement `hitl_action_recorded` event echo in `_on_human_action`.
- [x] Task 1.4: Add `browser_dialog` interception via `page.on("dialog")`.

### Phase 2: Frontend Infrastructure (Modal & Banner)
- [x] Task 2.1: Implement `GlobalHitlBanner` in `Dashboard.tsx`.
- [x] Task 2.2: Convert `TakeoverPanel` to a `position: fixed` modal with backdrop.
- [x] Task 2.3: Implement WebSocket listeners for new HITL events.

### Phase 3: HITL UI Rebuild
- [x] Task 3.1: Implement live CDP screencast viewer in `TakeoverPanel`.
- [x] Task 3.2: Build `HitlRecordingFeed` with real-time updates and step deletion.
- [x] Task 3.3: Build `BrowserDialogPanel` for intercepted alerts/prompts.
- [x] Task 3.4: Add 60s timeout countdown UI.

### Phase 4: Styling & Hardening
- [x] Task 4.1: Refactor `.takeover-*` CSS to use `var(--color-*)` tokens.
- [x] Task 4.2: Implement `page.wait_for_load_state("networkidle")` in `/interact`.
- [x] Task 4.3: Final theme audit and UX polish.

---

## Work Items

#### WI-085-001: Backend CDP & Action Echoing
**Status**: COMPLETE
**Files**: `backend/engine/human_takeover.py`, `backend/browser/context.py`
**Implementation**: Attach CDP session, start screencast on takeover entry, broadcast events on action/dialog.

#### WI-085-002: Global HITL Overlay & Banner
**Status**: COMPLETE
**Files**: `frontend/src/components/Dashboard.tsx`, `frontend/src/components/TakeoverPanel.tsx`
**Implementation**: Move `TakeoverPanel` to global scope, add persistent banner, manage global HITL state.

#### WI-085-003: Live Screencast & Action Feed UI
**Status**: COMPLETE
**Files**: `frontend/src/components/TakeoverPanel.tsx`, `frontend/src/components/HitlRecordingFeed.tsx`
**Implementation**: Render MJPEG stream from WebSocket, list actions as they arrive, allow editing.

#### WI-085-004: Theme Refactor & Hardening
**Status**: COMPLETE
**Files**: `frontend/src/index.css`, `backend/api/routes.py`
**Implementation**: Tokenize CSS colors, add network-idle waits to interaction handler.

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: REFLECT
**Current Step**: Reflection complete.
**Outputs**:
- [human-in-the-loop-hitl-takeover-revamp-hitl-revamp-user-journey.md](../creative/human-in-the-loop-hitl-takeover-revamp-hitl-revamp-user-journey.md)
- [human-in-the-loop-hitl-takeover-revamp-hitl-revamp-uiux.md](../creative/human-in-the-loop-hitl-takeover-revamp-hitl-revamp-uiux.md)
- [human-in-the-loop-hitl-takeover-revamp-hitl-revamp-architecture.md](../creative/human-in-the-loop-hitl-takeover-revamp-hitl-revamp-architecture.md)
- [reflection-human-in-the-loop-hitl-takeover-revamp.md](../reflection/reflection-human-in-the-loop-hitl-takeover-revamp.md)
**Can Resume**: NO


