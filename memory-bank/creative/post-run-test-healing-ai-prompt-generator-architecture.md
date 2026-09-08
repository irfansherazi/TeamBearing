# Architecture Decision: post-run-test-healing-ai-prompt-generator Post-Run Test Healing — AI Prompt Generator

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: post-run-test-healing-ai-prompt-generator / FEAT-110

---

## Context

### System Requirements

post-run-test-healing-ai-prompt-generator introduces **"Post-Run Test Healing"** for parallel headless Playwright suite executions. When a test suite completes and one or more tests fail, developers need a quick, context-rich way to fix them. Instead of manually correlating failure trace logs with local source files, a single click on "🩹 Heal Tests" will dynamically compile all failures, traces, and actual test source code into a singular, copy-ready AI-optimized prompt.

### Technical Constraints

1. **Information Completeness**: The prompt must contain the exact source code of the failing test, the exact error stack trace/assertion failure block, and the surrounding project context (Playwright, TypeScript, React 19, Angular, and PrimeNG SPA details).
2. **Token Containment & Context Truncation**: A suite can have multiple failures. If each failing test file contains hundreds of lines of code, the prompt can easily exceed standard token limits. We must implement a smart truncation heuristic for test files exceeding **300 lines** to gracefully keep the compiled prompt within a ~8K-16K token budget.
3. **Error Resilience**: If a test file referenced in the pre-built `playwright_index.json` registry has been moved, renamed, or is unreadable, the backend must handle this gracefully (e.g., logging an warning and including the error trace without the source code) rather than failing the entire request.
4. **State Lookup**: We must leverage the in-memory suite execution state dictionary `_suite_runs` established in parallel-headless-suite-runner-with-pass-fail-report to retrieve the run status, failure lists, and captured error trace snippets.

---

## Component Analysis

### Core Components Affected

| Component | File | Change Type | Purpose / Responsibility |
|-----------|------|-------------|--------------------------|
| `schemas.py` | `backend/api/schemas.py` | **MODIFY** | Define request schema `PlaywrightHealPromptRequest` and response schema `PlaywrightHealPromptResponse`. |
| `playwright_routes.py` | `backend/api/playwright_routes.py` | **MODIFY** | Implement the `POST /playwright/heal-prompt` endpoint. Read files, perform context-aware truncation, and construct the final markdown prompt. |
| `SuiteResultsPanel.tsx` | `frontend/src/components/SuiteResultsPanel.tsx` | **MODIFY** | Add "🩹 Heal Tests" button, trigger state handlers, and integrate the styled dark-themed healing modal. |
| `types/index.ts` | `frontend/src/types/index.ts` | **MODIFY** | Define matching TypeScript types/interfaces for request and response payloads. |

### Endpoint Sequence & Data Flow

```
[UI: SuiteResultsPanel]
       │
       ├──(1) User clicks "Heal Tests" (Only visible when suite completed with failures)
       ▼
[POST /api/playwright/heal-prompt]  -- { "run_id": "suite-xxxxx" }
       │
       ├──(2) Lookup "suite-xxxxx" in _suite_runs
       │         ├──► [NOT FOUND] ──► Return HTTP 404
       │         └──► [RUNNING]   ──► Return HTTP 400 (Suite is still running)
       │
       ├──(3) Filter results to identify failed tests. If none failed ──► Return HTTP 400
       │
       ├──(4) Load playwright_index.json (or registry) to resolve file paths for each failed test
       │
       ├──(5) For each failed test:
       │         ├──► Read source file from disk (e.g. backend/playwright_tests/...)
       │         └──► If lines > 300: Apply smart truncation heuristic to keep imports + failure block context
       │
       ├──(6) Format final consolidated markdown prompt containing:
       │         ├──► Framework & UI Context preamble
       │         ├──► List of failed tests
       │         └──► Per-test section: file path, error traceback, and source code block
       │
       ▼
[HTTP 200: { "prompt": "compiled prompt markdown..." }]
       │
       ▼
[UI: Render AI Healing Modal]
       │
       ├──► Displays copy-ready prompt in styled monospace container
       └──► Copy-to-Clipboard with dynamic success feedback
```

---

## Smart Truncation Heuristic Design

When a test file exceeds 300 lines, we apply a robust, token-efficient truncation algorithm in Python to keep the context size optimal:

```python
def truncate_test_source(file_content: str, error_snippet: str, max_lines: int = 300) -> str:
    lines = file_content.splitlines()
    if len(lines) <= max_lines:
        return file_content

    # Keep imports (first 30 lines)
    header_lines = lines[:30]
    
    # Try to find where the failure occurred. 
    # Extract line numbers from the error snippet or look for keywords
    matching_index = -1
    for i, line in enumerate(lines):
        # Heuristic: search for descriptive text or identifiers from the error snippet
        # If we have a stack trace with "test_file.ts:line_number", we can parse the line number.
        pass

    # If no line number parsed, fall back to matching keyword fragments from error_snippet
    # or keep the first 100 lines and last 150 lines with a transition block
    if matching_index == -1:
        # Default middle truncation
        middle_index = len(lines) // 2
        retained_body = lines[30:100] + ["\n// ... [TRUNCATED FOR BREVITY] ...\n"] + lines[-150:]
    else:
        # Context-aware window truncation (e.g., 50 lines before and 100 lines after the failure point)
        start_win = max(30, matching_index - 50)
        end_win = min(len(lines), matching_index + 100)
        retained_body = (
            ["\n// ... [TRUNCATED BEFORE FAILURE] ...\n"] + 
            lines[start_win:end_win] + 
            ["\n// ... [TRUNCATED AFTER FAILURE] ...\n"]
        )

    compiled_lines = header_lines + ["\n// --- IMPORTS END ---\n"] + retained_body
    return "\n".join(compiled_lines)
```

---

## AI Prompt Template Structure

The assembled prompt markdown is meticulously designed to elicit optimal code corrections from models like Claude and Gemini:

```markdown
# Playwright Test Healing Request

You are an expert Playwright automation engineer. Below is a set of failing test files from our test suite, along with their exact error stack traces and assertion messages.

## System Context
- **Testing Framework**: Playwright (TypeScript)
- **Application Stack**: React 19 / Angular SPA with PrimeNG UI components
- **Conventions**:
  - We use explicit, deterministic Playwright state assertions (e.g., `await expect(locator).toBeVisible()`).
  - Do NOT use visual delta or DOM-count diffing for success checks.
  - Handle PrimeNG-specific elements properly (dropdown overlays, animations, loading states).

## Instructions
1. For each failed file, analyze the error trace against the provided source code.
2. Provide a fully corrected, drop-in replacement for the test file inside a single standard markdown code block.
3. Keep all existing imports, session states, and test setup boilerplate intact unless they are directly causing the failure.
4. Explain the root cause of the failure and the specific correction you made in a brief bulleted list under each file block.

---

## Failed Test: {test_display_name}
- **File Path**: `{file_path}`
- **Error Assertion**:
```text
{error_snippet}
```

- **Source Code**:
```typescript
{source_code}
```

---
```

---

## Observability & Logging

All endpoint transitions are instrumented with structured logging to capture performance and usage metrics:

```json
{
  "timestamp": "2026-06-09T15:40:22.102Z",
  "level": "INFO",
  "traceId": "heal-suite-9a2c8b",
  "module": "backend.api.playwright_routes",
  "message": "Generating AI healing prompt",
  "data": {
    "run_id": "suite-9a2c8b",
    "failed_tests_count": 2,
    "total_source_lines_read": 420,
    "truncated_files": ["qa-101-client-merging.test.ts"]
  }
}
```
