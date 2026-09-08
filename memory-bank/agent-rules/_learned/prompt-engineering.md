---
name: Prompt Engineering Patterns
globs: ["backend/engine/prompts.py", "backend/engine/ac_parser.py"]
paths: ["backend/engine/"]
topics: ["llm", "prompts", "engineering", "bdd", "detection", "pipeline"]
priority: high
auto_generated: true
evidence_count: 8
last_reinforced: 2026-07-14
source_tasks: ["TASK-076", "TASK-078", "TASK-079", "TASK-099", "TASK-106", "TASK-122"]
derived_from: []
last_validated: 2026-07-22
---


# Prompt Engineering Patterns

Strategies for optimizing LLM reasoning and structured data emission through system prompts.

- **Prompt Audit Checklist Standard**: All prompt modifications must pass the checklist in `knowledge/prompt_audit_checklist.md`. This ensures that changes are evaluated against objective criteria (anchoring, delimiters, few-shot) rather than subjective performance impressions.
- **Hierarchical Anchoring**: Anchor critical "Golden Rules" at both the START (Primacy) and END (Recency) of system prompts. This mitigates "lost-in-the-middle" syndrome where instructions in the center of a long prompt (especially one containing large DOM/ARIA trees) are ignored.
- **Atomic BDD Decomposition**: Force the BDD Normalizer (Stage 1) to split compound Jira actions ("click then select") into separate "When" steps. This keeps the See-Think-Act loop granular and prevents the planner from attempting to bundle multiple interactions into a single action, which is a frequent source of executor failure.
- **Sub-step Emission Guidance**: Provide clear examples in the JSON Compiler (Stage 2) prompt for when to emit `sub_steps` vs separate steps. Use a specific marker (e.g., `<!-- COMPOSITE: ... -->`) from Stage 1 to trigger this emission, ensuring consistency across the two-stage parsing pipeline.
- **Contradiction Detection via Static Analysis**: Priority conflicts in system prompts (e.g., two "HIGHEST PRIORITY" rules) are a testable structural property. Add `assert prompt.count("HIGHEST PRIORITY") <= 1` as a unit test for any prompt that uses priority markers. Run this in `tests/test_prompt_structure.py` rather than relying on qualitative review. Source: TASK-079.
- **Fragment Library Compound Value**: Every new system prompt MUST import `GOLDEN_RULES` and `CRITICAL_REMINDER` from `backend/engine/prompt_fragments.py` rather than inlining its own anchoring text. The cost of structural hardening is O(1) once the fragment library exists; duplicating anchoring text inline makes future updates require touching every prompt file. Source: TASK-079.
- **Cardinality Sentinel Markers**: When transforming complex structural data (like tables or arrays) for an LLM parser, prefix the output with explicit cardinality sentinels (e.g., `[AC TABLE: N rows]`). This gives the system prompt clear hooks to enforce cardinality constraints and prevent output collapse.
- **a11y-tree-prompt-injection**: When generating element interaction specifications (e.g., Playwright tests) using LLMs, inject the pruned accessibility tree (ARIA snapshot) into the prompt context. This informs the LLM of semantic node boundaries and interactive roles, allowing it to generate highly precise `page.getByRole()` queries and avoid fragile text or structural DOM queries. Source: TASK-106.
- **Pre-Pipeline Detection Over LLM Call**: When adding detection fields (e.g., `detected_paths`) to an existing LLM pipeline response, use a pre-pipeline regex scan on raw input text rather than a new LLM call — for format-consistent structural markers (like `>` navigation paths) this adds zero latency, zero cost, and higher precision than post-normalization extraction; reserve a new LLM call only when implicit or context-dependent patterns must be detected. Source: TASK-122.

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Prompt Audit Checklist Standard | [TASK-078.md](../tasks/TASK-078.md) | 2026-05-29 |
| Hierarchical Anchoring | [TASK-078.md](../tasks/TASK-078.md) | 2026-05-29 |
| Atomic BDD Decomposition | [TASK-076.md](../tasks/TASK-076.md) | 2026-05-29 |
| Contradiction Detection via Static Analysis | [TASK-079.md](../tasks/TASK-079.md) | 2026-05-29 |
| Fragment Library Compound Value | [TASK-079.md](../tasks/TASK-079.md) | 2026-05-29 |
| Cardinality Sentinel Markers | [reflection-TASK-099.md](../reflection/reflection-TASK-099.md) | 2026-06-03 |
| Accessibility Tree Prompt Injection | [reflection-TASK-106.md](../reflection/reflection-TASK-106.md) | 2026-06-05 |
| Pre-Pipeline Detection Over LLM Call | [reflection-TASK-122.md](../reflection/reflection-TASK-122.md) | 2026-07-14 |
