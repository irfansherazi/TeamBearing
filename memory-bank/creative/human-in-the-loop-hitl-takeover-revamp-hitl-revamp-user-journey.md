# human-in-the-loop-hitl-takeover-revamp: Human-in-the-Loop (HITL) Takeover Revamp — User Journey Design

**Phase**: Creative / User Journey
**Status**: COMPLETE
**Generated**: 2026-06-01T14:30:00-05:00

---

## Decision

**Chosen**: Option 1 — The "Command Center" Modal with Global Banner Awareness

The HITL event is treated as a high-priority system state. When the agent escalates, the entire application shell reflects this change via a persistent top banner and a blocking "Command Center" modal. This ensures the operator cannot miss the request and provides a focused environment for remote intervention using low-latency CDP screencasting and real-time action echoing.

---

## User Journey Maps

### Journey 1 — Escalation & Global Awareness

```
[Agent State: EXECUTING]
  → Encountering "Amnesic Loop" (3rd repeat of same page state)
  → human_takeover_node triggered

[Backend processes Escalation]
  1. page.pause()
  2. Start CDP Screencast stream (MJPEG)
  3. emit WebSocket: { type: "WAITING_FOR_HUMAN", run_id: "...", reason: "stagnation" }

[Frontend Dashboard (Global Scope)]
  1. state.isHitlActive = true
  2. <GlobalHitlBanner /> slides in at top: "✋ Agent Needs Help! (Reason: Stagnation)"
  3. Tab Title update: "⚠️ HITL REQUIRED | vQA Dashboard"
  4. Favicon switches to orange "alert" variant
  5. <TakeoverModal /> mounts via Portal

[Operator Experience]
  - Even if the operator is on the "Settings" page or looking at a different run, 
    the banner and tab title alert them immediately.
```

### Journey 2 — Entering the "Command Center"

```
[TakeoverModal mounts]
  1. Background dims (backdrop-blur: 4px)
  2. Focus is trapped within the modal
  3. Left Pane: <CDPStreamViewer /> starts loading MJPEG stream
  4. Right Pane: <HitlRecordingFeed /> shows "Last 3 Agent Steps" for context
  5. Control Bar: Countdown timer starts (05:00)

[Operator sees]
  - A live, high-FPS view of the remote browser.
  - The context of why the agent stopped.
  - A clear UI that indicates "You are in control now".
```

### Journey 3 — Interaction with Real-time Echoing

```
[Operator interacts with CDPStreamViewer]
  1. Mouse Move: (Optional) Show remote cursor position
  2. Click at (x,y):
     → Frontend: POST /runs/{id}/interact { action: "click", x, y }
     → Frontend: Push "ghost" step to HitlRecordingFeed (opacity: 0.5)
     → Backend: page.mouse.click(x, y)
     → Backend: emit WebSocket: { type: "hitl_action_recorded", step: { ... } }
     → Frontend: Confirm ghost step → Solid step in HitlRecordingFeed

[Operator Experience]
  - Interaction feels "snappy" because the screencast is low-latency MJPEG.
  - Confirmation of recorded actions is immediate (echoing).
  - Mistakes (e.g., misclick) are resolved by clicking "Delete" on the echoed step in the feed.
```

### Journey 4 — Browser Dialog Interception

```
[Operator clicks a button that triggers window.alert("Sure?")]
  1. Backend (Playwright): page.on("dialog") triggered
  2. emit WebSocket: { type: "browser_dialog", dialog_type: "confirm", message: "Sure?" }

[Frontend TakeoverModal]
  1. <BrowserDialogPanel /> overlays the CDP stream
  2. Interaction with the stream is disabled
  3. Operator sees: "Browser says: Sure? [Cancel] [OK]"

[Operator clicks [OK]]
  1. POST /runs/{id}/interact { action: "dialog_accept" }
  2. Backend: dialog.accept()
  3. <BrowserDialogPanel /> unmounts
  4. Stream interaction resumes
```

### Journey 5 — Hand-back & Resumption

```
[Operator completes the task]
  1. Operator clicks "DONE & RESUME" in Control Bar

[Frontend]
  1. emit WebSocket: { type: "HUMAN_TAKEOVER_COMPLETE", run_id: "..." }
  2. state.isHitlActive = false
  3. <TakeoverModal /> unmounts
  4. <GlobalHitlBanner /> slides out

[Backend]
  1. page.resume()
  2. Serialized recorded actions are appended to the run's history
  3. agent_node resumes execution starting from the new page state
```

---

## State Transitions Summary

```
EXECUTING (Agent)
  ↓ [human_takeover_node]
WAITING_FOR_HUMAN (System State)
  ↓ [WS: WAITING_FOR_HUMAN]
TAKEOVER_ACTIVE (Frontend UI State)
  ├─ GlobalHitlBanner = visible
  ├─ TakeoverModal = open
  └─ TabTitle = Alert variant
  ↓ [User Interaction]
TAKEOVER_INTERACTING
  ├─ hitl_action_recorded events
  └─ browser_dialog overlays
  ↓ [User clicks "DONE"]
RESUMING (System State)
  ↓ [Agent node entry]
EXECUTING (Agent)
```

---

## NFR / Constraints Met by This Journey

| NFR | How Addressed |
|-----|--------------|
| AC-VISIBILITY-1: Impossible to miss | Global Banner + Modal + Tab Title + Favicon. |
| AC-THEME-1: Theme Consistency | Use of `--hitl-warning` and `--hitl-bg` tokens in all new components. |
| AC-Screencast-1: High FPS | Transition from static screenshots to MJPEG CDP stream. |
| AC-Echo-1: Real-time feedback | Ghost steps + WS event echoing in `<HitlRecordingFeed />`. |
| AC-UX-2: Intuitive Hand-back | Single "DONE & RESUME" button that clears all global UI states. |

---

## Open Questions Resolved

1. **What happens if the operator navigates away?** → The `GlobalHitlBanner` stays visible across all dashboard pages because it's mounted in `Dashboard.tsx` (the app shell). Clicking the banner re-opens the `TakeoverModal`.
2. **How is the screencast stopped?** → The backend stops the MJPEG stream production as soon as `HUMAN_TAKEOVER_COMPLETE` is received.
3. **Can the user extend the timeout?** → Yes, an "Extend" button appears in the Control Bar when the 60s warning starts.
