---
legacy_id: codegen-transformer-auto-refactor-recorded-tests-to-use-proj
---
# codegen-transformer-auto-refactor-recorded-tests-to-use-proj: Codegen Transformer — Auto-refactor recorded tests to use project helpers

**Complexity**: Level 2
**Status**: COMPLETE
**Reflection**: memory-bank/reflection/reflection-codegen-transformer-auto-refactor-recorded-tests-to-use-proj.md
**Archived**: memory-bank/archive/archive-codegen-transformer-auto-refactor-recorded-tests-to-use-proj.md
**Completed**: 2026-07-14
**Roadmap**: FEAT-112
**Branch**: feature/FEAT-112-codegen-transformer
**Worktree**: N/A

## Task Description

When a user records a demo via the vQA codegen flow, Playwright produces raw TypeScript that is
immediately brittle: hardcoded credentials, hardcoded dates, specific database row IDs, calendar
day-click sequences, and environment URLs that only work today. This feature adds an automatic
transformation step between recording and commit that rewrites the raw codegen output into a
production-ready test using the project's existing helper utilities.

**Core transformer and pipeline integration are already prototyped and validated** against two real
recordings (QA-192, VC2-9225). Both `backend/engine/codegen_transformer.py` and the one-line
integration in `backend/engine/codegen_session.py` (lines 362–363) are in place. The remaining work
is:

1. **Tests** — pytest test suite for `codegen_transformer.py` covering `_strip_fences` edge cases,
   `transform_recorded_test` fallback behavior, and the new `_analyze_transformations` helper
2. **`_analyze_transformations` helper** — inspect the transformed code and return a summary dict
   (auth_applied, date_helpers, nav_helpers, fragile_warnings, captcha_helpers)
3. **WS payload** — include `transformations` key in the `recording_done` broadcast from `codegen_session.py`
4. **UI feedback** — surface the transformation summary in the RecordDemoModal "done" panel so
   reviewers see what was changed at a glance

**What the transformer already does** (no changes needed):
- Removes the recorded login block → `test.use({ user })` + setup.ts fixture
- Replaces hardcoded environment URLs with `BASE_URL`; strips session query params
- Replaces spot title/ISCI/date fills with `generateRandomSpotTitle()`, `generateRandomISCI()`, `calculateDueDate()` etc.
- Replaces calendar day-click sequences with `fillDateField()` from `OrderHelper.ts`
- Replaces sidebar folder link clicks with `goToFolder()` from `NavHelper.ts`
- Handles reCAPTCHA interactions via `resolveCaptcha()` from `CaptchaHelper.ts`
- Adds `// ⚠️ FRAGILE:` comments on brittle locators
- PR body checklist points reviewers at `⚠️ FRAGILE` lines

## Specification

**Feature Type**: NFR/Infrastructure (developer productivity — no end-user UI changes beyond the
feedback row)
**Primary Persona**: QA Lead / Automation Engineer (records demos, reviews generated PRs)
**Creative Exploration Needed**: No

### Invocation Method
- Automatic — triggered when the user closes the Playwright recording browser
- Entry path: `POST /codegen/start` → close browser → `monitor_session()` in `codegen_session.py`
  calls `transform_recorded_test()` before `_format_test_file()`
- UI feedback is surfaced in the RecordDemoModal "done" panel via the existing WebSocket
  `{"type": "recording_done", ...}` payload

### Success Criteria
- **Test suite**: `pytest tests/test_codegen_transformer.py` passes with 8+ tests
- **User sees**: "done" panel in RecordDemoModal shows a `Transformations` row listing what was
  applied (e.g., "Auth fixture, 3 date helpers, 2 ⚠️ FRAGILE warnings")
- **Fallback**: if Bedrock fails, raw code is still committed; `transformations` key is absent from
  the WS payload (graceful degradation already in place — no regression)

### Acceptance Criteria

