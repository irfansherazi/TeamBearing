# Archive: Jira Card to Test Step Intelligence

## Metadata
- **Task ID**: jira-card-to-test-step-intelligence
- **Complexity**: Level 3
- **Roadmap Link**: FEAT-113
- **Branch**: feature/FEAT-113-jira-card-intelligence
- **Started**: 2026-07-14
- **Completed**: 2026-07-14
- **Latest Commit**: dcbb928

## Summary

Three targeted improvements to the Jira card → test step generation pipeline that dramatically increase the quality and specificity of generated test steps. The task originated from a live failure: a real Jira card with three `>` navigation paths was producing three repetitive generic step blocks instead of three distinct scenario groups.

**Deliverable 1 (Prompt Engineering)**: `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` now parse `>` delimited navigation paths as separate test scenario groups and split compound bug descriptions ("does not close AND does not clear fields") into independent verifiable assertions.

**Deliverable 2 (Video Analysis)**: `VisionAnalyzer` now handles `.mp4` Jira attachments by extracting key frames via ffmpeg (stdin-pipe, no disk writes) and running them through the Claude vision model. ffmpeg added to `docker/Dockerfile`.

**Deliverable 3 (Clarification Wizard UI)**: New `ClarificationWizardModal.tsx` component intercepts between `/preview-steps` response and test execution, showing detected navigation paths (include/exclude toggles) and surfaced ambiguities for user confirmation. Serialization logic extracted to `wizardGuidance.ts` for testability.

All 14 acceptance criteria met. 23 unit tests passing across 3 test files. TypeScript build clean.

## Requirements

### Original Requirements
- Parse `>` delimited navigation paths as distinct scenario groups in BDD normalizer
- Split compound bug descriptions into independent assertions in JSON compiler
- Support `.mp4` Jira attachments with ffmpeg frame extraction and vision analysis
- Graceful degradation when ffmpeg is unavailable
- New `ClarificationWizardModal` component with path toggles and ambiguity resolution fields
- Wizard opens automatically for multi-path tickets (Rule B: `detected_paths >= 2 OR ambiguities > 0`)
- Wizard selections serialize into `pre_parse_guidance` on execute
- Extend `PreviewStepsResponse` schema with `detected_paths` and `ambiguities` fields
- WCAG 2.1 AA accessibility for wizard modal

### Success Criteria
- [✓] Multi-path Jira cards produce distinct step groups per navigation path
- [✓] Compound assertions produce separate numbered test steps
- [✓] Single-path cards unaffected (regression-free)
- [✓] MP4 attachments processed via ffmpeg frame extraction + vision model
- [✓] ffmpeg-unavailable path degrades gracefully with warning log
- [✓] Wizard opens for multi-path tickets; skipped for single-path tickets
- [✓] Path exclusions and ambiguity resolutions propagated as `pre_parse_guidance`
- [✓] 23 unit tests passing; TypeScript clean

## Implementation

### Approach

**Schema-first**: Phase 1 established `detected_paths: list[str]` and `ambiguities: list[str]` fields in `PreviewStepsResponse` (backend `schemas.py` + frontend `types/index.ts`) before any UI work — removing integration risk for Phase 3.

**Pre-pipeline detection** (Hybrid Option 4 from creative phase): Paths detected via pre-pipeline regex scan on raw AC text (`_detect_nav_paths()`), not a new LLM call. Ambiguities reuse existing `_detect_step_ambiguity()`. Zero added latency, zero LLM cost.

**In-memory ffmpeg**: `asyncio.create_subprocess_exec` with `PIPE` stdout; PNG stream split on `b'\x89PNG'` magic bytes (with re-prepend fix) — no temp files, no filesystem writes.

**Wizard Rule B trigger**: `detected_paths.length >= 2 OR ambiguities.length > 0`. User confirms → `handleWizardConfirm` re-fetches preview with `buildGuidance()` output injected into `preParseGuidance`. Skip → unmodified steps preserved.

### Key Components

