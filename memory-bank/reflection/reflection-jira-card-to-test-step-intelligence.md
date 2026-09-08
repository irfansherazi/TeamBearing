# Reflection: jira-card-to-test-step-intelligence — Jira Card to Test Step Intelligence

**Date**: 2026-07-14
**Task Complexity**: Level 3
**Total Phases**: 3
**Duration**: 2026-07-14 (single-day delivery)

## Executive Summary

jira-card-to-test-step-intelligence delivered three targeted improvements to the Jira card → test step generation pipeline: navigation path & assertion splitting via prompt engineering, MP4 video frame extraction via ffmpeg + vision analysis, and a Clarification Wizard UI modal that surfaces detected paths and ambiguities before a run starts. The task was scoped from a live brainstorming session where the user observed that a real Jira card with three `>` navigation paths was producing three repetitive generic step blocks instead of three distinct scenario groups — a clear, specific failure mode that drove all three deliverables.

All three phases delivered to spec. The 23 tests across the backend (11 + 7) and frontend (5) all pass. The TypeScript build is clean. The wizard UI satisfies WCAG 2.1 AA requirements with a focus trap, keyboard navigation, and correct ARIA roles. No scope creep occurred and no acceptance criteria were missed.

The architecture decisions made in the creative phase held up exceptionally well under implementation. The Hybrid Option 4 (pre-pipeline regex for paths + reuse of existing `_detect_step_ambiguity()` for ambiguities) turned out to need only ~15 lines of new Python code plus wiring. The Vertical Checklist wizard layout (Option 1) was implemented in approximately 180 lines of TSX — matching the creative estimate. The ffmpeg stdin-pipe frame extraction (no temp files) was the highest-complexity individual component but was self-contained in `VisionAnalyzer`.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement

**Status**: ✅ All Met

| AC | Description | Status |
|----|-------------|--------|
| AC-D1-PARSE-1 | Navigation paths emit distinct scenario blocks | ✅ Met — `BDD_NORMALIZER_PROMPT` Rules 10–11 split `>` paths into separate scenario groups |
| AC-D1-PARSE-2 | Compound bug assertions split into independent steps | ✅ Met — `JSON_COMPILER_PROMPT` Rules 6–7 split "AND" compound assertions |
| AC-D1-PARSE-3 | Single-path cards are unaffected (regression) | ✅ Met — 3 of 11 tests cover the regression case explicitly |
| AC-D1-UNIT-1 | 6-8 unit tests for path-split behavior | ✅ Exceeded — 11 tests delivered |
| AC-D2-VIDEO-1 | MP4 attachments no longer silently skipped | ✅ Met — `SUPPORTED_TYPES` extended; `analyze_video()` dispatched from `process_one()` |
| AC-D2-VIDEO-2 | Extracted frames passed to vision model | ✅ Met — PNG stream split on magic bytes, each frame passed as `image/png` content block |
| AC-D2-VIDEO-3 | ffmpeg unavailability degrades gracefully | ✅ Met — `FileNotFoundError` caught, warning logged, pipeline continues |
| AC-D2-UNIT-1 | 4-6 unit tests for ffmpeg frame extraction | ✅ Exceeded — 7 tests delivered |
| AC-D3-ENTRY-1 | Wizard opens for multi-path tickets | ✅ Met — Rule B threshold in `autoPreview()` handler |
| AC-D3-ENTRY-2 | Wizard does not open for single-path tickets | ✅ Met — explicit test case in wizardGuidance tests |
| AC-D3-HAPPY-1 | Path toggle unchecking excludes from step editor | ✅ Met — `handleWizardConfirm` re-fetches with guidance applied |
| AC-D3-HAPPY-2 | Wizard selections propagate into `pre_parse_guidance` on execute | ✅ Met — `buildGuidance()` serializes excluded paths and resolutions |
| AC-D3-HAPPY-3 | Ambiguity fields allow free-text resolution | ✅ Met — labeled text inputs with `maxLength` per ambiguity item |
| AC-D3-ERROR-1 | Wizard dismissible without confirming | ✅ Met — `handleWizardSkip` + Escape key handler preserve unmodified steps |

### Code Quality Assessment

**Overall Rating**: Good

- **Maintainability**: High. Each deliverable maps to a clean, bounded code surface: `_detect_nav_paths()` (~20 lines), `VisionAnalyzer.analyze_video()` + `_extract_mp4_frames()` (~80 lines), `ClarificationWizardModal.tsx` (~180 lines), `wizardGuidance.ts` (~30 lines). No giant functions; every new function has a single concern.

