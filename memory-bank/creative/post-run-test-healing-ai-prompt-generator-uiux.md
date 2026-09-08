# UI/UX Design: post-run-test-healing-ai-prompt-generator Post-Run Test Healing — AI Prompt Generator

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: UI/UX Design
**Task**: post-run-test-healing-ai-prompt-generator / FEAT-110

---

## Overview

post-run-test-healing-ai-prompt-generator adds an interactive, high-value **"Heal Tests"** option to the Playwright suite results dashboard. When failures exist on completion, the user is offered a clear action to compile and retrieve a correction prompt.
The design covers:
1. Integrating the **🩹 Heal Tests** action trigger directly into the header controls of `SuiteResultsPanel.tsx`.
2. A beautiful, immersive, dark-themed Modal Overlay dialog that houses the generated AI prompt.
3. Interactive copy mechanisms with precise visual state transitions.

---

## Layout and Placement

### 1. Header Trigger Integration
The **"Heal Tests"** button is placed at the top-right corner of `SuiteResultsPanel.tsx` next to the progress metrics or back button:

```
+-------------------------------------------------------------------------+
|  📊 SUITE EXECUTION FAILED                                [🩹 Heal Tests] [◀ Back] |
+------------------------------------+------------------------------------+
|  Total: 41 | Passed: 39 | Failed: 2 | Time: 1m 15s                       |
+------------------------------------+------------------------------------+
```

- **Visibility Rule**: Only visible when the suite is in state `"completed"` or `"failed"`, AND `failed > 0`.
- **Active / Loading State**: When clicked, the button transitions to a disabled loading state, replacing the text with a spinning wheel and `"Generating Prompt..."`.

### 2. Immersive Prompt Modal Overlay
On API success, a Modal overlay centers on the screen with a high-contrast backdrop blur:

```
+-------------------------------------------------------------------------+
|                                                                         |
|         +-----------------------------------------------------+         |
|         | 🩹 AI Test Healing Prompt                       [X] |         |
|         |-----------------------------------------------------|         |
|         | Copy the compiled context-rich prompt below and     |         |
|         | paste it into Claude/Gemini to heal your tests.     |         |
|         |                                                     |         |
|         | +-------------------------------------------------+ |         |
|         | | # Playwright Test Healing Request               | |         |
|         | | You are an expert Playwright automation...      | |         |
|         | |                                                 | |         |
|         | | [Scrollable, dark monospace text area]          | |         |
|         | +-------------------------------------------------+ |         |
|         |                                                     |         |
|         | [📋 Copy to Clipboard]                      [Close] |         |
|         +-----------------------------------------------------+         |
|                                                                         |
+-------------------------------------------------------------------------+
```

---

## UI Components & Interactive Elements

### 1. Trigger Button
- **Default State**:
  - **Label**: `🩹 Heal Tests`
  - **Background**: Soft purple border-accent or distinct button class (`background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.4); color: #a78bfa;`).
- **Loading State**:
  - **Label**: `⏳ Generating...`
  - **Interaction**: Disabled (`pointer-events: none; opacity: 0.6`).
- **Hover state**: Light scaling delta and background fill highlight (`background: rgba(139, 92, 246, 0.25);`).

### 2. Modal Overlay & Dialog Frame
- **Backdrop**: Smooth translucent slate overlay with backdrop-blur (`background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(4px);`).
- **Frame**: Structured card container (`max-width: 800px; width: 90%; background: #1e293b; border: 1px solid #334155; border-radius: 12px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);`).
- **Header**: Contains the healing emoji, clear bold text, and an upper-right `[X]` exit trigger.

### 3. Scrollable Code Container
- **Component**: `<pre>` or `<textarea>` element styled as a dark-theme console window.
- **Styling**: `background: #090d16; border: 1px solid #1e293b; font-family: var(--font-mono, monospace); font-size: 0.85rem; color: #cbd5e1; border-radius: 6px; padding: 16px; max-height: 400px; overflow-y: auto; overflow-x: hidden;`.
- **Selection**: Auto-selected on click to allow rapid manual copying if clipboard API is blocked.

### 4. Interactive Action Buttons
- **Copy to Clipboard Button**:
  - Primary call-to-action inside the modal footer.
  - **State Transitions**:
    - **Idle**: Label `📋 Copy Prompt`, Icon: copy sheets, Color: Purple-accent.
    - **Clicked / Success**: Label `✅ Copied!`, Icon: Checkmark, Color: Green-accent. Restores to idle after a 2-second debounce timer.
- **Close Button**: Standard neutral secondary button (`border: 1px solid #475569; color: #94a3b8;`).

---

## Design System Tokens & Classes

We introduce the following styling definitions in the frontend (or embed them directly inside the modal components) to ensure absolute visual parity:

```css
/* Healing Trigger Button */
.btn-heal-tests {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(139, 92, 246, 0.15);
  border: 1px solid rgba(139, 92, 246, 0.4);
  color: #c084fc;
  padding: 6px 12px;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-heal-tests:hover:not(:disabled) {
  background: rgba(139, 92, 246, 0.25);
  border-color: rgba(139, 92, 246, 0.6);
  color: #d8b4fe;
}

.btn-heal-tests:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal Overlay Base */
.heal-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(9, 13, 22, 0.8);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.15s ease-out;
}

/* Modal Frame */
.heal-modal-container {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 12px;
  width: 90%;
  max-width: 750px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
  animation: scaleUp 0.15s ease-out;
}

/* Scrollable Mono Area */
.heal-prompt-area {
  background: #030712;
  border: 1px solid #1f2937;
  border-radius: 8px;
  padding: 16px;
  margin: 16px 24px;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
  color: #e5e7eb;
  max-height: 380px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  user-select: all; /* Allows quick select-all on double-click */
}

/* Keyframes */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes scaleUp {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
```
