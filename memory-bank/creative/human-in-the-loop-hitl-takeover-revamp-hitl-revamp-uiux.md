# UI/UX Decision: human-in-the-loop-hitl-takeover-revamp Human-in-the-Loop (HITL) Takeover Revamp

**Created**: 2026-05-30
**Status**: DECIDED
**Decision Type**: UI/UX

## User Context

### Target Users
- **Primary**: HITL Operator / QA Analyst - Needs to quickly unblock a stuck agent with minimal friction and low latency.
- **Secondary**: PM / QA Lead - Monitoring runs; needs high-visibility indicators when attention is required.

### User Goals
1. **Immediate Awareness**: Never miss a takeover request, regardless of the active dashboard tab.
2. **Natural Interaction**: Remote browser control should feel as close to a local browser as possible (low lag, high FPS).
3. **Auditable Actions**: See exactly what actions are being recorded to ensure the agent "learns" the correct behavior.
4. **Visual Consistency**: The takeover interface must respect the user's selected theme (Light/Dark).

### Use Cases
| Use Case | User | Goal | Frequency |
|----------|------|------|-----------|
| **Takeover Trigger** | System | Notify user that agent is stuck | ~10-20% of runs |
| **Direct Interaction** | Operator | Click/type in remote browser to solve a step | Every takeover |
| **Action Review** | Operator | Delete accidental clicks from the recorded feed | Occasional |
| **Native Dialog Handling**| Operator | Dismiss an alert or confirm a popup | Occasional |
| **Control Hand-back** | Operator | Resume the autonomous agent | End of every takeover |

### Constraints
- **Devices**: Desktop only (primary focus).
- **Accessibility**: WCAG AA. Keyboard focus management in modal. ARIA live regions for status updates.
- **Existing Patterns**: Must use CSS variables from `index.css`. Modal must integrate with React 19 `createPortal` pattern.

## User Flow

### Flow Diagram
```
[Agent Stuck] → [WebSocket: WAITING_FOR_HUMAN]
                      ↓
[Global Banner Appears] + [Takeover Modal Opens]
                      ↓
[User sees Live CDP Stream] ↔ [User Interacts with Browser]
                      ↓                  ↓
[Dialogs handled via Panel] ← [Actions echoed to Recording Feed]
                      ↓
             [User clicks "Done & Resume"]
                      ↓
[WebSocket: DONE] → [Agent Resumes Execution]
```

### Flow Description
1. **Entry**: Agent hits a failure threshold or amnesic loop. Backend triggers `WAITING_FOR_HUMAN` event.
2. **Notification**: `GlobalHitlBanner` slides into view at the top of the app shell. Simultaneously, the `TakeoverPanel` modal opens centered on screen.
3. **Interaction**: User sees a live MJPEG stream (CDP-based) instead of static screenshots. Clicks and keypresses are sent to the backend and immediately echoed back into the `HitlRecordingFeed`.
4. **Correction**: User can delete any step in the `HitlRecordingFeed` if they made a mistake.
5. **Native Dialogs**: If the browser shows an `alert`, `confirm`, or `prompt`, the `BrowserDialogPanel` appears as a high-priority overlay within the modal, preventing interaction with the page until the dialog is handled.
6. **Exit**: User clicks "Done & Resume". The modal closes, the banner disappears, and the agent continues.

### Error States
| Error | Cause | User Recovery |
|-------|-------|---------------|
| **Stream Lag** | Network congestion | Visual indicator (fps counter/health) shows orange; user waits for settle. |
| **Timeout Approaching** | 5-minute inactivity | 60s warning appears with "Extend" button. |
| **WS Disconnect** | Server/Network drop | "Reconnecting..." overlay blocks interaction to prevent blind clicks. |

## Options Explored

### Option 1: The "Command Center" Modal (CHOSEN)
- **Approach**: A high-z-index centered modal that blocks the background. The main content area is split between the live stream and the recording feed.
- **Wireframe/Layout**:
  ```
  ┌───────────────────────────────────────────────────────────┐
  │  Global Banner: ✋ Agent Needs Help! (Timer: 04:59)       │
  ├───────────────────────────────────────────────────────────┤
  │                                                           │
  │   ┌─────────────────────────────────────────┬─────────┐   │
  │   │ [BrowserDialogPanel (if active)]        │ ACTIONS │   │
  │   ├─────────────────────────────────────────┤         │   │
  │   │                                         │ [Step 1]│   │
  │   │                                         │ [Step 2]│   │
  │   │        LIVE CDP SCREEENCAST             │ [Step 3]│   │
  │   │             (MJPEG Stream)              │         │   │
  │   │                                         │         │   │
  │   │                                         │         │   │
  │   ├─────────────────────────────────────────┴─────────┤   │
  │   │ [Control Bar: Cancel | Extend Time | DONE & RESUME]│   │
  │   └───────────────────────────────────────────────────┘   │
  │                                                           │
  └───────────────────────────────────────────────────────────┘
  ```
- **Pros**:
  - Maximum focus on the intervention.
  - Clear separation of "Agent" vs "Human" modes.
  - High visibility (impossible to miss).
- **Cons**:
  - Blocks view of the execution logs in the background.
- **Usability**: High
- **Accessibility**: High
- **Implementation Complexity**: Medium

