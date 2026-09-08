# Reflection: robust-jira-card-parsing - Robust Jira Card Parsing

## Summary
The primary goal of robust-jira-card-parsing was to improve the reliability of the Jira-to-Test-Plan ingestion pipeline. This involved handling project-specific custom fields for Acceptance Criteria (AC), expanding Atlassian Document Format (ADF) parsing to include media and application cards, and implementing strict guardrails to prevent the LLM from selecting ephemeral UI elements (like `.active` classes) that cause validation failures and infinite loops.

## What Went Well
- **Multi-layered Guardrails**: Combining prompt-level "forbidden" lists with code-level validation hints created a robust self-correction loop.
- **TDD for Ingestion**: New unit tests (`test_jira_fallbacks.py`, `test_adf_new_nodes.py`) successfully simulated complex Jira payloads, ensuring parsing logic remains stable.
- **Graceful Fallbacks**: The implementation of AC field fallbacks (`customfield_10031` -> `customfield_10010`) makes the system more resilient to variations in Jira project configurations.

## Challenges
- **Transient Selector Hallucination**: The LLM frequently defaulted to `.active` selectors because they appear in the DOM during interaction.
  - **Resolution**: Implemented a targeted "repair hint" in `ac_parser.py` that explains *why* the selector is invalid and suggests persistent alternatives (e.g., checking for wrapper classes).
- **ADF Complexity**: Atlassian's ADF format is deeply nested and contains many optional node types.
  - **Resolution**: Expanded the recursive parser to include `mediaGroup` and `applicationCard`, while maintaining a graceful fallback for unknown types to prevent crashes.

## Lessons Learned
- **Persistent State > Transient State**: In automated browser testing, verifying a "selection" should always focus on the persistent side-effects (e.g., a class on a parent container or a URL change) rather than the ephemeral UI elements used to make the selection.
- **Error Feedback Loop Quality**: The effectiveness of LLM self-correction is directly proportional to the specificity of the error feedback. Vague "validation failed" messages lead to poor retries, whereas "transient selector detected; use wrapper class X instead" leads to immediate repair.

## Action Items
- Monitor logs for new Jira custom field IDs that might contain AC; consider making the fallback list configurable via environment variables.
- Periodically update the "FORBIDDEN SELECTORS" list in `prompts.py` as new ephemeral UI patterns are discovered in the target applications.

## Claude Code Ecosystem Observations

### What Worked Well
- **VC Workflow Commands**: `/vc-plan` and `/vc-build` provided a clear structure for this Level 2 task, ensuring that documentation and tests were not overlooked.
- **Grep/Glob Tools**: These were essential for identifying all locations where Jira fields and ADF parsing logic were defined.

### Friction Points
- **Recursive ADF Parsing Debugging**: Visualizing deeply nested ADF structures in terminal logs can be difficult.
  - **Suggestion**: A utility to "pretty-print" ADF structures during local development or in `DEBUG` logs would be beneficial.

### Suggestions for Improvement
> **Note**: These are suggestions only. Do NOT implement changes.

- **Dynamic Fallback Registry**: Instead of hardcoding field fallbacks in `client.py`, implement a discovery mechanism or an environment variable `JIRA_AC_FIELDS=10031,10010` to allow for project-specific overrides without code changes.
- **Selector Validator Utility**: Extract the "transient selector" check into a shared utility that can be used across different parsing nodes or even in a pre-commit hook for test plans.
