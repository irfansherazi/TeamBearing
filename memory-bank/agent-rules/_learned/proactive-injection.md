---
name: Proactive Context Injection
globs: ["backend/engine/*.py", "backend/kb/*.py"]
paths: ["backend/engine/", "backend/kb/", "knowledge/"]
topics: ["prompt-engineering", "hallucination-reduction", "dropdown-options"]
priority: low
auto_generated: true
evidence_count: 2
last_reinforced: 2026-05-15
source_tasks: ["TASK-013", "TASK-015"]
derived_from: []
last_validated: 2026-07-22
---


# Proactive Context Injection

Inject known-good values into LLM prompts proactively — before the model encounters the element — to prevent hallucinated option names.

- **Static Registry Pattern**: Maintain a JSON registry (e.g., `dropdown_options.json`) mapping field names to their valid option lists. Load at startup; match via case-insensitive substring of the AC step text.
- **Prompt Injection Format**: Use a visually distinct block (emoji header + separator lines) so the LLM can distinguish ground-truth values from general instructions.
- **Applicability**: Any domain where the valid option set is finite and pre-enumerable — dropdowns, radio groups, status fields, role selectors.
- **Force-Click Fallback**: When Playwright clicks are intercepted by overlays (CDK, PrimeNG modals), retry with `force=True` before escalating. Track which fallback was used via a typed `ClickResult` dataclass for auditing.
- **Verbatim Grounding**: Implement strict verbatim grounding constraints in system prompts to prevent LLM hallucinations when interacting with dynamic UI components. (Source: reflection-TASK-015)