### Option 2: The "Integrated Drawer"
- **Approach**: A side drawer (similar to `CopilotSidebar`) that expands to 80% width when takeover is active.
- **User Flow**: Banner appears -> User clicks "Open Takeover" -> Drawer slides in from right.
- **Pros**: Matches the existing sidebar paradigm.
- **Cons**: Can feel cramped; doesn't feel like a "global" event; harder to manage native dialog overlays.
- **Usability**: Medium
- **Accessibility**: Medium
- **Implementation Complexity**: Medium

## Evaluation Matrix

| Criteria | Option 1 (Modal) | Option 2 (Drawer) |
|----------|------------------|-------------------|
| Usability | 5/5 (Focused) | 3/5 (Cramped) |
| Accessibility | 5/5 (Standard Modal) | 4/5 |
| Consistency | 4/5 (New but bold) | 5/5 (Sidebar-like) |
| Responsiveness | 5/5 | 5/5 |
| Performance | 5/5 | 5/5 |
| Implementation | 4/5 | 4/5 |

## Decision

**Chosen**: Option 1 - The "Command Center" Modal

### Rationale
The "Command Center" Modal provides the necessary gravitas for a Human-in-the-Loop event. Since the agent has stopped execution to wait for a human, the UI should reflect this "pause" globally. The modal prevents "blind" interaction with other dashboard parts while a critical takeover is in progress. Using CDP-based screencasting (MJPEG) in a large modal area provides the best user experience for remote browser control.

### Trade-offs Accepted
- **Background Blocking**: Users cannot see the full `ExecutionLog` while the modal is open. *Mitigation*: The modal will include a "Show Context" toggle or display the last 3 agent steps at the top of the action feed.

## Design Specifications

### Layout
- **Desktop**: 90vw width, 85vh height centered modal. 2-column layout (70/30).
- **Tablet**: Full-screen modal.
- **Mobile**: Not supported (test execution is a desktop-first workflow).

### Key Components
| Component | Purpose | Behavior |
|-----------|---------|----------|
| `GlobalHitlBanner` | Persistent awareness | Sticky `top: 0`, `z-index: 1000`. Blinks/Pulses on first appearance. |
| `HitlRecordingFeed`| Action echoing | Scrollable list. Each item has a `Delete` button. "Ghost" steps show while action is in flight. |
| `BrowserDialogPanel`| Native alert handler | Centered top overlay on the stream. Blocks stream interaction until Dismissed/Accepted. |
| `CDPViewer` | High-FPS Stream | `<img />` tag consuming the MJPEG stream URL with low-latency headers. |

### Interactions
| Trigger | Action | Feedback |
|---------|--------|----------|
| User clicks stream | `POST /interact` (click) | Pulse animation at click coordinates on stream. |
| User types | `POST /interact` (keypress) | Input buffer appears briefly at bottom of stream. |
| Action Recorded | WS `hitl_action_recorded` | New card slides into `HitlRecordingFeed`. |
| Dialog Triggered| WS `browser_dialog` | `BrowserDialogPanel` appears with "OK/Cancel" buttons. |

### Responsive Behavior
| Breakpoint | Changes |
|------------|---------|
| < 1024px | Stack `HitlRecordingFeed` below the `CDPViewer`. |
| > 1024px | 2-column side-by-side layout. |

### Accessibility Requirements
- [x] Keyboard navigation support (Focus trap inside modal)
- [x] Screen reader compatibility (ARIA alerts for "Takeover Active")
- [x] Color contrast compliance (WCAG AA - use high contrast for Banner)
- [x] Focus indicators visible
- [x] Error messages accessible

## Implementation Guidelines

### For Developers
1. **MJPEG Stream**: Use a standard `<img>` tag. The backend will serve a stream that handles the MJPEG headers. Ensure no-cache headers are set.
2. **Action Echoing**: Use a "Pending" state in the `HitlRecordingFeed` when an interaction is sent but not yet confirmed by the backend event.
3. **Theme Tokens**: Strictly use `var(--accent)`, `var(--bg-primary)`, `var(--text-primary)`, etc. For the HITL Banner, introduce `var(--hitl-warning)` (orange/amber) to distinguish from standard accents.
4. **WebSocket**: The `Dashboard` should own the global HITL state (`isHitlActive`) and pass it down via context or props.

### Component Structure
```
frontend/src/components/hitl/
├── GlobalHitlBanner.tsx
├── TakeoverModal.tsx (Replaces TakeoverPanel)
├── HitlRecordingFeed.tsx
├── BrowserDialogPanel.tsx
└── CDPStreamViewer.tsx
```

### Recommended Libraries/Patterns
- **React Portal**: For the Modal to ensure it sits above all other UI.
- **CSS Grid**: For the 70/30 split layout.

## Validation Checklist
- [x] Meets all user goals
- [x] Accessible per requirements
- [x] Consistent with existing patterns (Theme tokens)
- [x] Respects Guiding Principles (HITL as Learning Signal)
- [x] Responsive across devices
- [x] Performance acceptable (CDP > Screenshots)
- [x] Implementation feasible

## Next Steps
1. Refactor `index.css` to include `--hitl-warning` and `--hitl-bg` tokens.
2. Implement the Backend MJPEG stream endpoint.
3. Build the `GlobalHitlBanner` and integrate into `Dashboard.tsx`.
4. Rebuild `TakeoverPanel` as `TakeoverModal`.
