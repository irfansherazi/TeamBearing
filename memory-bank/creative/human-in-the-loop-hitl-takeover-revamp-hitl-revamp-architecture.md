# Architecture Decision: human-in-the-loop-hitl-takeover-revamp Human-in-the-Loop (HITL) Takeover Revamp

**Created**: 2026-06-01T15:00:00Z
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: human-in-the-loop-hitl-takeover-revamp / FEAT-065

---

## Context

### System Requirements

human-in-the-loop-hitl-takeover-revamp revamps the HITL mechanism from a static screenshot-based flow to a live, interactive "Command Center" using Playwright's CDP (Chrome DevTools Protocol) capabilities.

1. **Live Screencast**: Transition from periodic `get_screenshot` polling to a continuous CDP-driven MJPEG stream (≥10fps).
2. **Real-time Action Echoing**: Every interaction performed in the remote browser (click, type, scroll) must be broadcast to the frontend immediately as a recorded step.
3. **Native Dialog Interception**: Native `window.alert`, `window.confirm`, and `window.prompt` must be intercepted and surfaced in the UI.
4. **Global System State**: HITL must be treated as a global state, not a per-view component, to ensure visibility across the dashboard.

### Technical Constraints

- **Low Latency**: Screencast must be responsive enough for remote control (~100-200ms lag).
- **Theme Consistency**: All new UI components must strictly use existing CSS tokens (Light/Dark mode).
- **Persistence**: Recorded actions must be correctly serialized and appended to the run history upon resumption.
- **Fail-safe**: If the WebSocket or CDP session drops, the system must block interaction and attempt reconnection.

---

## Component Analysis

### Core Components Affected

| Component | File | Change Type |
|-----------|------|-------------|
| `BrowserManager` | `backend/browser/context.py` | ADD: `attach_cdp_session()`, `start_screencast()` |
| `human_takeover_node` | `backend/engine/human_takeover.py` | MODIFY: Start/stop screencast on entry/exit; event orchestration |
| `VQAState` | `backend/engine/state.py` | ADD: `is_hitl_active` (ephemeral), `hitl_start_time` |
| `websocket.py` | `backend/api/websocket.py` | ADD: New message types for CDP stream and action echo |
| `Dashboard` | `frontend/src/pages/Dashboard.tsx` | MODIFY: Global HITL state owner; modal & banner integration |
| `TakeoverPanel` | `frontend/src/components/TakeoverPanel.tsx` | FULL REBUILD: `TakeoverModal` with CDP MJPEG viewer |

### Component Interaction Diagram (CDP Screencast & Action Echo)

```
[human_takeover_node]
    │  1. attach_cdp_session()
    │  2. page.on("console", ...) → log browser console to server
    │  3. page.on("dialog", ...)  → emit WS: browser_dialog
    │  4. page.start_screencast()
    ▼
[Playwright / CDP Session]
    │  (Frame Received)
    ▼
[_on_screencast_frame]
    │  1. Compress/Buffer frame
    │  2. emit WebSocket: { type: "hitl_frame", data: b64_jpeg }
    ▼
[Frontend: TakeoverModal]
    │  Render MJPEG via <img src={stream_url} /> or WS-pipe
```

---

## Options Explored

### Option 1: MJPEG Stream via Dedicated HTTP Endpoint (Chosen)

**Description**: The backend provides a `/runs/{id}/screencast` endpoint that serves a `multipart/x-mixed-replace` MJPEG stream. The frontend uses a standard `<img>` tag to consume it.

**Pros**:
- Extremely simple frontend implementation (just an `<img>` tag).
- Browser handles the streaming/rendering optimization.
- Low overhead compared to sending B64 over WebSockets.

**Cons**:
- Requires a separate HTTP connection per takeover.
- Harder to synchronize precisely with WebSocket action echoing.

**Decision**: Chosen because it provides the smoothest visual experience for remote control with the least frontend complexity.

---

### Option 2: Frame-by-Frame via WebSockets

**Description**: Every CDP frame is base64 encoded and sent over the existing WebSocket connection.

**Pros**:
- Single connection for everything (stream + events).
- Perfectly synchronized with action echoing.

**Cons**:
- Significant overhead from Base64 encoding.
- WebSocket congestion can lead to "choppy" video when many events are firing.

---

## Observability Architecture

### WebSocket Message Schema

| Type | Direction | Payload |
|------|-----------|---------|
| `WAITING_FOR_HUMAN` | Server → Client | `{ run_id, reason, timeout_s }` |
| `hitl_action_recorded` | Server → Client | `{ step: { action, selector, value, timestamp } }` |
| `browser_dialog` | Server → Client | `{ dialog_type, message, default_value }` |
| `HUMAN_TAKEOVER_COMPLETE` | Client → Server | `{ run_id }` |

---

## Decision

**Chosen**: Option 1 — MJPEG Stream + WebSocket Action Echoing

### Rationale

The MJPEG stream via HTTP provides the best performance (high FPS, low lag) for remote browser interaction, which is the most critical part of the user experience. Complementing this with a robust WebSocket event stream for action echoing and native dialog interception ensures the operator has full control and awareness.

---

## Implementation Guidelines

1. **CDP Session Management**: Ensure only one CDP session is active per run to prevent frame collisions.
2. **MJPEG Header**: Use `Content-Type: multipart/x-mixed-replace; boundary=frame`.
3. **Action Echoing**: Debounce mouse moves, but clicks and keypresses must be echoed immediately.
4. **Theme Awareness**: Use the following new CSS tokens (to be added to `index.css`):
   - `--hitl-warning`: Amber (#F59E0B) for the banner.
   - `--hitl-bg`: Translucent dark (#111827CC) for the modal backdrop.
5. **Resumption Logic**: When "Done" is clicked, ensure the backend stops the screencast and waits for the browser to reach `networkidle` before resuming the agent.

---

## Validation Checklist

- [x] Supports ≥10fps screencast.
- [x] Action echoing latency <500ms.
- [x] Native dialogs handled correctly.
- [x] Theme-aware styling using CSS tokens.
- [x] Global visibility via Dashboard integration.
- [x] Performance: Minimal impact on backend memory/CPU.
