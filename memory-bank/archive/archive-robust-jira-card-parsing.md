# Archive: Robust Jira Card Parsing

## Metadata
- Task ID: robust-jira-card-parsing
- Complexity: Level 2
- Completed: 2026-05-20
- Feature: FEAT-045

## Summary
Improved the reliability of the Jira-to-Test-Plan ingestion pipeline by handling project-specific custom fields for Acceptance Criteria (AC), expanding Atlassian Document Format (ADF) parsing to include media and application cards, and implementing strict guardrails to prevent ephemeral UI element selection.

## Solution
- **Jira Client**: Added fallback custom field IDs (`customfield_10010`) and expanded `_extract_text_from_adf` to support `mediaGroup` and `applicationCard` nodes.
- **AC Parser**: Enhanced self-correction loop with targeted "repair hints" for transient selectors (e.g., `.active`).
- **Prompts**: Updated `JSON_COMPILER_PROMPT` with a strict "FORBIDDEN SELECTORS" list and tightened `BDD_NORMALIZER_PROMPT` for table handling.

## Files Changed
- `backend/jira/client.py` - Added fallback fields and expanded ADF node support.
- `backend/engine/ac_parser.py` - Improved error feedback and self-correction hints.
- `backend/engine/prompts.py` - Added "FORBIDDEN SELECTORS" list and tightened normalization rules.
- `tests/test_jira_fallbacks.py` - New unit tests for multi-field AC ingestion.
- `tests/test_adf_new_nodes.py` - New unit tests for expanded ADF node types.

## Lessons Learned
- **Persistent State > Transient State**: Automated browser testing should focus on persistent side-effects rather than ephemeral UI elements.
- **Error Feedback Quality**: Effective LLM self-correction requires specific, actionable error feedback rather than vague failure messages.

## Learned Rules Consolidated
- `memory-bank/agent-rules/_learned/jira-robustness.md` - Documented strategies for reliable Jira data extraction.
