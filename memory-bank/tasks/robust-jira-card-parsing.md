---
legacy_id: robust-jira-card-parsing
---
# robust-jira-card-parsing: Robust Jira Card Parsing

**Status**: COMPLETE
**Phase**: DONE
**Complexity**: Level 2
**Created**: 2026-05-20
**Roadmap Link**: N/A
**Branch**: main

---

## Summary

Some Jira cards were failing to parse properly into structured test plans, often due to non-standard formatting (tables, nested lists), the use of transient CSS selectors in the compiled plan, or the use of project-specific custom fields for Acceptance Criteria. This feature improves the robustness of the two-stage parsing pipeline by tightening prompt guardrails, expanding field fallback logic, and enhancing ADF parsing capabilities.

---

## Specification

### Invocation Location
- **Jira Client**: `backend/jira/client.py` handles ticket fetching and ADF parsing.
- **AC Parser Node**: `backend/engine/ac_parser.py` orchestrates the two-stage parsing.
- **Prompts**: `backend/engine/prompts.py` contains the system instructions for normalization and compilation.

### Success Criteria
- Jira tickets using custom fields other than `customfield_10031` for AC are correctly ingested.
- The ADF parser handles `mediaGroup` and `applicationCard` nodes without data loss.
- The LLM compiler avoids generating "forbidden" transient selectors (e.g., `.active`) that fail Pydantic validation.
- Complex Jira tables and list structures are correctly normalized into BDD scenarios.

### Data Persistence
- None (logic and prompt improvements).

---

## Acceptance Criteria

### AC-HAPPY-1: Multi-Field AC Ingestion
**Priority**: MUST

**Given** a Jira ticket where Acceptance Criteria is stored in `customfield_10010`
**When** the agent fetches the ticket
**Then**:
  - The client successfully identifies and extracts the AC from the fallback field
  - The agent logs which field was used for ingestion

**Verification**:
- [x] Unit test: `tests/test_jira_fallbacks.py` verifies fallback field priority and extraction.

### AC-HAPPY-2: Robust ADF Parsing
**Priority**: MUST

**Given** a Jira AC field containing `mediaGroup` or `applicationCard` ADF nodes
**When** the ADF-to-text converter runs
**Then**:
  - The converter extracts text from these nodes instead of skipping them or crashing
  - Media filenames are preserved in the text output

**Verification**:
- [x] Unit test: `tests/test_adf_new_nodes.py` verifies support for these node types.

### AC-HAPPY-3: Forbidden Selector Guardrails
**Priority**: MUST

**Given** the Stage 2 JSON Compiler is generating a test plan
**When** the LLM attempts to use a transient selector like `.active` or `p-menu-overlay`
**Then**:
  - Pydantic validation rejects the plan
  - The self-correction loop provides a targeted hint about forbidden selectors
  - The LLM successfully repairs the plan on retry using a persistent marker

**Verification**:
- [x] Prompt update in `prompts.py` includes strict forbidden list.
- [x] Error feedback in `ac_parser.py` includes specific hints for transient selector failures.

---

## Component Analysis

### Affected Components

| Component | File | Change |
|---|---|---|
| `JiraClient` | `backend/jira/client.py` | Added fallback field IDs and expanded ADF node support. |
| `ACParserNode` | `backend/engine/ac_parser.py` | Improved error feedback and self-correction hints. |
| `Prompts` | `backend/engine/prompts.py` | Tightened rules for table handling and added "FORBIDDEN SELECTORS" list. |

---

## Implementation Strategy

### Phase 1 — Jira Client & ADF Enhancements
**Goal**: Ensure all relevant data is captured from Jira.

1. Add fallback custom fields to `fetch_ticket_context`.
2. Expand `_extract_text_from_adf` to support more node types.

### Phase 2 — Prompt Engineering & Self-Correction
**Goal**: Improve the quality and validity of the compiled test plans.

1. Update `BDD_NORMALIZER_PROMPT` for table and scenario outline support.
2. Update `JSON_COMPILER_PROMPT` with forbidden selector list.
3. Add targeted validation hints to `ac_parser.py`.

---

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| **Field Name Changes** | Jira custom field IDs vary by project. **Mitigation**: We check a list of common IDs and log the successful match. |
| **LLM Hallucination** | LLM might ignore prompt rules. **Mitigation**: Strict Pydantic validators in `schemas.py` enforce the rules and trigger retries. |

---

## Observability Requirements

- **Logs**:
  - `INFO`: `"[JiraClient] Found AC in Jira field 'customfield_10010'"`
  - `WARNING`: `"[ACParser] Transient selector detected in Stage 2 attempt 1. Providing repair hint."`

---

## Work Items

### WI-046-001: Jira Ingestion Robustness
**Status**: Complete
**Completed**: 2026-05-20
**Implementation**: Updated `client.py` with fallback fields and new ADF node handlers.

### WI-046-002: Prompt & Parsing Quality
**Status**: Complete
**Completed**: 2026-05-20
**Implementation**: Updated `prompts.py` and `ac_parser.py` with strict guardrails and improved feedback.

---

## Test Strategy

| Test File | Coverage |
|---|---|
| `tests/test_jira_fallbacks.py` | Multi-field AC ingestion logic |
| `tests/test_adf_new_nodes.py` | Expanded ADF node type support |
| `tests/test_adf_parser.py` | (Existing) Core ADF parsing logic |

---

## Validation Gate ✅

- [x] Fallback fields correctly ingested.
- [x] New ADF nodes correctly flattened.
- [x] Forbidden selectors blocked by Pydantic.
- [x] Self-correction loop successfully provides repair hints.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: DONE
**Can Resume**: NO
**Completed Phases**: PLAN, Phase 1, Phase 2, REFLECT
**Phase Being Built**: N/A
**Phase Number**: 2 of 2
**Is Multi-Phase**: YES
**Build Started**: 2026-05-20T12:30:00-05:00
**Build Completed**: 2026-05-20T13:30:00-05:00

### Completed Steps
- Step 1 Research: COMPLETE
- Step 2 Implementation: COMPLETE
- Step 3 Verification: COMPLETE
- Step 4 Reflection: COMPLETE
- Step 5 Archive: COMPLETE