1. **`_detect_nav_paths()` in `backend/engine/ac_parser.py`**
   - Pre-pipeline regex: `\b([A-Za-z][A-Za-z0-9]{0,49}(?:\s*>\s*[A-Za-z][A-Za-z0-9 ]{0,49})+)`
   - Avoids false positives on Markdown blockquotes (`> text`) and operators (`>=`)
   - Wired into all 4 return paths of `ac_parser_node()`

2. **`PreviewStepsResponse` extension in `backend/api/schemas.py` + `frontend/src/types/index.ts`**
   - New fields: `detected_paths: list[str]`, `ambiguities: list[str]`
   - `routes.py` updated to map both fields from `ac_parser_node` output

3. **`BDD_NORMALIZER_PROMPT` + `JSON_COMPILER_PROMPT` in `backend/engine/prompts.py`**
   - Rules 10–11 in BDD normalizer: treat each `>` path as a separate scenario group
   - Rules 6–7 in JSON compiler: split "AND" compound assertions into independent steps

4. **`VisionAnalyzer.analyze_video()` + `_extract_mp4_frames()` in `backend/engine/vision_analyzer.py`**
   - ffmpeg: `image2pipe -vcodec png` mode, stdout piped
   - PNG stream split on `b'\x89PNG'`; each fragment reconstructed as `b'\x89PNG' + chunk`
   - `FileNotFoundError` caught → warning logged, pipeline continues
   - `ac_parser.py` `SUPPORTED_TYPES` extended to include `video/mp4`
   - `docker/Dockerfile` updated with `ffmpeg` in apt-get packages

5. **`ClarificationWizardModal.tsx` in `frontend/src/components/`**
   - Vertical checklist layout (Option 1 per UI/UX creative)
   - Focus trap, Escape-to-skip, WCAG 2.1 AA (`role="dialog"`, `aria-modal`, `aria-labelledby`)
   - `wizard-path-row--excluded` dims to 50% opacity on uncheck
   - Confirm button disabled + `role="alert"` message when all paths unchecked
   - CSS in `frontend/src/index.css`

6. **`wizardGuidance.ts` in `frontend/src/lib/`**
   - Pure serialization function: excluded paths → `Exclude path: <path>` lines; resolutions → `Clarification — "<term>": <resolution>` lines
   - Extracted per `react-fast-refresh-isolated-helpers` learned rule for testability

7. **`ExecutionPanel.tsx` wiring**
   - 3 new state vars: `showWizard`, `wizardPaths`, `wizardAmbiguities`
   - `autoPreview()` handler sets wizard state on Rule B match
   - `handleWizardConfirm`: builds guidance, updates `preParseGuidance`, re-fetches preview
   - `handleWizardSkip`: closes modal, preserves unmodified steps

### Design Decisions

**Architecture**: Hybrid Option 4 — pre-pipeline regex for structural path markers + reuse of `_detect_step_ambiguity()` for semantic ambiguities. Rationale: explicit `>` notation is format-consistent, making regex highly precise (zero false positives in test suite). Saves the latency + cost of a Stage 0 LLM call.

**Wizard trigger**: Rule B (`paths >= 2 OR ambiguities > 0`) over Rule A (paths only). A PM verifying a single-path ticket with a vague assertion still sees the wizard and can clarify before the run — saves one retry cycle.

**Wizard layout**: Vertical checklist (Option 1) over accordion or two-column drag-to-reorder. Lowest implementation cost, consistent with existing `StepTable` pattern.

References:
- `memory-bank/creative/jira-card-to-test-step-intelligence-path-detection-architecture.md`
- `memory-bank/creative/jira-card-to-test-step-intelligence-clarification-wizard-uiux.md`

## Testing

- **Backend phase 1**: 11 unit tests in `tests/test_prompt_path_parsing.py` — all passing
- **Backend phase 2**: 7 unit tests in `tests/test_video_analyzer.py` — all passing
- **Frontend phase 3**: 5 unit tests in `frontend/src/lib/__tests__/wizardGuidance.test.ts` — all passing
- **TypeScript check**: Clean (no errors)
- **Pre-existing failures**: 4 failures in `AppShell.test.tsx` / `SelectView.test.tsx` confirmed unrelated to jira-card-to-test-step-intelligence changes (tracked as vqa-playwright-test-suite-stability-sweep-22-failures)
- **Total new tests**: 23

