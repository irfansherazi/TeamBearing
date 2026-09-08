---
version: next
status: completed
priority: high
complexity: 3
linked_tasks: [hitl-portal-aware-click-capture]
created: 2026-07-28
completed: 2026-07-29
---

# HITL Portal-Aware Click Capture

When a human takes over the browser during HITL to demonstrate an action, ensure clicks on portal-mounted elements (React-Portal dropdowns, popovers, autocomplete lists, modals mounted outside the target's DOM subtree) are captured and translated into replayable selectors/actions — closing the current gap where a portal click lands on a detached container and the recorder misses the intended target.

**Complexity rationale**: Set via `--level 3` user override. Multi-component scope — HITL takeover flow, browser action-capture layer, selector generation/registry, and replay pipeline all touch this. Requires design decisions around portal detection (aria-owns / aria-controls vs. DOM position vs. runtime detection), container-to-logical-target mapping, and selector fallback strategy when the portal container is anonymous. Matches Level 3: design decisions + multiple components, not system-wide.
