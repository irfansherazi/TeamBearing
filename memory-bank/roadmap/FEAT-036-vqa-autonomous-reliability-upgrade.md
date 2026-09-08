---
legacy_id: FEAT-036
version: next
linked_tasks: []
status: planned
---

### FEAT-036: vQA Autonomous Reliability Upgrade
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: A comprehensive, multi-phase upgrade to eliminate the three main classes of vQA failures observed in production runs: (1) Locator Ambiguity at Source — move from reactive STRICT_MODE recovery to proactive KB-layer container-scoped locators and DOM-introspective option resolution in primeng_dropdown so the agent never generates ambiguous selectors in the first place; (2) Execution Budget & State Management — implement sort-state tracking in VQAState so the agent knows which direction a column is currently sorted, add a complexity-adjusted per-step budget formula that scales with AC count and interaction complexity, and persist inter-step UI state to eliminate redundant re-probing; (3) Latency & Context Efficiency — prune the planner prompt to only current-step context (removing stale past-action entries, trimming DOM snapshot to viewport-visible elements) to reduce avg latency from 4500ms toward 2000ms target, and canonicalize compound column header interaction into a dedicated recipe so it executes in 2 steps rather than 15+. Success metrics: ≥95% AC step pass rate on the 321 sorting card without HITL, avg step latency ≤ 2500ms, total cost reduction ≥ 40% vs current baseline ($1.92 → <$1.15).
- **Linked Tasks**: None
- **Branch**: feature/FEAT-036-vqa-autonomous-reliability
- **Created**: 2026-05-16
