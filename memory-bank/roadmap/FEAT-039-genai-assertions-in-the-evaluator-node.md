---
legacy_id: FEAT-039
version: next
linked_tasks: []
status: planned
---

### FEAT-039: GenAI Assertions in the Evaluator Node
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Vague Jira ACs often include non-deterministic validation steps like "Ensure the dashboard looks correct" or "Verify the chart shows data." Traditional DOM/ARIA locators cannot validate these semantically. This feature implements "GenAI Assertions" in the Evaluator node. Instead of writing code to verify state, the vQA Evaluator passes the final post-action screenshot and the natural language assertion text directly to the LLM (Tier 1 — Claude Sonnet). The model acts as a visual QA analyst, returning a deterministic Pass/Fail verdict with human-readable reasoning grounded in visual semantics rather than DOM structure. Design decisions required: (1) assertion routing — how the AC parser tags steps as `dom_assertion` vs. `genai_assertion` (keyword heuristics vs. LLM pre-classifier); (2) vision prompt schema — how the screenshot and assertion are packaged (system role as QA analyst, structured JSON response with `verdict`, `confidence`, `reasoning`); (3) cost gate strategy — only invoke vision LLM after DOM/ARIA verification has no applicable locator (not on every step); (4) confidence threshold — minimum confidence score for auto-PASS vs. HITL escalation for borderline visual assertions; (5) integration point in the evaluator routing graph — new `genai_assertion_node` branch or inline within the existing verifier. Success metrics: genai assertions resolve ≥ 80% of previously-unverifiable AC steps without HITL escalation, vision invocation rate ≤ 15% of total AC steps, zero false-PASS verdicts on clearly incorrect UI states (validated by manual review of 20 diverse assertions).
- **Linked Tasks**: None
- **Branch**: feature/FEAT-039-genai-assertions
- **Created**: 2026-05-16
