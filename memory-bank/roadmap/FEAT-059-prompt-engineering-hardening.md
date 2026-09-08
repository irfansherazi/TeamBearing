---
legacy_id: FEAT-059
version: v3.0.0
linked_tasks: [prompt-engineering-hardening-feat-059]
status: complete
---

### FEAT-059: Prompt Engineering Hardening
- **Version**: v3.0.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Harden all LLM system prompts in the vQA engine against known failure modes. Key improvements:
    1. **Anchor Critical Rules**: Address "lost in the middle" syndrome by anchoring critical constraints at both the START and END of system prompts in `planner.py`, `verifier.py`, `verifier_node.py`, `ac_parser.py`, and `prompts.py`.
    2. **Structured Delimiters**: Use XML/markdown blocks (e.g., `<RULES>`, `<CONTEXT>`, `<EXAMPLES>`) to clearly separate instructions from dynamic context.
    3. **Few-Shot & CoT**: Add few-shot examples for PrimeNG sorting re-renders and p-select dropdowns; implement explicit chain-of-thought scaffolding for unreliable decision points.
    4. **Audit Standard**: Establish a prompt audit checklist as a dev standard for future prompt modifications.
- **Linked Tasks**: prompt-engineering-hardening-feat-059
- **Branch**: feature/FEAT-059-prompt-hardening
- **Created**: 2026-05-29
- **Completed**: 2026-05-29 ✅
