---
legacy_id: FEAT-106
version: next
linked_tasks: [jira-driven-uat-platform-stabilization, jira-driven-uat-platform-stabilization]
status: in_progress
---

### FEAT-106: Jira-Driven UAT Platform Stabilization
- **Version**: next
- **Status**: active
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: Master stabilization initiative to evolve vQA from an experimental LLM-loop agent into a production-grade, Jira-driven UAT platform. Synthesized from empirical data (Week 2 baseline: 0/10 cards passing due to expired auth + selector collisions) and three independent architecture evaluations.

  **Sprint 0 — Empirical Grounding (Day 1)**:
  Resolve two hard blockers: (1) regenerate expired Playwright auth state (`playwright/storage/vpromedia_auth.json`), (2) fix `input[type='password']` strict-mode selector collision on QA-125. Run QA-170 true baseline to produce the first clean end-to-end data point.

  **Sprint 1 — Wire the Wiring Gap (Days 2–5)**:
  Connect four disconnected components to the linear pipeline (all parallelizable):
  - WU-1.1: Wire AC Parser (`_stage_1_normalize` + `_stage_2_compile`) to `_execute_linear_run()`
  - WU-1.2: Fix Jira Posting (`analysis` vs `failure_analysis` key mismatch)
  - WU-1.3: Multi-Signal Stagnant UI Detection (4-signal `compute_ui_delta()` shared utility from jira-and-execution-engine-reliability-polish)
  - WU-1.4: Wire FAIR Quality Gate (log-only MVP, no blocking)

  **Sprint 2 — A11y Tree + Dynamic Selectors (Days 6–10)**:
  Replace brittle static `selectors.json` (28 selectors, ≤20% coverage) with dynamic A11y tree discovery:
  - WU-2.1: A11y Tree Snapshot Capture (`page.accessibility.snapshot()` → pruned structured dict)
  - WU-2.2: A11y-Augmented Spec Generation (inject A11y tree into generator prompt, prioritize `getByRole`)
  - WU-2.3: A11y-Powered Self-Healing (Categories 2 + 6: timing + interaction change detection)

  **Sprint 3 — Golden 10 Benchmark + Iteration (Days 8–12)**:
  - WU-3.1: Run all 10 golden cards, document every failure, update self-healing rates from `[THEORETICAL]` to `[EMPIRICAL]`
  - WU-3.2: Failure Triage — categorize all failures by type, compute per-category fix ROI
  - WU-3.3: vc-uat / Linear Pipeline Convergence Plan (design-only, no code)

  **Architecture Policy Compliance**: Verified against all GEMINI.md rules — Fallback Reliability (proven before proposed), Visual Delta (stagnation detection only, not trust signal), LLM Role (pre-run + post-run only), Recipe/Fixture (dedicated tests for every WU), Reliability Targets (denominator defined: golden_10 × ~15 AC items ≈ 150 AC items).
- **Acceptance Criteria**:
  - AC-1: Auth state regenerated — Playwright sessions run against `two-test.vcreative.net` without login-redirect failures.
  - AC-2: AC Parser wired to linear pipeline — `card["expected_steps"]` is non-empty for tickets with raw AC text.
  - AC-3: Jira Posting works for linear pipeline runs — `POST /run/{id}/post-to-jira` returns 200.
  - AC-4: Multi-signal stagnant UI detection uses 4 signals (URL, element count, ARIA snapshot, overlay markers) via shared `ui_delta.py` utility.
  - AC-5: FAIR Quality Gate fires and logs for FAIR-grade tickets (non-blocking MVP).
  - AC-6: A11y tree snapshot captures ≥50 named elements from `two-test.vcreative.net/spots` in <10 seconds.
  - AC-7: Generated Playwright specs use `page.getByRole()` locators derived from A11y tree context.
  - AC-8: Self-healing detects timing failures (`Timeout 30000ms exceeded`) and interaction changes (`element is not visible`) with max 3 retries across all categories.
  - AC-9: Golden 10 benchmark run produces 10 result entries with per-AC-item pass/fail breakdown.
  - AC-10: ≥40% AC item pass rate on golden_10 corpus (150 AC items denominator).
  - AC-11: Self-healing success rates updated from `[THEORETICAL]` to `[EMPIRICAL]` labels based on benchmark data.
  - AC-12: vc-uat / linear pipeline convergence design document produced (approved before any code).
