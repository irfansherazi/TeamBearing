---
legacy_id: FEAT-110
version: next
linked_tasks: [post-run-test-healing-ai-prompt-generator, post-run-test-healing-ai-prompt-generator]
status: planned
---

  ### FEAT-110: Post-Run Test Healing — AI Prompt Generator
- **Version**: next
- **Status**: planning
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Add a "Heal Tests" button to the Playwright test results UI that is only available after a full suite run completes. When clicked, the system collects all failure data (error messages, stack traces, test file paths, relevant source code snippets) from the run and generates a comprehensive, copy-ready AI prompt that a developer can paste into an AI coding assistant (Gemini, Claude, ChatGPT, etc.) to fix all the failing tests in one shot.
    1. **Failure Data Collection**: After a Playwright run completes, the backend collects structured failure data from each failed test: error type, error message, stack trace, test file path, the failing test step/assertion, and the relevant lines of the test source code.
    2. **AI Prompt Generation Endpoint**: A new `POST /playwright/heal-prompt` endpoint accepts a `run_id` and returns a structured, context-rich prompt. The prompt includes: (a) a preamble explaining the project context (Playwright + TypeScript, Angular/PrimeNG SPA under test), (b) for each failed test: the full error output, the test source code, the test step that failed, and any relevant fixture/helper code, (c) clear instructions asking the AI to output corrected test files.
    3. **Frontend "Heal Tests" Button**: A prominent button (e.g., 🩹 "Heal Tests") appears in the test results view ONLY when the run is complete AND at least one test has failed. Clicking it calls the backend endpoint, then displays the generated prompt in a modal with a "Copy to Clipboard" button.
    4. **Smart Context Inclusion**: The prompt generator intelligently includes only the most relevant context — not entire files, but the failing test blocks, shared fixtures/helpers referenced by the failing tests, and the `playwright.config.ts` setup section. This keeps the prompt within typical AI context window limits.
- **Acceptance Criteria**:
    - AC-1: "Heal Tests" button is visible in the Playwright results UI only when: (a) the run is complete, AND (b) at least one test failed.
    - AC-2: "Heal Tests" button is NOT visible when all tests pass or when the run is still in progress.
    - AC-3: `POST /api/playwright/heal-prompt` accepts a `run_id` and returns a structured prompt string containing all failure details.
    - AC-4: The generated prompt includes for each failed test: error message, stack trace, test file path, the test source code, and the specific failing assertion/step.
    - AC-5: The generated prompt includes project context (Playwright + TypeScript, test runner config, relevant shared helpers).
    - AC-6: A modal displays the generated prompt with a "Copy to Clipboard" button that copies the full prompt text.
    - AC-7: The prompt is structured so an AI coding assistant can understand and produce corrected test files without additional context.
    - AC-8: The prompt stays within reasonable size limits (~8K-16K tokens) by including only relevant code sections, not entire files.
- **Key Files**:
    - `backend/api/playwright_routes.py` (Modify — add `/heal-prompt` endpoint)
    - `backend/storage/playwright_registry.py` (Modify — add failure data extraction helpers)
    - `frontend/src/components/PlaywrightLibrary.tsx` (Modify — add Heal Tests button + prompt modal)
    - `frontend/src/index.css` (Modify — styles for heal prompt modal)
- **Linked Tasks**: [post-run-test-healing-ai-prompt-generator](tasks/post-run-test-healing-ai-prompt-generator.md)
- **Branch**: feature/FEAT-110-heal-tests-prompt
- **Created**: 2026-06-09
