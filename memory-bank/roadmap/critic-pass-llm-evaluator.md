---
version: next
status: completed
priority: medium
complexity: 3
linked_tasks:
  - critic-pass-llm-evaluator
created: 2026-07-30
completed: 2026-07-30
parent_feature: agentic-testing-sota-adoption-2026
---

# Critic-Pass LLM Evaluator

Insert a small LLM critic pass between Stage 2 (TestPlan compilation) and execution that re-reads the acceptance criteria + compiled TestPlan and flags mismatches before we spend browser time. Mirrors the Playwright Healer / Anthropic Skill Creator test-measure-refine loop.

## Motivation

vQA today has a static heuristic ambiguity-detection pass but no LLM critic re-scoring the compiled plan against the AC. The compiled TestPlan can drift from the AC (missing steps, hallucinated success criteria, wrong persona, misordered actions) and today we only detect this at execution time — after the browser has already run steps. A cheap Haiku pass at plan-compile time catches these before any browser work happens, and gives the planner structured feedback to regenerate rather than a hard failure.

Promoted from candidate #1 of the [2026 agentic-testing SOTA adoption umbrella](./agentic-testing-sota-adoption-2026.md).

## In scope

- New engine node between Stage 2 (`ac_parser` / TestPlan compilation) and Stage 3 (executor loop)
- Haiku model (per model-selection-strategy — small task, structured output)
- Verdict schema: `pass` | `mismatch` with typed reasons (missing_step, hallucinated_ac, persona_mismatch, order_violation, ambiguous_step)
- Feedback loop: on `mismatch`, structured reasons feed back into the planner for one retry pass
- Bounded retries (max 2 critic-planner cycles per AC) to prevent loops
- Observability: emit critic verdict + reason codes to the run report

## Out of scope

- Post-execution critic (that's candidate #8, self-healing recovery router — separate feature)
- Rewriting `ac_parser` or the executor
- Human-in-the-loop escalation from the critic (uses existing HITL if the critic-planner loop exhausts retries)
- Changes to the AC parsing itself (candidate #4, domain plugin registry, is separate)

## References

- Anthropic Skill Creator test-measure-refine loop (Mar 2026)
- Playwright Healer agent (v1.56)
- Existing vQA nodes: `backend/engine/verifier.py`, `backend/engine/preflight_check.py`, `backend/engine/recovery_router.py`, `backend/kb/preflight.py`

**Complexity rationale**: Level 3 — adds one new LLM node with a defined contract, integrates with 2-3 existing engine files, requires deliberate design of the verdict schema and retry protocol (design decisions), but is not system-wide (does not touch UI, storage layer, or the executor loop's core state machine). If the retry protocol turns out to require formal design (e.g. cycle detection, verdict-to-planner-feedback grammar), promote to L4 during planning.