- **UAT Contract**:
  - **Input**: Jira ticket ID + target environment URL
  - **Output**: Per-AC-item pass/fail report, Playwright traces, Jira comment posted
  - **SLA**: <5 minutes per ticket
  - **Success Unit**: Per-AC-item pass/fail
  - **MVP Target**: ≥40% AC item pass rate on golden_10
  - **Environment**: `https://two-test.vcreative.net`
- **Key Files**:
  - `backend/api/routes.py` (Modify — AC parser wiring, FAIR gate, Jira posting fix)
  - `backend/engine/ui_delta.py` (New — shared 4-signal stagnant UI utility)
  - `backend/engine/a11y_discovery.py` (New — A11y tree snapshot capture)
  - `backend/engine/generator_node.py` (Modify — A11y-augmented prompt)
  - `backend/engine/linear_bridge.py` (Modify — self-healing categories 2 + 6)
  - `backend/engine/verifier.py` (Modify — multi-signal delta)
  - `backend/engine/planner.py` (Modify — overlay-aware DOM culling)
  - `tenants/vpromedia/selectors.json` (Modify — selector collision fix)
  - `tests/benchmarks/golden_10_data.json` (Read — benchmark corpus)
- **Source Plan**: [Master Implementation Plan](file:///Users/joshschauer/.gemini/antigravity-ide/brain/f1b631be-bba3-4c53-8cd6-bb59b2833650/implementation_plan.md)
- **Linked Tasks**: [jira-driven-uat-platform-stabilization](tasks/jira-driven-uat-platform-stabilization.md)
- **Branch**: feature/FEAT-106-uat-platform-stabilization
- **Created**: 2026-06-05

  ### FEAT-107: SSO Keepalive for React Frontend
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Implement a minimal SSO keepalive module for the React frontend using only `vapi`. The sole goal is to prevent users from being logged out every few minutes. This is NOT a redesign of auth — it integrates with the app's existing auth setup (token storage, login flow, auth context/provider).
    1. **Session Helper Module**: Build a small `ssoKeepalive` helper that exposes `start()`, `stop()`, and `refreshNow()`. Only one timer may run at a time. The module calls `POST /auth/ssoRefresh` via `vapi` every 15 seconds with `Authorization: Bearer <current sso token>` and body `{ "spotIdsVisible": [] }`.
    2. **Token Refresh**: On success, if the response contains a valid `ssoToken`, immediately replace the stored token using the app's existing token setter. All other response fields (`lockedSpots`, `updatedSpots`, `caches`, `sisense_jwt`, etc.) are ignored.
    3. **Failure Handling**: Temporary/network errors are silently retried on the next interval (token preserved). Only 401, 403, or a successful response with no valid `ssoToken` triggers forced logout.
    4. **Lifecycle Integration**: Start keepalive after login succeeds and during app bootstrap if a token already exists. Stop on logout. Clean up the interval on unmount.
- **Acceptance Criteria**:
    - AC-1: `ssoKeepalive.start()` begins a 15-second interval calling `POST /auth/ssoRefresh` via `vapi` with the current SSO token.
    - AC-2: A successful response containing a valid `ssoToken` immediately updates the stored token.
    - AC-3: Network/temporary errors do not clear the token; the interval continues.
    - AC-4: 401, 403, or a response with no valid `ssoToken` triggers forced logout.
    - AC-5: `stop()` clears the interval. Calling `start()` twice does not create duplicate timers.
    - AC-6: Keepalive starts automatically after login and on app bootstrap when a token exists.
    - AC-7: Keepalive stops on logout and cleans up on component unmount.
    - AC-8: Tests cover: successful refresh updates token, network failure preserves token, 401/403 triggers logout, `stop()` clears interval, double `start()` no duplicate timers.
- **Scope Limits**: Ignore all product-specific behavior — `lockedSpots`, `updatedSpots`, `caches`, `sisense_jwt`, `activeFolder`, `myFirmIds`, and all non-token-refresh response fields.
- **Key Files**:
    - `frontend/src/auth/ssoKeepalive.ts` (New — keepalive helper module)
    - `frontend/src/auth/AuthContext.tsx` or equivalent (Modify — integrate start/stop)
    - `frontend/src/tests/ssoKeepalive.test.ts` (New — unit tests)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-107-sso-keepalive
- **Created**: 2026-06-08
  ### FEAT-108: Auto-Route Jira Cards to Existing Playwright Tests
- **Version**: next
- **Status**: completed
- **Priority**: high
- **Complexity**: Level 3
- **Description**: When a user selects a Jira card in the "Run a Test" flow, the system should check if there's already a static Playwright test mapped to that card via `playwright_index.json`. If so, skip the AI agent entirely and run the existing test via `POST /playwright/run`. The pieces (index file, registry, schema `execution_engine: "static"`) already exist but are not wired together.
    1. **Backend Test-Match Lookup**: Add `get_tests_by_jira_key(key)` to `PlaywrightRegistry` and expose a new `GET /playwright/match/{ticket_id}` endpoint that returns `{ matched: bool, tests: [...] }` for lightweight, read-only ticket-to-test lookups.
    2. **Frontend Auto-Detection**: In `SelectView.handleSelectTicket()`, call the match endpoint after the user clicks a ticket. If a match is found, show a banner ("🎭 Static Playwright test found") with a "Run Static Test" action.
    3. **Static Test Execution Routing**: When the user opts for the static test, skip the REVIEW/AI agent flow entirely and launch via `POST /playwright/run` with the matched test ID. Stream output via the existing WebSocket terminal.
- **Acceptance Criteria**:
    - AC-1: `PlaywrightRegistry.get_tests_by_jira_key(key)` returns all tests whose `jira_keys` array contains the given key.
    - AC-2: `GET /api/playwright/match/{ticket_id}` returns `{ matched: true, tests: [...] }` when a static test exists, `{ matched: false, tests: [] }` when none.
    - AC-3: Selecting a Jira card with a mapped static test (e.g., QA-170) shows a banner offering to run the static test directly.
    - AC-4: Clicking "Run Static Test" launches the test via `POST /playwright/run` and streams output through the existing WebSocket terminal — no AI agent involved.
    - AC-5: Selecting a Jira card with NO mapped static test proceeds to the existing AI agent flow with zero changes.
    - AC-6: Cards with multiple mapped tests (e.g., QA-196) display all matched tests for selection.
- **Open Questions**:
    - **UX Decision**: Run inline (same page, new UI mode) vs. redirect to Playwright Library vs. choice banner (static test or AI agent)?
    - **Dual-coverage cards**: Cards with both a static test AND AI-testable ACs — always prefer static, let user choose, or run static first then fall back to AI?
- **Key Files**:
    - `backend/storage/playwright_registry.py` (Modify — add `get_tests_by_jira_key`)
    - `backend/api/playwright_routes.py` (Modify — add `/match/{ticket_id}` endpoint)
    - `frontend/src/components/SelectView.tsx` (Modify — auto-detect + banner)
    - `frontend/src/components/RunTestView.tsx` (Modify — static test execution mode)
    - `playwright/playwright_index.json` (Read-only — existing test-to-Jira mapping)
- **Linked Tasks**: [auto-route-jira-cards-to-existing-playwright-tests](tasks/auto-route-jira-cards-to-existing-playwright-tests.md)
- **Branch**: feature/FEAT-108-auto-route-playwright
- **Created**: 2026-06-08

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

  ### FEAT-111: Bolstered Failure Report for Suite Runs
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Description**: After running the full Playwright test suite via "▶ Run All Tests", the end-of-run report should include a bolstered, prominent failure summary section that consolidates all failed tests and their failure reasons into one glanceable block — eliminating the need to click through each row individually.
    1. **Backend — Structured Failure Digest**: Extend the `GET /playwright/run-all/{suite_run_id}/report` response with a new `failure_digest` field: an array of `{ test_id, name, error_summary }` objects, one per failed test. The `error_summary` is a cleaned, one-line condensation of the `error_snippet` (strip ANSI codes, collapse multi-line stack traces to the primary assertion message). This field is only populated when `status === "completed"` or `status === "failed"` and `failed > 0`.
    2. **Frontend — Failure Summary Panel**: Add a new collapsible "❌ Failure Summary" panel to `SuiteResultsPanel.tsx` that appears between the KPI cards and the results table when the suite run is complete and has at least one failure. The panel renders a numbered list of every failed test: `#N — Test Name — Error reason`. Each entry is color-coded red with a monospace error excerpt. The panel starts expanded by default so the operator sees it immediately.
    3. **Clipboard Export**: Add a "📋 Copy Failure Summary" button at the top-right of the failure summary panel. Clicking it copies a plain-text version of the failure list (test name + error reason, one per line) to the clipboard for easy pasting into Slack, Jira comments, or stand-up notes.
- **Acceptance Criteria**:
    - AC-1: `GET /playwright/run-all/{suite_run_id}/report` includes a `failure_digest` array when the suite run has failed tests.
    - AC-2: Each entry in `failure_digest` contains `test_id`, `name`, and a cleaned one-line `error_summary`.
    - AC-3: The `SuiteResultsPanel` renders a prominent "❌ Failure Summary" panel listing all failed tests with their error reasons, positioned between the KPI cards and the results table.
    - AC-4: The failure summary panel is only visible when the suite run is complete/failed AND at least one test failed.
    - AC-5: A "📋 Copy Failure Summary" button copies a plain-text failure list to the clipboard.
    - AC-6: The failure summary panel starts expanded by default for immediate visibility.
    - AC-7: The `error_summary` field strips ANSI escape codes and condenses multi-line errors to the primary assertion message (≤120 chars).
- **Key Files**:
    - `backend/api/playwright_routes.py` — Modify `_run_suite_orchestrator` and report endpoint to include `failure_digest`
    - `backend/api/schemas.py` — Add `FailureDigestEntry` and update `PlaywrightSuiteReportResponse`
    - `frontend/src/components/SuiteResultsPanel.tsx` — Add Failure Summary panel
    - `frontend/src/types/index.ts` — Update `PlaywrightSuiteReportResponse` type
- **Linked Tasks**: None
- **Branch**: feature/FEAT-111-bolstered-failure-report
- **Created**: 2026-06-11

  ### FEAT-112: Codegen Transformer — Auto-refactor recorded tests to use project helpers
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Automatic transformation step inserted between recording and commit that rewrites raw Playwright codegen TypeScript into a production-ready test using project helpers. Core transformer (`backend/engine/codegen_transformer.py`) and pipeline integration (`codegen_session.py`) are already prototyped and validated. Remaining work is tests + UI feedback.
    1. **`_analyze_transformations` helper**: Inspect the transformed code to produce a summary dict (auth_applied, date_helpers, nav_helpers, fragile_warnings, captcha_helpers).
    2. **Tests**: `tests/test_codegen_transformer.py` covering `_strip_fences`, `transform_recorded_test` fallback, and `_analyze_transformations`.
    3. **WS payload**: Include `transformations` key in the `recording_done` broadcast from `codegen_session.py`.
    4. **RecordDemoModal UI row**: Display transformation summary in the "done" panel (e.g., "Auth fixture · 2 date helpers · 1 ⚠️ FRAGILE").
- **Acceptance Criteria**:
    - AC-1: `tests/test_codegen_transformer.py` passes under `pytest tests/` with 8+ tests
    - AC-2: `_strip_fences` handles typescript fence, ts fence, no fence, trailing-only fence
    - AC-3: `transform_recorded_test` returns raw code on Bedrock failure (no raise)
    - AC-4: `_analyze_transformations` returns dict with auth_applied, date_helpers, nav_helpers, fragile_warnings, captcha_helpers
    - AC-5: `codegen_session.py` includes `transformations` key in `recording_done` WS broadcast after successful transform
    - AC-6: `CodegenDoneEvent` in `frontend/src/types.ts` includes optional `transformations` field
    - AC-7: RecordDemoModal "done" panel renders `Transformations` row when `result.transformations` is present
- **Key Files**:
    - `backend/engine/codegen_transformer.py` — Add `_analyze_transformations` function
    - `backend/engine/codegen_session.py` — Call `_analyze_transformations` and include in WS broadcast
    - `tests/test_codegen_transformer.py` — New test file
    - `frontend/src/types.ts` — Add optional `transformations` field to `CodegenDoneEvent`
    - `frontend/src/components/RecordDemoModal.tsx` — Add Transformations row to done panel
- **Linked Tasks**: codegen-transformer-auto-refactor-recorded-tests-to-use-proj
- **Branch**: feature/FEAT-112-codegen-transformer
- **Created**: 2026-07-14
