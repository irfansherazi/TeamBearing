---
name: Jira Ingestion Robustness
globs: ["backend/jira/client.py"]
paths: ["backend/jira/"]
topics: ["jira", "ingestion", "robustness"]
priority: medium
auto_generated: true
evidence_count: 4
last_reinforced: 2026-06-03
source_tasks: ["TASK-046", "TASK-047", "TASK-058", "TASK-099"]
derived_from: []
last_validated: 2026-07-22
---


# Jira Ingestion Robustness

Strategies for ensuring reliable data extraction from varied Jira project configurations.

- **Configurable Board IDs**: Jira Agile API board IDs MUST be configurable via environment variables (e.g., `JIRA_BOARD_IDS`) and not hardcoded. Board IDs are specific to the environment and board view, not just the project.
- **Multi-Field Fallback Registry**: When extracting key data (like Acceptance Criteria) from Jira custom fields, implement a priority-ordered list of field IDs (e.g. `customfield_10031` -> `customfield_10010`). Field IDs vary across projects even for the same logical purpose.
- **ADF Node Flattening**: Recursive ADF-to-text parsers should support layout nodes (`mediaGroup`, `applicationCard`) to prevent data loss in tickets containing embedded media or rich links.
- **Embedded Media Fallback**: Scan ADF document nodes for `media` and `mediaSingle` types even if the top-level `attachment` array is empty, as users often paste screenshots directly into descriptions.
- **ADF Mark Boundary Spacing**: When extracting text from ADF, ensure spaces are injected between adjacent text nodes if neither has whitespace at the boundary. Sibling text nodes often lack whitespace when separated by "marks" (bold, code, link) in Atlassian Document Format.
- **ADF Table Row Pipe Separator**: Use a pipe separator (` | `) when joining table cell content during ADF extraction. This preserves tabular structure for the downstream BDD normalizer, preventing data fusion in multi-column rows.
- **Field Discovery Logging**: Always log which specific custom field was successfully used for ingestion to aid in debugging missing-context issues across different environments.
- **Recursive Parser Exclusions**: When implementing a custom recursive handler for a complex node type (like `table`), exclude that node type from the default recursion lists or fallback paths to avoid duplicate processing and maintain container boundary isolation.

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Configurable Board IDs | [reflection-TASK-058.md](../reflection/reflection-TASK-058.md) | 2026-05-27 |
| ADF media nodes | [reflection-TASK-047.md](../reflection/reflection-TASK-047.md) | 2026-05-21 |
| Recursive Parser Exclusions | [reflection-TASK-099.md](../reflection/reflection-TASK-099.md) | 2026-06-03 |
