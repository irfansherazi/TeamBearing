---
name: Ephemeral UI Observer Pattern
globs: ["backend/browser/context.py", "backend/engine/verifier.py"]
paths: ["backend/browser/", "backend/engine/"]
topics: ["reliability", "race-conditions", "ephemeral-ui"]
priority: medium
auto_generated: true
evidence_count: 1
last_reinforced: 2026-05-12
source_tasks: ["TASK-009"]
derived_from: []
last_validated: 2026-07-22
---


# Ephemeral UI Observer Pattern

Eliminate race conditions for transient UI elements (toasts, alerts, auto-closing menus) by injecting a persistent MutationObserver into the browser context.

- **Init-Script Injection**: Use `browser_context.add_init_script()` to inject the observer at the earliest possible moment, ensuring it captures elements that appear/disappear during page load or immediately after interactions.
- **In-Browser FIFO Buffer**: Store captured events in a lightweight global array (e.g., `window.__VQA_TOAST_BUFFER__`) with a size limit (e.g., 10 entries) to prevent memory leaks.
- **Temporal Filtering**: When verifying against the buffer, always apply a timestamp-based filter (e.g., last 15 seconds) to ensure matches are relevant to the current AC step and not stale leftovers.
- **Verification Cascade (Tier 0)**: Treat the browser buffer as "Tier 0" in the verification logic—checking it before polling the DOM or falling back to transient caches.
- **Persistent-State Verification**: When verifying UI state changes (e.g. view switches, sorting), prioritize persistent DOM markers (wrapper classes, URL changes) over ephemeral indicators like `.active` or menu overlays. Ephemeral elements often disappear immediately after interaction, leading to verification loops.
