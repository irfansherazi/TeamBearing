# Archive: post-run-test-healing-ai-prompt-generator — Post-Run Test Healing — AI Prompt Generator

**Archived**: 2026-06-09  
**Status**: COMPLETE  
**Complexity**: Level 3 (Intermediate)  
**Feature**: FEAT-110  
**Branch**: `feature/FEAT-110-heal-tests-prompt`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/local-archive-post-run-test-healing-ai-prompt-generator

---

## What Was Built

We successfully designed, implemented, and validated an automated **"Heal Tests"** AI prompt generator for parallel headless Playwright suite executions. When a suite completes and one or more tests fail, clicking the "Heal Tests" button compiles failure logs, failed assertion messages, stack traces, and exact test source code files into a singular, highly optimized, copy-ready markdown prompt. Developers can paste this prompt into Claude or Gemini to get instantly corrected test source files.

### Key Design Decisions
- **REST Compilation Endpoint**: Exposed Pydantic-validated `POST /api/playwright/heal-prompt` in `backend/api/playwright_routes.py` with error guards (HTTP `404` on unknown run IDs, `400` on active or passing runs).
- **Smart Head/Tail Truncation**: Files exceeding 300 lines are deterministically truncated: retaining the first 100 lines (imports, setup) and last 150 lines (assertions, main test logic) to respect LLM token budgets (~8K-16K tokens) and avoid regex indexing vulnerabilities.
- **Credential & Secrets Scrubbing**: Integrated a custom regex-based `scrub_secrets` utility leveraging the existing log-scrubbing helper (`_scrub_line`) to securely replace passwords, tokens, cookies, and JWT values with `[REDACTED]` blocks.
- **Dynamic Header Controls**: Rendered the prominent **🩹 Heal Tests** trigger inside `SuiteResultsPanel.tsx` next to suite header controls. This button appears only when suites finish with failures, showing active loading spin/text indicators during generation.
- **Translucent Prompt Overlay Modal**: Designed the centered `<HealTestsModal />` featuring dark-theme styles, smooth overlay fade-ins, close buttons (`✕` icon and Close footer triggers), and a one-click clipboard copy button with checkmark visual feedback (`Copied!`).
- **Resilient Copy Fallback**: Rendered compiled prompt text inside a `readOnly` `<textarea>` that auto-selects its content on click. If browser sandboxing or VNC iframe limits restrict the Clipboard API, the user can instantly copy using hotkeys (`Cmd+C` / `Ctrl+C`).

---

## Implementation Summary

### Files Changed / Added (11 files)

| File | Change |
|------|--------|
| `backend/api/schemas.py` | Defined `PlaywrightHealPromptRequest` and `PlaywrightHealPromptResponse` Pydantic models. |
| `frontend/src/types/index.ts` | Defined matching TypeScript interfaces for request/response payloads. |
| `backend/api/playwright_routes.py` | Mounted the `/heal-prompt` POST handler. Implemented Head/Tail slicing, file reading, and `scrub_secrets` filtering. |
| `frontend/src/components/SuiteResultsPanel.tsx` | Added header trigger button, loading spinners, and integrated the `<HealTestsModal />` overlay dialog. |
| `tests/test_playwright_healing.py` | Created comprehensive backend pytest cases asserting 404/400 validation, file lookups, secret scrubbing, and truncation limits. |
| `frontend/src/components/__tests__/SuiteResultsPanel.test.tsx` | Expanded Vitest cases to verify dynamic button visibility, mock API requests, Modal loading, and clipboard copy actions. |
| `memory-bank/creative/post-run-test-healing-ai-prompt-generator-architecture.md` | Authored architecture specs (truncation scheme and prompt format). |
| `memory-bank/creative/post-run-test-healing-ai-prompt-generator-uiux.md` | Authored UI/UX layout specs (headers integration, modal overlays, and copy feedback states). |
| `memory-bank/creative/post-run-test-healing-ai-prompt-generator-user-journey.md` | Authored user journey map (run launched, active triage, and reload states). |
| `memory-bank/reflection/reflection-post-run-test-healing-ai-prompt-generator.md` | Compiled post-build engineering lessons, challenges, and evaluations. |
| `memory-bank/tasks/post-run-test-healing-ai-prompt-generator.md` | Task document updated to status `REFLECTION_COMPLETE`. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Target Backend Unit Tests | `tests/test_playwright_healing.py` |
| Target Backend Pass Rate | 100% (5/5 PASS) |
| Target Frontend Unit Tests | `frontend/src/components/__tests__/SuiteResultsPanel.test.tsx` |
| Target Frontend Pass Rate | 100% (9/9 PASS) |
| TypeScript Compiler Status | 100% Clean (`0 errors / 0 warnings`) |
| Overall Regression Suite Pass Rate | 100% green |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| **AC-1**: POST `/api/playwright/heal-prompt` endpoint | ✅ PASS | Validated with Pydantic payload `{"run_id": "suite-xxxxx"}`. |
| **AC-2**: Unknown run ID / active / passing run validation | ✅ PASS | Triggers HTTP `404` on invalid IDs and `400` on running or successful runs. |
| **AC-3**: Resolve, read, and gracefully truncate test files | ✅ PASS | Loads test file path from index registry, gracefully handles missing files, and truncates files >300 lines. |
| **AC-4**: Assemble markdown structured prompt | ✅ PASS | Compiles framework context, error assertion stdout/stderr trace, and test source code. |
| **AC-5**: Return assembled prompt as JSON response | ✅ PASS | Successfully serializes compiled markdown as `{"prompt": "compiled prompt..."}`. |
| **AC-6**: Header trigger button | ✅ PASS | Integrates a prominent **"🩹 Heal Tests"** action next to header controls. |
| **AC-7**: Dynamic visibility rule | ✅ PASS | Omitted during active execution, and visible only when the report status is complete or failed with failed tests > 0. |
| **AC-8**: Spinner loading indicator | ✅ PASS | Spatters a purple-accented rotating wheel and "Generating..." label on click. |
| **AC-9**: Translucent prompt Modal overlay | ✅ PASS | Renders centered overlay displaying copy-to-clipboard actions with visual checkmark success states. |

---

## Retrospective Notes

**Key Learnings**:
- **Microtask Timing in Assertions**: Asynchronous state propagation (such as clipboard copy success highlights) inside React Testing Library must be wrapped in `await waitFor(...)` blocks to avoid race conditions.
- **Double Mocking for File Queries**: Always patch both `exists()` and `is_file()` when stubbing file-system path queries in python unit tests.
- **Ecosystem Safety via Localized Scope**: Localized vitest filters (`npm test -- SuiteResultsPanel`) speed up dev feedback loops and optimize token outputs.
