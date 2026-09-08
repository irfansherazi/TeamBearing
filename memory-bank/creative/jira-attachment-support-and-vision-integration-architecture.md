# jira-attachment-support-and-vision-integration Architecture Design: Jira Attachment Support & Vision Integration

**Created**: 2026-05-20
**Task**: jira-attachment-support-and-vision-integration
**Feature**: FEAT-045
**Phase**: CREATIVE — Architecture Design
**Status**: COMPLETE

---

## Decision

**Chosen**: Option A — Decoupled Vision Analyzer Service

A new `VisionAnalyzer` class will be implemented in `backend/engine/vision_analyzer.py` to handle the interaction with the Vision LLM (Claude 3.5 Sonnet via Bedrock). The `JiraClient` will be extended to support attachment retrieval and downloading. The `ac_parser_node` will act as the orchestrator, fetching attachments, triggering analysis, and injecting the resulting context into the existing parsing pipeline.

---

## Component Diagram

```
┌─────────────────┐       ┌──────────────────────┐       ┌────────────────────┐
│   Jira API      │◄─────╼│      JiraClient      │◄─────╼│    ACParserNode    │
└─────────────────┘       │ (client.py)          │       │ (ac_parser.py)     │
                          └──────────┬───────────┘       └──────────┬─────────┘
                                     │                              │
                                     │ download_attachment()        │ analyze & inject
                                     ▼                              ▼
                          ┌──────────────────────┐       ┌────────────────────┐
                          │    Jira Attachments  │       │   VisionAnalyzer   │
                          │   (Raw Bytes)        │──────╼│ (vision_analyzer.py)│
                          └──────────────────────┘       └──────────┬─────────┘
                                                                    │
                                                                    ▼
                                                         ┌────────────────────┐
                                                         │   Bedrock API      │
                                                         │ (Claude 3.5 Sonnet)│
                                                         └────────────────────┘
```

---

## Detailed Component Design

### 1. JiraClient Extension (`backend/jira/client.py`)

- **Field Query**: Update `fields` in `fetch_ticket_context` to include `"attachment"`.
- **`download_attachment(attachment_id: str) -> bytes`**:
    - Uses the Jira `attachment/content/{id}` endpoint.
    - Handles authentication and binary streaming.
    - Returns raw bytes for vision analysis.

### 2. VisionAnalyzer (`backend/engine/vision_analyzer.py`) [NEW]

- **`analyze_image(image_bytes: bytes, mime_type: str, ac_text: str) -> str`**:
    - Wraps Bedrock `invoke_model` call.
    - **Model**: `anthropic.claude-3-5-sonnet-20240620-v1:0`.
    - **Prompt**:
        - System: "You are a QA Visual Analyst. Analyze the provided Jira attachment in the context of the Acceptance Criteria."
        - User: [Image] + "Acceptance Criteria: {ac_text}. Identify UI labels and components shown in this image that relate to the AC."
    - **Output**: A text summary of visual facts.

### 3. ACParserNode Orchestration (`backend/engine/ac_parser.py`)

- **`_get_visual_context(state: VQAState) -> str`**:
    - Logic to:
        1. Extract attachment metadata from `state["jira_ticket"]["attachments"]`.
        2. Filter for images (`image/png`, `image/jpeg`).
        3. For top 3 images:
            - Call `JiraClient.download_attachment()`.
            - Call `VisionAnalyzer.analyze_image()`.
        4. Join all summaries into a single string.
- **`_stage_1_normalize`**:
    - Call `_get_visual_context` before generating the prompt.
    - Inject into `BDD_NORMALIZER_PROMPT` using the `{visual_context}` placeholder.

### 4. State Schema Update (`backend/engine/state.py`)

- **`JiraTicketContext`**: Add `attachments: list[dict]`.
- **`VQAState`**: Add `visual_context: str` (optional).

---

## Data Flow: Attachment Integration

1. **Jira Fetch**: `ac_parser_node` starts → calls `JiraClient.fetch_ticket_context()`.
2. **Context Storage**: `VQAState["jira_ticket"]` now contains attachment metadata.
3. **Parallel Analysis**: `ac_parser_node` identifies relevant images and launches parallel `analyze_image` tasks.
4. **Summary Collection**: Results are aggregated into `VQAState["visual_context"]`.
5. **Prompt Construction**: `BDD_NORMALIZER_PROMPT` is formatted with `ac_text` AND `visual_context`.
6. **Normalization**: LLM produces BDD scenarios grounded in visual reality.

---

## Implementation Traceability

| Work Item | Component | File |
|---|---|---|
| WI-047-001 | `JiraClient` | `backend/jira/client.py`, `backend/engine/state.py` |
| WI-047-002 | `VisionAnalyzer` | `backend/engine/vision_analyzer.py` (New) |
| WI-047-003 | `ACParserNode` | `backend/engine/ac_parser.py` |
| WI-047-004 | `Prompts` | `backend/engine/prompts.py` |
