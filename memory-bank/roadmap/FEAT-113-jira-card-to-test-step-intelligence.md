---
legacy_id: FEAT-113
version: next
linked_tasks: [jira-card-to-test-step-intelligence]
status: complete
---

### FEAT-113: Jira Card to Test Step Intelligence
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Three targeted improvements to the Jira card → test step generation pipeline that dramatically increase the quality and specificity of generated test steps.
    1. **Prompt Engineering — Navigation Path Parsing & Assertion Splitting**: Update `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` in `backend/engine/prompts.py` to (a) recognize `>` delimited navigation strings (e.g. `HDah>Module Abilities>Edit Module`) as distinct test scenario groups rather than collapsing them into a single generic loop, and (b) decompose compound bug descriptions ("does not close AND fields are not cleared") into separate, verifiable assertions.
    2. **Video Analysis — MP4 Attachment Support**: Extend `VisionAnalyzer` and `_fetch_visual_context_from_attachments` in `backend/engine/ac_parser.py` to handle `.mp4` attachments by extracting key frames via ffmpeg and running them through the vision model. Currently only PNG/JPEG/PDF are supported; video files attached to Jira cards are silently skipped.
    3. **Clarification Wizard UI**: Add a new React modal (`ClarificationWizardModal.tsx`) that intercepts between `/preview-steps` response and test execution. The wizard shows the AI-parsed navigation paths, assertion list, and surfaces ambiguities (unknown paths, missing test data) for user confirmation or correction before the run starts.
- **Acceptance Criteria**:
    - AC-1: A Jira card description containing 3 `>` delimited paths generates 3 distinct scenario blocks in the TestPlan, not a single repeated block.
    - AC-2: A bug description with two behaviors ("does not close AND does not clear fields") produces two separate `StructuredACStep` entries with independent verification assertions.
    - AC-3: An `.mp4` attachment on a Jira card is frame-extracted (≥3 frames) and the visual context from those frames is included in the BDD normalizer prompt.
    - AC-4: The Clarification Wizard modal appears after `/preview-steps` and lists detected navigation paths with checkboxes (include/exclude) and surfaced ambiguities.
    - AC-5: User edits in the wizard (path toggles, test data inputs) are serialized into the `pre_parse_guidance` passed to the next execution, and the updated steps reflect the user's selections.
- **Key Files**:
    - `backend/engine/prompts.py` — `BDD_NORMALIZER_PROMPT`, `JSON_COMPILER_PROMPT`
    - `backend/engine/vision_analyzer.py` — `VisionAnalyzer.analyze_image()`, add `analyze_video()`
    - `backend/engine/ac_parser.py` — `_fetch_visual_context_from_attachments()`, `_rank_attachments()`
    - `frontend/src/components/ClarificationWizardModal.tsx` (New) — wizard UI
    - `frontend/src/components/SelectView.tsx` — wire wizard between preview and run
- **Linked Tasks**: jira-card-to-test-step-intelligence
- **Branch**: feature/FEAT-113-jira-card-intelligence
- **Created**: 2026-07-14