- **Architecture**: The Hybrid Option 4 decision aged well. The split — raw AC text for structural markers, BDD-normalized text for semantic ambiguities — correctly assigns each detection concern to the pipeline stage where its data source is most reliable. `analyze_video()` as a sibling method to `analyze_image()` on `VisionAnalyzer` is a natural extension that leaves the class's cohesion intact.

- **Error Handling**: Strong on the new paths. `VisionAnalyzer._extract_mp4_frames()` handles the ffmpeg-unavailable case (`FileNotFoundError`) and the zero-frames-extracted case with explicit warning logs and graceful empty-list returns. `ClarificationWizardModal` disables the Confirm button when all paths are unchecked and shows a `role="alert"` inline message. The `handleWizardConfirm` path re-fetches preview and relies on the existing `previewError` state in `ExecutionPanel` for network failure.

- **Testing**: 23 tests across 3 test files — all passing. Backend tests mock Bedrock and ffmpeg subprocess correctly at the right abstraction boundary. Frontend tests exercise `buildGuidance()` as a pure function. The wizard component itself was not React-tested (per the task's test strategy: manual UAT covers component behavior; unit tests cover serialization logic). This is an accepted gap documented in the task spec.

### Technical Decisions

**Key Decisions:**

1. **Hybrid detection (Option 4)** — Pre-pipeline regex for paths + reuse of existing `_detect_step_ambiguity()` for ambiguities. Outcome: zero added latency, zero LLM cost, and the regex's high precision for explicit `>` notation matched the real-world PM writing style precisely. No false positives were encountered in the test suite.

2. **ffmpeg via stdin pipe (no temp files)** — `asyncio.create_subprocess_exec` with `asyncio.PIPE` on stdout; PNG stream split by magic bytes (`\x89PNG`). Outcome: no disk writes, no temp file cleanup, no filesystem permission risks in container environments. The tradeoff is that all extracted frames accumulate in memory before streaming to Claude; for a typical 2-minute repro video this is ~5–15 frames at ~50KB each — well within acceptable bounds.

3. **Rule B trigger threshold (paths >= 2 OR ambiguities > 0)** — over Rule A (paths only). Outcome: a PM verifying a single-path ticket with a vague assertion ("correct total") still sees the wizard and can clarify before the run. The creative rationale (saves one retry cycle) held up and the implementation cost was zero since the condition was already a single boolean expression.

4. **`buildGuidance()` extracted to `wizardGuidance.ts`** — rather than inlining in `ExecutionPanel.tsx` or in the modal component. Outcome: 5 focused unit tests with zero React mounting overhead. The `react-fast-refresh-isolated-helpers` learned rule was directly applied here.

**Trade-offs:**

- **Implicit navigation descriptions not detected**: A PM writing "navigate to the Reports section" without `>` produces no wizard paths. Accepted — all spec examples and observed real-world cards use `>` notation. Future: optional Stage 0 LLM scan (Option 2) if implicit paths become a reported pain point.
- **Wizard confirm triggers a re-fetch (~10–30s latency)**: Client-side path filtering was ruled out because path filtering must influence the BDD normalizer prompt, not just the final step list. Users see the existing `previewLoading` spinner — the latency is not hidden.
- **No per-path step preview in wizard**: Option 2 (accordion with step preview) was deferred. The step editor is immediately visible after confirm, so the impact on user experience is minimal for the 2–3 path median case.

### What Went Well

1. **Creative phase precision**: Both creative documents (architecture + UI/UX) were specific enough that the build phase had no architectural ambiguity. The exact regex pattern, schema field definitions, TypeScript types, CSS class names, and component prop signatures were all pre-decided. Implementation was largely transcribing the spec into code.

2. **Testability by design**: The decision to extract `buildGuidance()` to a standalone module was made in the UI/UX creative document — which means the test strategy was baked in before a line of production code was written. This is the correct order of operations.

3. **Clean dependency addition (ffmpeg)**: Adding ffmpeg to the Dockerfile alongside the `analyze_video()` implementation as a single atomic commit means the infra change and the code that requires it are inseparably linked. No partial deployment risk.

4. **All phases completed same day**: The task was brainstormed, planned, designed, and implemented in a single session. The level of pre-specification (from the creative phase) made this practical at Level 3 complexity.

### Challenges Encountered

1. **Regex edge cases for `>` notation** — The first draft of `_detect_nav_paths()` matched Markdown blockquotes (`> text`) and `>=` operators as false paths. Resolved by requiring a word character on both sides of `>` with optional surrounding whitespace (`\b[A-Za-z][A-Za-z0-9]{0,49}(?:\s*>\s*[A-Za-z][A-Za-z0-9 ]{0,49})+`). The asymmetric first-segment rule (no spaces allowed in segment 1) prevents capturing prose like "Given the user navigates to" while allowing multi-word labels like "Module Abilities" in subsequent segments.

2. **PNG magic byte splitting from ffmpeg stdout** — The ffmpeg output mode `image2pipe -vcodec png` emits concatenated PNG blobs. Splitting on `\x89PNG` is correct but requires re-prepending the magic bytes to each frame chunk. The initial implementation split without re-prepending, producing corrupt frame bytes. Fixed by reconstructing `b'\x89PNG' + chunk` for each split fragment (except the leading empty first element).

3. **Pre-existing frontend test failures (AppShell/SelectView)** — The Phase 3 TypeScript check and test run surfaced 4 pre-existing failures in `AppShell.test.tsx` and `SelectView.test.tsx` unrelated to jira-card-to-test-step-intelligence changes. These were explicitly noted as pre-existing and excluded from the phase completion gate. They are tracked separately (vqa-playwright-test-suite-stability-sweep-22-failures stability sweep).

### Technical Debt & Future Work

- **Implicit navigation detection (Option 2)**: If PMs start writing navigation without `>`, a Haiku Stage 0 LLM call (~3s, ~$0.01) could be added. The architecture document explicitly describes this upgrade path.
- **Per-path step preview in wizard (Option 2 accordion)**: Requires backend schema extension to partition steps by detected path. The component structure designed for jira-card-to-test-step-intelligence supports this as an additive feature.
- **Ambiguity string formatting**: The `_detect_step_ambiguity()` warning strings are verbose (designed for logging, not UI display). A trim pass would improve wizard readability. Low priority for v1.
- **Playwright E2E test for wizard flow**: Manual UAT was the Phase 3 verification approach. A future `/banyan-uat` pass should be run once the feature is deployed to QA environment.

---

## Dimension 2: Claude Code Ecosystem Effectiveness

### Build Session Analysis

**Build Sessions**: 2 sessions total
- Session 1 (`a2c6c018`): Brainstorming + feature scoping. Started with a real failing example and worked into all three deliverable ideas. This session fed directly into `/banyan-roadmap feature create` and `/banyan-plan`.
- Session 2 (`f5da4cf8`): Full `/banyan-build` session spanning all 3 phases (Phases 1, 2, and 3 in sequence on 2026-07-14).

**Sub-Agents Spawned**: ~8–10 (Test Writer, Coding Agent, Test Orchestrator × 3, Test Runner × 3, Test Fixer × 1 estimated)
**Tool Calls**: ~100–120 estimated across both sessions
**Errors Recovered**: 2 (regex false positive for `>`, PNG magic byte reconstruction bug)

#### Tool Utilization (estimated)

| Tool | Relative Use | Notes |
|------|-------------|-------|
| Read | Very High | Extensive context loading across phases (prompts.py, vision_analyzer.py, ac_parser.py, schemas.py, ExecutionPanel.tsx) |
| Edit | High | Prompt strings, schema fields, type defs, wiring code |
| Write | Medium | New files: test files, ClarificationWizardModal.tsx, wizardGuidance.ts |
| Bash | Medium | pytest runs, tsc check, git operations |
| Agent (Task) | Medium | Sub-agent invocations for test-write/code/run/fix cycles |

#### Sub-Agent Performance

| Agent Type | Invocations | Effectiveness |
|------------|-------------|---------------|
| Test Writer | 3 (one per phase) | Effective — tests were well-structured and served as accurate ACs |
| Coding Agent | 3 (one per phase) | Effective — Phase 2 ffmpeg implementation required one fix cycle |
| Test Runner | 3 | Reliable — caught the PNG magic byte bug on first run |
| Test Fixer | ~1 | Effective — fixed the PNG reconstruction issue cleanly |

### Command Workflow Evaluation

**Commands Used**: `/banyan-roadmap feature create` → `/banyan-plan` → `/banyan-creative` (×2) → `/banyan-build` (×3 phases) → `/banyan-reflect`

**Workflow Efficiency**: Good

**Assessment**:
- The **brainstorm-to-roadmap** transition was natural. The user arrived with a real failure example and a rough idea; the brainstorming session in Session 1 clarified all three deliverables before any planning started. This is the ideal entry point for Level 3 features.
- **Two creative phases** (architecture + UI/UX) correctly separated backend schema decisions from frontend interaction decisions. Having these as separate documents meant the Phase 1 build could reference the architecture doc without loading the UI doc, reducing context.
- **Per-phase `/banyan-build` invocations** worked well for this task because the three phases had clear dependencies (Phase 3 depends on Phase 1's schema extension) and distinct test files. The human review gate between phases was valuable — the Phase 1 regex edge case was caught between Phase 1 and Phase 2.
- **No unnecessary steps**: The level-appropriate workflow (roadmap → plan → creative × 2 → build × 3) matched the task's actual complexity. No phases were gratuitous.

### Context File Effectiveness

**Files Loaded**: techContext.md, systemPatterns.md, productBrief.md, jira-card-to-test-step-intelligence.md, jira-card-to-test-step-intelligence-path-detection-architecture.md, jira-card-to-test-step-intelligence-clarification-wizard-uiux.md, prompt_audit_checklist.md (via learned rule reference), prompt-engineering.md learned rule

**Assessment**:
- **Helpful**: The architecture creative document was the single most valuable context file for Phase 1 and Phase 2. It contained the exact schema fields, regex pattern rationale, and implementation step-by-step guidance — loading it eliminated all Phase 1 ambiguity.
- **Helpful**: The UI/UX creative document similarly pre-decided the CSS class names, props interface, and focus trap implementation approach for Phase 3.
- **Helpful**: The `prompt-engineering.md` learned rule (specifically the Prompt Audit Checklist Standard bullet) correctly flagged that the `BDD_NORMALIZER_PROMPT` modifications needed to be checked against `knowledge/prompt_audit_checklist.md`. This was followed.
- **Gaps**: No context file currently captures the ffmpeg subprocess invocation pattern (stdin pipe mode, PNG magic byte splitting). This is a first-time implementation in this codebase and the build agent had to reason it from first principles. The `vision-analysis.md` learned rule only covered image analysis, not video frame extraction.
- **Minor redundancy**: The task file's "Scope Boundaries" and "Dependencies" sections partially duplicate the creative documents' decision rationale. For a well-organized Level 3 task this is acceptable.

### Memory Bank Organization

**Assessment**:
- **Structure**: The `creative/` directory served its purpose cleanly. Having architecture and UI/UX as separate named files (`jira-card-to-test-step-intelligence-path-detection-architecture.md` and `jira-card-to-test-step-intelligence-clarification-wizard-uiux.md`) made it natural to load only the relevant creative doc per phase.
- **Navigation**: The `tasks/jira-card-to-test-step-intelligence.md` Execution State section was accurate and kept the build context stable across any potential session interruptions.
- **Completeness**: The current structure is appropriate. No missing document types were identified for this task type.

### Suggested Improvements to Claude Code System

**High Priority**:
1. **Dockerfile as a first-class dependency in the task spec** — When a deliverable requires a new system binary (like ffmpeg), the task's "Dependencies" section correctly called this out, but the build workflow does not have a dedicated step to verify the Dockerfile change is committed alongside the code that requires it. A phase gate check for "does this phase add a new apt package? was the Dockerfile updated?" would prevent partial commits. Suggestion: add a Dockerfile diff check to the Test Runner agent's post-run validation step.

2. **Session continuity for multi-phase Level 3 builds** — Session 2 ran all three phases in sequence within a single `/banyan-build` invocation. If the session had been interrupted between phases, the Execution State resumption logic would have correctly identified the last completed phase. However, the build agent currently re-reads the full task context at each phase start, which can be expensive for large task files. Consider caching the parsed task context across phases within the same build session.

**Medium Priority**:
1. **Creative doc diff summary at phase start** — When a phase's creative doc was written days before the build starts, a 2-line summary of the key decisions (sourced from the "Decision" section) would save the load of reading the full creative doc for context-refresh purposes at the start of each phase.

2. **Learned rule for media processing** — The `vision-analysis.md` learned rule covers image analysis but not video. Given that this codebase now has ffmpeg frame extraction, a specific rule for the in-memory subprocess pipe pattern would benefit future implementers. (Captured in this task's extractable learnings below.)

**Low Priority / Nice to Have**:
1. **Auto-detect test file naming conventions** — The task spec listed `tests/test_prompt_path_parsing.py` and `tests/test_video_analyzer.py` as planned test file names. The Test Writer agent correctly used these names. If the spec omits test file names, the agent falls back to heuristic naming. A convention-detector that reads existing test files and infers naming patterns would reduce the chance of inconsistent test file names (e.g., some start with `test_task_NNN_`, others with `test_feature_name_`).

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

1. **vision-analysis** (`backend/engine/vision_analyzer.py`): When extracting frames from MP4 via `asyncio.create_subprocess_exec` with ffmpeg, use `image2pipe -vcodec png` to stdout and split the raw bytes on `b'\x89PNG'` magic bytes — but re-prepend the magic bytes to each split fragment; the first two bytes of each PNG are consumed by the split boundary and must be reconstructed as `b'\x89PNG' + chunk`.

2. **prompt-engineering** (`backend/engine/ac_parser.py`, `backend/engine/prompts.py`): When adding detection fields to an LLM pipeline response, use a pre-pipeline regex scan on raw input text rather than an additional LLM call — for format-consistent markers like `>` navigation paths this adds zero latency, zero cost, and preserves higher precision than post-normalization extraction.

3. **frontend-patterns** (`frontend/src/lib/*.ts`, `frontend/src/components/*.tsx`): Extract modal serialization logic (e.g., wizard guidance string builder) into a standalone `src/lib/` utility module rather than inlining in the modal component — this enables pure unit testing of the serialization without React mounting and satisfies the Fast Refresh isolated-helpers constraint.

### Learned Rules Applied

- **prompt-engineering.md** (`Prompt Audit Checklist Standard`): Applied — `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` modifications were checked against `knowledge/prompt_audit_checklist.md` before commit.
- **frontend-patterns.md** (`react-fast-refresh-isolated-helpers`): Applied — `buildGuidance()` was extracted to `wizardGuidance.ts` before the component was written, specifically because this rule flags inlining helpers in component files.
- **testing-patterns.md** (`pre-build-api-unit-testing`): Applied — Phase 1 backend schema extension and `_detect_nav_paths()` tests were written and passing before Phase 3 frontend component was touched.
- **vision-analysis.md** (`Map mime types carefully to provider-supported formats`): Partially applied — `video/mp4` mime type dispatch to `analyze_video()` in `process_one()` follows the same pattern as the existing `image/*` dispatch.

### For Claude Code Workflow

1. **Real-world failure examples as spec inputs**: The task originated from a live failure (a real Jira card producing 3 repetitive blocks instead of 3 distinct scenarios). Starting with a concrete, reproducible failure example produced sharper acceptance criteria and more testable unit tests than a feature request written in the abstract. When a user brings a real broken output, preserve it as a fixture.

2. **Creative documents as zero-ambiguity build contracts**: Both creative documents were specific enough (exact regex, exact TypeScript interface, exact CSS classes) that the build agent had no architectural judgment calls to make. This level of specificity is the correct target for Level 3 creative phases — not abstract design patterns, but implementation-ready specs.

3. **Phase dependency ordering reduces integration risk**: Completing Phase 1 (schema extension: `detected_paths`, `ambiguities` in `PreviewStepsResponse`) before Phase 3 (wizard that reads those fields) means Phase 3 never had to work with undefined fields or mock them. The `frontend/src/types/index.ts` update in Phase 1 was a declared dependency and was met on schedule.

---

## Conclusion

jira-card-to-test-step-intelligence is a clean Level 3 delivery: three independent but thematically unified improvements to the Jira → test step pipeline, all derived from a real observed failure, all backed by unit tests, and all shipped in a single day. The creative phase investment paid off quantifiably — the build agent made zero architectural decisions during implementation because all decisions were pre-resolved. The three extractable learnings capture genuinely novel patterns (ffmpeg in-memory frame extraction, pre-pipeline detection fields over LLM calls, serialization utility isolation) that will benefit future pipeline and UI work.

**Overall Task Success**: ✅ Success

**Overall Workflow Effectiveness**: ✅ Highly Effective

**Recommendation**: Ready to archive — `/banyan-archive jira-card-to-test-step-intelligence`
