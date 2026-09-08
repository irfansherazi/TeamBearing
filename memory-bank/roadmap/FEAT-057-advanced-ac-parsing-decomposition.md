---
legacy_id: FEAT-057
version: v3.0.0
linked_tasks: [advanced-ac-parsing-and-decomposition]
status: complete
---

### FEAT-057: Advanced AC Parsing & Decomposition
- **Version**: v3.0.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Standardize the transition from Jira ADF to executable test plans by fixing extraction artifacts and logic:
    1. **ADF Inline Mark Fix**: Fix word fusion at mark boundaries in `jira/client.py` that produces malformed AC text (e.g., "log in asAccount Executive"). Improve table row handling and verify via `reproduce_jira_parsing.py`.
    2. **Atomic Step Decomposition**: Update the BDD Normalizer prompt to split compound Jira actions ("click then select") into separate atomic steps. Add optional `sub_steps` to the TestStep schema so the executor only performs a full verification check after the final sub-action in a compound sequence completes.
- **Linked Tasks**: advanced-ac-parsing-and-decomposition
- **Branch**: feature/FEAT-057-advanced-parsing
- **Created**: 2026-05-29
