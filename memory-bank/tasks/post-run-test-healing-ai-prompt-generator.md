---
legacy_id: post-run-test-healing-ai-prompt-generator
---
# post-run-test-healing-ai-prompt-generator: Post-Run Test Healing — AI Prompt Generator

**Complexity**: Level 3 (Intermediate)
**Status**: REFLECTION_COMPLETE
**Roadmap Link**: [FEAT-110: Post-Run Test Healing — AI Prompt Generator](../roadmap.md#feat-110-post-run-test-healing-ai-prompt-generator)
**Branch**: feature/FEAT-110-heal-tests-prompt

---

## Description

Introduce an automated, context-rich **"Heal Tests"** AI prompt generator for parallel headless Playwright suite executions. When a suite completes and one or more tests fail, clicking the "Heal Tests" button collects all failure logs, failed assertion messages, stack traces, and the exact test source code files, compiling them into a singular, highly optimized, copy-ready markdown prompt. Developers can paste this prompt into an AI coding assistant (such as Gemini or Claude) to obtain instantly corrected test source files.

---

## Specification

### Acceptance Criteria

#### Backend Endpoint (`POST /api/playwright/heal-prompt`)
- **AC-1**: Expose a Pydantic-validated endpoint `POST /api/playwright/heal-prompt` accepting a JSON payload: `{"run_id": "suite-xxxxx"}`.
- **AC-2**: Raise an `HTTP 404` exception if the `run_id` is unknown, or an `HTTP 400` if the run is still in progress or has zero test failures.
- **AC-3**: For each failed test in the suite run:
  - Retrieve its file path from the pre-built `playwright_index.json` (via the registry).
  - Resolve and read the source code file from disk. If the file is missing or unreadable, handle the error gracefully and continue.
  - Limit inclusion of files exceeding 300 lines by gracefully truncating and retaining only relevant imports and failing step context blocks to respect token limits (~8K-16K tokens).
- **AC-4**: Assemble a markdown-structured prompt string containing:
  - A project context preamble describing the framework (Playwright, TypeScript, React 19, Angular, PrimeNG SPA under test).
  - For each failed test: the test file path, the exact parsed stdout/stderr assertion error block, and the test's full source code.
  - Instructions for the AI to provide corrected versions of the files in standard markdown code blocks without breaking styles or imports.
- **AC-5**: Return the assembled prompt in a JSON structure: `{"prompt": "compiled prompt markdown..."}`.

#### Frontend "Heal Tests" Trigger & Modal
- **AC-6**: Implement a prominent **"🩹 Heal Tests"** button in `SuiteResultsPanel.tsx` next to the header controls.
- **AC-7**: The "Heal Tests" button is visible **only** when `report.status` is `"completed"` or `"failed"`, AND `report.failed > 0`. It is hidden during active execution or when all tests pass.
- **AC-8**: Clicking "Heal Tests" displays a loading spinner and calls `POST /api/playwright/heal-prompt` with the suite's run ID.
- **AC-9**: On success, displays the generated prompt inside a beautifully styled dark-theme Modal overlay featuring:
  - Title: **🩹 AI Test Healing Prompt**
  - Description instructions.
  - A scrollable, pre-formatted `<pre>` or `<textarea>` block containing the copy-ready prompt.
  - A **"Copy to Clipboard"** button with dynamic copy feedback (e.g. changing text to "Copied!").
  - A **"Close"** button.

---

## Implementation Roadmap

### Phase 1: Schemas & Type Definitions
- Add `PlaywrightHealPromptRequest` and `PlaywrightHealPromptResponse` to `backend/api/schemas.py`.
- Add mirroring TypeScript interfaces to `frontend/src/types/index.ts`.

### Phase 2: Backend API Implementation
- Implement the `/heal-prompt` POST handler in `backend/api/playwright_routes.py`.
- Implement `_extract_test_source_code` to read and format local file contents safely.
- Create the core prompt formatting template.

### Phase 3: Frontend Component Integration
- Add the `Heal Tests` button and loading state handlers inside `SuiteResultsPanel.tsx`.
- Create the styled Overlay and Modal container components with full copy-to-clipboard hook support.

### Phase 4: Testing & Verification
- **Backend Tests**: Create `tests/test_playwright_healing.py` asserting prompt formatting and robust file loading.
- **Frontend Tests**: Add cases inside `frontend/src/components/__tests__/SuiteResultsPanel.test.tsx` verifying:
  - Button visibility states.
  - Modal rendering and copy events.

---

## Test Strategy

### Backend Test Suite (`tests/test_playwright_healing.py`)
- **Test 1**: Verify `POST /api/playwright/heal-prompt` returns 404 for unknown run IDs.
- **Test 2**: Verify `POST /api/playwright/heal-prompt` returns 400 for runs in progress.
- **Test 3**: Mock file systems and successful runs to verify the compiled prompt contains:
  - Preamble framework tags.
  - File paths and source contents of failed tests.
  - Assertion outputs.

### Frontend Test Suite (`SuiteResultsPanel.test.tsx`)
- **Test 1**: Assert "Heal Tests" button is visible when failed tests > 0.
- **Test 2**: Assert "Heal Tests" button is hidden when failed tests === 0.
- **Test 3**: Verify modal opens on click and contains clipboard buttons.
