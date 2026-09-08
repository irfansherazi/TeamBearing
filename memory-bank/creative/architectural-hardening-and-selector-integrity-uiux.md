# Creative Design: architectural-hardening-and-selector-integrity UI/UX — HITL Overlay Visibility

## Problem Statement
The Human-In-The-Loop (HITL) takeover panel is sometimes obscured or "lost" in the UI when multiple sidebars or notifications are active. We need to ensure it is always the most prominent element on the screen during a takeover event.

## Proposed Design: Option A — Global Modal Overlay (Selected)

### 1. Backdrop and Blur
- Use `position: fixed` to cover the entire viewport.
- `z-index: 9999` to ensure it sits above all other elements (including PrimeNG dialogs which typically use 1000-2000).
- `backdrop-filter: blur(12px)` (increased from 8px) to provide a deep visual separation from the underlying app state.
- `background: rgba(0, 0, 0, 0.6)` for high contrast.

### 2. Centered Content Card
- The `TakeoverPanel` should be centered both vertically and horizontally.
- Max-width of 90vw and max-height of 90vh to prevent overflowing small screens.
- Use a shadow to provide depth: `box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4)`.

### 3. Visual "Takeover" Cues
- Add a subtle pulse animation to the border of the `TakeoverPanel` to signal that the system is waiting for user input.
- Disable scrolling on the body while the overlay is active.

## Alternative: Option B — Persistent Header Banner
Show a bright red banner at the top of the screen when takeover is required.
- **Pros**: Less disruptive.
- **Cons**: Easily ignored; doesn't "take over" the workflow which is the goal of HITL.

## Decision: Option A
The global modal overlay is the standard for "stop and help" workflows. It prevents the user from interacting with a potentially broken state while the agent is paused.

## Implementation Details
- Update `.takeover-overlay` in `frontend/src/index.css`.
- Ensure `TakeoverPanel` is rendered in a Portal if necessary to escape any container-level `overflow: hidden`.