- AC-1: `tests/test_codegen_transformer.py` exists and all tests pass under `pytest tests/`
- AC-2: `_strip_fences` correctly handles `typescript` fence, `ts` fence, no fence, and trailing-only fence
- AC-3: `transform_recorded_test` returns raw code (not raises) when `_call_bedrock` raises any exception
- AC-4: `_analyze_transformations(transformed_code)` in `codegen_transformer.py` returns a dict with
  keys: `auth_applied` (bool), `date_helpers` (int), `nav_helpers` (int), `fragile_warnings` (int),
  `captcha_helpers` (int)
- AC-5: `codegen_session.py` calls `_analyze_transformations` after a successful transformation and
  includes a `transformations` key in the `recording_done` WS broadcast
- AC-6: `CodegenDoneEvent` type in `frontend/src/types.ts` includes optional `transformations` field
  typed as `{ auth_applied: boolean; date_helpers: number; nav_helpers: number; fragile_warnings: number; captcha_helpers: number }`
- AC-7: RecordDemoModal "done" panel renders a `Transformations` row when `result.transformations` is
  present, showing a human-readable summary string (e.g., "Auth fixture · 2 date helpers · 1 ⚠️ FRAGILE")

### Scope Boundaries
- **In scope**: transformer unit tests, `_analyze_transformations` helper, WS payload update, frontend type + UI row
- **Out of scope**: changing the transformer's Claude system prompt, integration tests that call real Bedrock, other codegen UI changes
- **Dependencies**: `codegen_transformer.py` and `codegen_session.py` already implement the core; no new backend routes needed

## Test Strategy

### Approach
- **Emphasis**: unit (pure Python, no Bedrock calls — mock `_call_bedrock`)
- **Target test count**: 8–10 total

### File Organization
- **New test files**: `tests/test_codegen_transformer.py` — covers `_strip_fences`, `transform_recorded_test` fallback, and `_analyze_transformations`
- **Extend existing**: none (no existing transformer tests)

### What NOT to Test
- Actual Claude/Bedrock output quality — validated manually via the prototype recordings
- GitHub API commit logic in `codegen_session.py` — out of scope for this task
- The transformer system prompt content — no changes planned

### Per-Phase Test Guidance
- Phase 1:
  - `_strip_fences` (4 tests): typescript fence, ts fence, no fence, trailing-only fence
  - `transform_recorded_test` fallback (2 tests): Bedrock success path (mocked), Bedrock raises → returns raw
  - `_analyze_transformations` (2 tests): code with helpers → correct counts; code with no helpers → all zeros/false
- Phase 2: no new tests (frontend row is manually verified)

## Implementation Roadmap

- [x] Phase 1: `_analyze_transformations` + tests
- [x] Phase 2: WS payload + RecordDemoModal Transformations row

## Creative Phases

(none required)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Current Step**: ARCHIVED
**Completed**: 2026-07-14
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Step 0: Provisioned as codegen-transformer-auto-refactor-recorded-tests-to-use-proj for FEAT-112 (existing prototype validated, scope is tests + UI feedback)
- Step 3: Spec authored by planner with full codebase context — no Spec Writer Agent needed given prototype is complete
- Step 1: Read task context — Phase 1 identified (_analyze_transformations + tests)
- Step 2: Load context — Level 2 implementation rules noted
- Phase 1 COMPLETE (2026-07-14): Added `_analyze_transformations` to codegen_transformer.py; created tests/test_codegen_transformer.py with 8 passing tests (AC-1, AC-2, AC-3, AC-4 satisfied)
- Phase 2 COMPLETE (2026-07-14): Added `transform_and_analyze` to codegen_transformer.py; updated codegen_session.py to include `transformations` in recording_done payload; added `CodegenTransformations` type and optional field to `CodegenDoneEvent`; added Transformations row to RecordDemoModal done panel (AC-5, AC-6, AC-7 satisfied)
