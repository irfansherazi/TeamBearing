---
legacy_id: FEAT-040
version: next
linked_tasks: [exploration-mode-and-autonomous-kb-self-heal]
status: complete
---

### FEAT-040: Exploration Mode & Autonomous KB Self-Heal
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: When vQA cannot find a target element, it currently retries with locator variants and then escalates to HITL. This feature introduces an intermediate "Exploration Mode" that fires before HITL escalation. Instead of immediately surfacing a human interrupt, the agent autonomously navigates adjacent UI topology — clicking through sibling tabs, expanding collapsed accordions/panels, and scrolling into viewport — searching for the missing target. If located, the agent resumes execution normally. If not found within the exploration budget, it escalates to HITL as before. Crucially, every successful exploration builds institutional knowledge: the agent synthesizes the discovered navigation pathway into a structured KB entry and injects it into human_guidance.md (Bedrock Knowledge Base), allowing future runs to resolve the same element directly without exploration overhead. Design decisions required: (1) exploration trigger — exactly when in the failure recovery chain Exploration Mode activates (after N locator failures, before HITL threshold); (2) exploration strategy taxonomy — ordered traversal of: scroll-to-reveal, expand-collapsed-parent, click-sibling-tab, open-accordion, toggle-panel — with depth and breadth limits per strategy; (3) exploration budget — max steps, max time, max cost per exploration episode before hard-escalate to HITL; (4) pathway synthesis — how the agent converts a multi-step exploration sequence into a reusable KB entry (LLM summarization vs. deterministic action log serialization); (5) KB injection format — new `navigation_pathway` field in human_guidance.md entries, with `trigger_condition`, `steps` array, `target_element`, and `confidence_score`; (6) VQAState schema changes — `exploration_active`, `exploration_steps`, `exploration_target`, `exploration_outcome` fields; (7) idempotency — deduplication strategy to prevent KB bloat when the same pathway is discovered across multiple runs. Phased implementation: Phase 1 — Exploration State Machine (trigger logic, strategy dispatcher, budget enforcer, VQAState schema); Phase 2 — Exploration Executor (scroll-to-reveal, expand-collapsed-parent, click-sibling-tab strategies with Playwright integration); Phase 3 — Pathway Synthesis & KB Injection (LLM-based synthesis prompt, human_guidance.md writer, deduplication); Phase 4 — Reporter Integration (exploration episodes surfaced in HTML audit report with distinct "🔍 Explored" step styling). Success metrics: ≥ 70% of "element not found" escalations resolved by Exploration Mode without HITL, KB self-heal injection rate ≥ 60% of successful explorations (pathway injected and verified on re-run), HITL escalation rate reduction ≥ 40% compared to current baseline, exploration overhead ≤ 8 additional steps per episode.
- **Linked Tasks**: exploration-mode-and-autonomous-kb-self-heal (COMPLETE)
- **Branch**: feature/FEAT-040-exploration-mode-kb-self-heal
- **Created**: 2026-05-16
- **Completed**: 2026-05-18 ✅
