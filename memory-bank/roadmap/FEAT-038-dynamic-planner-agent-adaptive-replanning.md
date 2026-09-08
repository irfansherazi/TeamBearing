---
legacy_id: FEAT-038
version: next
linked_tasks: []
status: planned
---

### FEAT-038: Dynamic Planner Agent (Adaptive Replanning)
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Replaces the current static, sequential AC-step executor with a goal-aware Dynamic Planner Agent. Today, vQA parses Jira AC into a fixed ordered plan; if any unexpected interstitial UI appears (Terms of Service popup, A/B test layout shift, session-expiry modal, permission prompt), the static plan breaks and the agent either burns its retry budget or escalates to HITL. This feature makes the agent adaptive: after every action the agent evaluates the browser state against the high-level Jira AC goal. If the observed state matches the expected post-condition, it advances normally. If an unexpected blocker is detected (modal overlay, URL redirect, toast error, missing element), the agent dynamically generates a Detour Plan — a minimal sub-sequence of actions to dismiss or satisfy the blocker — then resumes from the bookmarked main-path position. The main AC goal is preserved throughout; detour steps are clearly labelled in the audit report and do not count against the AC step pass/fail record. Design decisions required: (1) blocker detection taxonomy (modal vs. redirect vs. toast vs. missing element — each needs a different detour strategy); (2) detour plan generation (LLM-generated vs. rule-based recipe lookup vs. hybrid); (3) main-path bookmark and restoration (VQAState must persist the last confirmed AC step index and its expected post-condition); (4) infinite-replan guard (max detour depth = 2, escalate to HITL after 3 consecutive blocker detections on the same AC step); (5) reporting layer (detour steps surfaced in HTML audit report with distinct styling). Phased implementation: Phase 1 — blocker detection module and VQAState bookmark schema; Phase 2 — detour plan generation engine (LLM + recipe hybrid); Phase 3 — main-path restoration and infinite-replan guard; Phase 4 — audit reporter integration. Success metrics: ≥90% of unexpected-interstitial scenarios auto-resolved without HITL, zero infinite-replan loops reaching the session limit, detour overhead ≤ 3 extra steps per blocker resolution.
- **Linked Tasks**: None
- **Branch**: feature/FEAT-038-dynamic-planner-agent
- **Created**: 2026-05-16
