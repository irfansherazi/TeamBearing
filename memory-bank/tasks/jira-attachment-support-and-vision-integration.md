---
legacy_id: jira-attachment-support-and-vision-integration
---
# jira-attachment-support-and-vision-integration: Jira Attachment Support & Vision Integration

**Status**: COMPLETE
**Reflection**: memory-bank/reflection/reflection-jira-attachment-support-and-vision-integration.md
**Phase**: ARCHIVE
**Complexity**: Level 4
**Created**: 2026-05-20
**Roadmap Link**: [FEAT-045](roadmap.md#feat-045-jira-parsing--attachment-support)
**Branch**: feature/FEAT-045-jira-attachments

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE
**Is Multi-Phase**: YES
**Build Started**: 2026-05-20T14:40:00-05:00
**Current Build Step**:
  Step: Step 5 - Report Completion
  Status: COMPLETE
  Started: 2026-05-21T10:05:00-05:00
**Can Resume**: NO

### Active Sub-Agents
- Test Writer Agent: COMPLETE
- Coding Agent: COMPLETE
- Reflection Agent: COMPLETE

### Completed Steps
- [x] Step 0: Parse Task ID
- [x] Step 0.5: Git Setup (Worktree created: .worktrees/jira-attachment-support-and-vision-integration)
- [x] Step 0.6: Phase Gate (Creative docs generated)
- [x] User Journey Design: COMPLETE (memory-bank/creative/jira-attachment-support-and-vision-integration-user-journey.md)
- [x] Architecture Design: COMPLETE (memory-bank/creative/jira-attachment-support-and-vision-integration-architecture.md)
- [x] Algorithm Design: COMPLETE (memory-bank/creative/jira-attachment-support-and-vision-integration-algorithm.md)
- [x] Phase 1: Jira Attachment Retrieval: COMPLETE (2026-05-20)
- [x] Phase 2: Vision Analysis Engine: COMPLETE (2026-05-20)
- [x] Phase 3: Parser Integration: COMPLETE (2026-05-20)
- [x] Step 3: Reflection Agent: COMPLETE (2026-05-21)
- [x] Step 3.5: Pattern Extraction: COMPLETE (2026-05-21)

---

## Creative Phases

- [x] User Journey Design (Agent: User Journey)
- [x] Architecture Design (Agent: Architecture)
- [x] Algorithm Design (Agent: Algorithm)

---

## Summary

This task implements support for leveraging Jira attachments (images, PDFs) during the test planning phase. By fetching these attachments and analyzing them with Claude 3.5 Sonnet Vision, the agent can gain critical visual context that is often missing from the raw Acceptance Criteria text. This context is then injected into the BDD Normalization stage to produce more accurate and grounded test plans.

---

## Specification

### Invocation Location
- **Jira Client**: `backend/jira/client.py` - Add attachment retrieval and download.
- **Vision Analyzer**: `backend/engine/vision_analyzer.py` (New) - Analyze images via Bedrock.
- **AC Parser Node**: `backend/engine/ac_parser.py` - Orchestrate attachment analysis and inject context into prompts.

### Success Criteria
- vQA successfully identifies and downloads image attachments from Jira tickets.
- Relevant attachments are analyzed by a Vision LLM to extract "Visual Context".
- The "Visual Context" is used by the BDD Normalizer to resolve ambiguities in the AC (e.g., identifying button labels or form fields shown in screenshots).
- The system handles missing or non-image attachments gracefully without failing the run.

### Data Persistence
- Attachment metadata stored in `VQAState["jira_ticket"]["attachments"]`.
- Visual Analysis stored in `VQAState["visual_context"]`.

---

## Acceptance Criteria

### AC-HAPPY-1: Attachment Metadata Extraction
**Priority**: MUST

**Given** a Jira ticket with multiple attachments (PNG, JPG, PDF)
**When** the agent fetches the ticket
**Then**:
  - The `JiraTicketContext` includes a list of attachment metadata (ID, filename, size, mimeType).

**Verification**:
- [ ] Unit test in `tests/test_jira_attachments.py`.

### AC-HAPPY-2: Attachment Content Download
**Priority**: MUST

**Given** a valid attachment ID from a Jira ticket
**When** the `JiraClient` requests the download
**Then**:
  - The raw binary content is returned.

**Verification**:
- [ ] Integration test with mocked Jira API.

### AC-HAPPY-3: Vision Analysis & Context Injection
**Priority**: MUST

**Given** a Jira ticket with a screenshot of a login form
**When** the AC Parser runs
**Then**:
  - The screenshot is analyzed by the Vision model.
  - The analysis (e.g., "Screenshot shows a 'Login' button and 'Email' field") is injected into the BDD Normalizer prompt.
  - The resulting BDD scenario uses the specific terms found in the screenshot.

**Verification**:
- [ ] Simulation script `reproduce_jira_attachment_support.py`.

---

## Component Analysis

### Affected Components

| Component | File | Change |
|---|---|---|
| `JiraClient` | `backend/jira/client.py` | Add `attachment` field to query; add `download_attachment` method. |
| `VisionAnalyzer` | `backend/engine/vision_analyzer.py` | (NEW) Service to analyze attachments via Claude Vision. |
| `ACParserNode` | `backend/engine/ac_parser.py` | Orchestrate analysis and inject context into `_stage_1_normalize`. |
| `Prompts` | `backend/engine/prompts.py` | Update `BDD_NORMALIZER_PROMPT` to support `{visual_context}`. |

---

## Implementation Strategy

### Phase 1 — Jira Attachment Retrieval (COMPLETE)
**Goal**: Enable the agent to see and fetch files from Jira.

1. [x] Update `fetch_ticket_context` to request the `attachment` field.
2. [x] Update `JiraTicketContext` schema in `state.py`.
3. [x] Implement `download_attachment` in `client.py`.

### Phase 2 — Vision Analysis Engine (COMPLETE)
**Goal**: Convert image data into useful textual context for the parser.

1. [x] Implement `VisionAnalyzer` in `backend/engine/vision_analyzer.py`.
2. [x] Configure Bedrock to use Sonnet 3.5 for vision tasks.
3. [x] Handle basic image formats and error cases.

### Phase 3 — Parser Integration & Prompt Engineering (COMPLETE)
**Goal**: Close the loop by using visual context in test planning.

1. [x] Update `ac_parser_node` to trigger analysis.
2. [x] Update `prompts.py` to leverage the new context.
3. [x] Refine prompts based on initial test results.

---

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| **High Token Cost** | Vision analysis can be expensive. **Mitigation**: Only analyze relevant image attachments (filter by mimeType and maybe size); limit max attachments analyzed to 3. |
| **Non-Image Attachments** | PDFs or log files can't be analyzed by vision. **Mitigation**: Filter by mimeType; provide text-based fallbacks for PDFs if possible. |
| **Latency** | Vision API calls add time to the parsing stage. **Mitigation**: Run analysis in parallel if multiple attachments are present. |

---

## Observability Requirements

- **Logs**:
  - `INFO`: `"[JiraClient] Found 2 attachments for ticket QA-239"`
  - `INFO`: `"[VisionAnalyzer] Analyzing screenshot-1.png..."`
  - `INFO`: `"[ACParser] Injected visual context from 1 attachment(s)"`

---

## Work Items

- [x] WI-047-001: Implement Jira attachment metadata & download logic.
- [x] WI-047-002: Create `VisionAnalyzer` for image analysis.
- [x] WI-047-003: Integrate vision context into the AC parsing pipeline.
- [x] WI-047-004: Update prompts and verify with reproduction script.

---

## Test Strategy

| Test File | Coverage |
|---|---|
| `tests/test_jira_attachments.py` | Metadata extraction and download logic |
| `tests/test_vision_analyzer.py` | Mocked vision analysis output |
| `reproduce_jira_attachment_support.py` | End-to-end simulation of vision-assisted parsing |