## Files Changed

- `backend/api/routes.py` — Map `detected_paths` and `ambiguities` from `ac_parser_node` response
- `backend/api/schemas.py` — Extend `PreviewStepsResponse` with `detected_paths` and `ambiguities` fields
- `backend/engine/ac_parser.py` — Add `_detect_nav_paths()`, extend `SUPPORTED_TYPES` for `video/mp4`, dispatch MP4 to `analyze_video()`
- `backend/engine/prompts.py` — Rules 10–11 in `BDD_NORMALIZER_PROMPT`; Rules 6–7 in `JSON_COMPILER_PROMPT`
- `backend/engine/vision_analyzer.py` — Add `analyze_video()` and `_extract_mp4_frames()` methods
- `docker/Dockerfile` — Add `ffmpeg` to apt-get packages
- `frontend/src/components/ClarificationWizardModal.tsx` — New wizard modal component
- `frontend/src/components/ExecutionPanel.tsx` — Wizard state vars, `handleWizardConfirm`, `handleWizardSkip`, Rule B trigger in `autoPreview()`
- `frontend/src/index.css` — Wizard CSS classes
- `frontend/src/lib/__tests__/wizardGuidance.test.ts` — New: 5 unit tests for `buildGuidance()`
- `frontend/src/lib/wizardGuidance.ts` — New: `buildGuidance()` pure serialization utility
- `frontend/src/types/index.ts` — Add `detected_paths` and `ambiguities` to `PreviewStepsResponse`
- `tests/test_prompt_path_parsing.py` — New: 11 unit tests for path detection and prompt behavior
- `tests/test_video_analyzer.py` — New: 7 unit tests for ffmpeg frame extraction and vision dispatch

## Lessons Learned

1. **Creative documents as zero-ambiguity build contracts**: Both creative documents were specific enough (exact regex, TypeScript interface, CSS classes) that the build agent made no architectural judgment calls. All decisions were pre-resolved. This is the correct target for Level 3 creative phases.

2. **Real-world failure examples as spec inputs**: Starting with a concrete failing output (3 repetitive blocks from a 3-path Jira card) produced sharper acceptance criteria and more testable unit tests than abstract feature requests.

3. **ffmpeg stdin-pipe frame extraction**: Use `asyncio.create_subprocess_exec` with `image2pipe -vcodec png` to stdout. Split on `b'\x89PNG'` but **re-prepend** the magic bytes to each fragment — the split boundary consumes the first two bytes of each PNG; reconstruct as `b'\x89PNG' + chunk`.

4. **Pre-pipeline detection over LLM call**: For format-consistent structural markers (like `>` navigation paths), a pre-pipeline regex scan adds zero latency, zero cost, and higher precision than a new LLM call. Reserve a new LLM stage for implicit/context-dependent patterns.

5. **Phase dependency ordering reduces integration risk**: Completing `PreviewStepsResponse` schema extension (Phase 1) before Phase 3 (wizard that reads those fields) means Phase 3 never worked with undefined fields.

Reference: `memory-bank/reflection/reflection-jira-card-to-test-step-intelligence.md`

## Follow-up

- **Playwright E2E for wizard flow** (vqa-playwright-test-suite-stability-sweep-22-failures or future `/banyan-uat` pass once deployed to QA)
- **Implicit navigation detection** (Option 2): If PMs write navigation without `>`, a Haiku Stage 0 LLM call (~3s, ~$0.01) can be added; the architecture doc describes the upgrade path
- **Per-path step preview in wizard** (accordion layout): Requires backend schema extension to partition steps by detected path; deferred from jira-card-to-test-step-intelligence scope

## References
- Reflection: `memory-bank/reflection/reflection-jira-card-to-test-step-intelligence.md`
- Architecture creative: `memory-bank/creative/jira-card-to-test-step-intelligence-path-detection-architecture.md`
- UI/UX creative: `memory-bank/creative/jira-card-to-test-step-intelligence-clarification-wizard-uiux.md`
- Feature: `FEAT-113` in `memory-bank/roadmap.md`
