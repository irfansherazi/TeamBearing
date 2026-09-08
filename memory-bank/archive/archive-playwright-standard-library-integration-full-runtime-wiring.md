# Archive: Playwright Standard Library Integration — Full Runtime Wiring

## Metadata
- **Task ID**: playwright-standard-library-integration-full-runtime-wiring
- **Complexity**: Level 4
- **Started**: 2026-05-27
- **Completed**: 2026-05-27
- **Duration**: ~6 hours (12:26 – 18:13 CDT)
- **Roadmap Link**: FEAT-052
- **Branch**: feature/FEAT-052-playwright-standard-library
- **Worktree**: `.worktrees/FEAT-052`
- **Final Commit**: `e3f71b8` (reflect), `f4cfdf9` (build)

---

## Executive Summary

playwright-standard-library-integration-full-runtime-wiring delivered full runtime wiring of the production `playwright/` directory into the vQA product. Before this task, 35+ Playwright test files existed in the repository but were completely disconnected from the product UI. After this task, a QA Lead can navigate to `/playwright` in the dashboard, browse 40 tests grouped by JIRA prefix, configure environment/user/browser, run a test, watch live streaming logs, and manage auth sessions for 13 users across 4 environments.

**Scope delivered**:
- **4 backend API endpoints** (GET tests, POST run, GET storage/status, POST storage/generate)
- **5-layer input validation** + log scrubbing + semaphore concurrency control
- **Full-page Playwright Dashboard** (`/playwright`) with dark-mode aesthetic matching vQA
- **Storage State Manager** — 13×4 matrix with per-env Refresh Auth
- **30 new tests** — 0 regressions from 716-test suite
- **36/36 Acceptance Criteria** delivered

---

## System Overview

### Purpose

Wire the production `playwright/` directory (35+ test files, 22 utility files, complete storage-state auth for 13 users × 4 environments) into the vQA product as a full-featured Playwright Dashboard.

### Scope

**Included:**
- Backend: `playwright_routes.py` sub-router with 4 endpoints
- Backend: `PlaywrightRegistry` re-pointed to canonical `playwright/playwright_index.json`
- Backend: Log scrubbing, semaphore concurrency control (max 2 runs), PID tracking + shutdown cleanup
- Frontend: `PlaywrightPage.tsx` full-page dashboard (793 lines)
- Frontend: Route `/playwright`, Dashboard tab navigation
- Infrastructure: `playwright.config.ts`, root `package.json` npm scripts, `users.json` (13 users), storage directories

**Excluded (future work):**
- Frontend component splitting (`PlaywrightPage.tsx` tech debt)
- ANSI-to-HTML terminal color rendering
- Filesystem-derived generated count (currently hardcoded 13)
- `pytest-asyncio` async semaphore integration tests

### Key Capabilities

1. **Test Browser** — Searchable, JIRA-prefix-grouped list of all 40 tests from `playwright_index.json`
2. **Run Controls** — env/user/browser selectors + one-click test execution
3. **Live Log Streaming** — Real-time stdout/stderr via existing WebSocket (`_broadcast_terminal_log`) with ANSI stripping
4. **Windowed Terminal** — Last 500 lines kept in state; older lines dropped to prevent browser memory bloat
5. **Pass/Fail Badge** — Green ✅ PASSED / Red ❌ FAILED(N) on WebSocket exit-code event
6. **Storage Manager** — 13×4 color-coded matrix (green=valid, amber=expired, red=missing)
7. **Refresh Auth** — Per-environment `POST /playwright/storage/generate` triggering `generateStorageStates.mjs`
8. **Security** — 5-layer validation: Pydantic Enum → metachar regex → allow-list → user allow-list → no `shell=True`

---

## Architecture

### Overview

The feature adds a dedicated FastAPI sub-router (`backend/api/playwright_routes.py`) mounted in `main.py`. This isolates all Playwright-specific state (semaphore, lock, PID dict) from the main `routes.py` and enables independent testing. The frontend adds a new protected route (`/playwright`) with a full-page React component. No database changes; state is in-memory.

### Component Diagram

```
Frontend (React)                   Backend (FastAPI)
┌──────────────────────┐           ┌──────────────────────────┐
│ Dashboard.tsx        │           │ main.py                  │
│  └─ "Playwright" tab │────────▶  │  └─ include_router()     │
│                      │           │                          │
│ PlaywrightPage.tsx   │  HTTP     │ playwright_routes.py     │
│  ├─ TestBrowser      │ ◀──────── │  ├─ GET /playwright/tests│
│  ├─ TestConfig       │           │  ├─ POST /playwright/run  │
│  ├─ RunControls      │  WS       │  ├─ GET .../status       │
│  │   └─ Terminal     │ ◀──────── │  └─ POST .../generate    │
│  └─ StorageManager   │           │                          │
└──────────────────────┘           │ PlaywrightRegistry       │
                                   │  └─ playwright_index.json│
                                   │                          │
                                   │ Subprocess Layer         │
                                   │  ├─ asyncio.Semaphore(2) │
                                   │  ├─ asyncio.Lock (gen)   │
                                   │  ├─ PID tracking dict    │
                                   │  └─ _log_scrubber()      │
                                   └──────────────────────────┘
```

### Data Flow

1. User navigates to `/playwright` → `GET /playwright/tests` → `PlaywrightRegistry` reads `playwright_index.json` → 40 entries returned
2. User selects test + config + clicks Run → `POST /playwright/run` validates (5 layers) → semaphore gate → `asyncio.create_subprocess_exec(npx playwright ...)` → PID tracked
3. Subprocess stdout/stderr → `_log_scrubber()` → `_broadcast_terminal_log()` → WebSocket → terminal UI
4. Process exits → exit code broadcast via WebSocket → frontend shows PASSED/FAILED badge
5. Storage Manager: `GET /playwright/storage/status` → filesystem check `playwright/storage/{env}/storageState_{User}.json` → mtime → valid/expired/missing
6. Refresh Auth: `POST /playwright/storage/generate` → `asyncio.Lock` gate → `node generateStorageStates.mjs` → 13 files written

### Integration Points

- **WebSocket broadcast** (`_broadcast_terminal_log`): Reuses existing pattern from playwright-test-integration-and-dashboard-execution — zero reinvention
- **PlaywrightRegistry** (`backend/storage/playwright_registry.py`): Pre-existing class; re-pointed to canonical index
- **Frontend router** (`frontend/src/router.tsx`): Protected route added; follows existing auth guard pattern
- **Dashboard navigation** (`frontend/src/components/Dashboard.tsx`): "Playwright" tab added alongside existing tabs
- **API client** (`frontend/src/api_client.ts`): 3 new helper methods (`runPlaywrightTest`, `getStorageStatus`, `generateStorageStates`)
- **`main.py` shutdown hook**: PID cleanup (SIGTERM) added to existing lifespan context

---

## Design Decisions

### Decision 1: Dedicated Sub-Router (`playwright_routes.py`)

- **Decision**: Create `backend/api/playwright_routes.py` as a standalone FastAPI sub-router rather than appending to the 2000-line `routes.py`
- **Rationale**: Isolation of module-level state (semaphore, lock, PID dict). Clean test surface. Independent mount/unmount in `main.py`.
- **Alternatives Considered**: Append to `routes.py` (pollutes global state, makes testing harder)
- **Reference**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-architecture.md`

### Decision 2: Allow-List as Primary Security Control

- **Decision**: `test_id` must exist in `playwright_index.json` (allow-list). Metacharacter regex is secondary defense only. No `shell=True` anywhere.
- **Rationale**: Denylists are bypassable; allow-lists are not. The index is the authoritative source.
- **Alternatives Considered**: Sanitize only (denylist approach) — rejected: too many edge cases
- **Reference**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-algorithm.md`

### Decision 3: Static Allow-List with Pre-compiled Patterns

- **Decision**: Log scrubber uses pre-compiled `re.Pattern` objects at module import time (not per-call `re.sub()`)
- **Rationale**: Performance + correctness. Patterns compile once; 0 per-call compilation overhead.
- **Alternatives Considered**: Per-call re.sub() — rejected: measurable overhead in high-throughput log streaming
- **Reference**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-algorithm.md`

### Decision 4: Monolithic `PlaywrightPage.tsx`

- **Decision**: Single 793-line `PlaywrightPage.tsx` with logical internal sections vs. 5 separate files
- **Rationale**: Pragmatic first-pass choice. Avoids complex prop-drilling for prototype. Documented as tech debt.
- **Trade-off accepted**: Lower per-file testability; higher cognitive load per file in future maintenance
- **Reference**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-uiux.md`

### Decision 5: Terminal Windowing (Slice at 600, Keep 500)

- **Decision**: Amortized batch truncation — when buffer reaches 600 lines, slice to keep last 500
- **Rationale**: Per-line truncation overhead is high in React state. Batch truncation amortizes cost. 500-line window is sufficient for Playwright output visibility.
- **Reference**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-algorithm.md`

---

## Implementation

### Phases

| Phase | Scope | Key Files | Outcome |
|-------|-------|-----------|---------|
| Phase 1: Data Prep | Registry re-point, users.json, storage dirs, .env.example | `playwright_registry.py`, `users.json`, `.env.example` | Canonical index wired |
| Phase 2: Backend API | 4 endpoints, validation, scrubber, semaphore, PID tracking | `playwright_routes.py`, `main.py` | API fully operational |
| Phase 3: Frontend | Full-page dashboard, route, nav, CSS | `PlaywrightPage.tsx`, `router.tsx`, `Dashboard.tsx`, `index.css` | UI functional end-to-end |
| Phase 4: Infra | `playwright.config.ts`, npm scripts, E2E smoke | `playwright.config.ts`, `package.json` | Build verified |

### Key Components

#### `backend/api/playwright_routes.py` (NEW, 587 lines)
FastAPI sub-router with:
- `GET /playwright/tests` — loads `PlaywrightRegistry`, returns 40 entries from canonical index
- `POST /playwright/run` — 5-layer validation, semaphore gate, subprocess exec, PID tracking, log streaming
- `GET /playwright/storage/status` — filesystem check for 13 users × 4 envs, mtime-based validity
- `POST /playwright/storage/generate` — `asyncio.Lock` throttle, `node generateStorageStates.mjs`, 300s timeout

Module-level state:
```python
_playwright_semaphore = asyncio.Semaphore(2)   # max concurrent runs
_storage_lock = asyncio.Lock()                   # 1 concurrent generate
_playwright_pids: dict[str, int] = {}            # run_id → PID
_SCRUB_PATTERNS: list[re.Pattern] = [...]        # pre-compiled at import
```

#### `frontend/src/pages/PlaywrightPage.tsx` (NEW, 793 lines)
Four logical sections:
- **Test Browser**: search input + JIRA-prefix grouping (QA / VC2 / Other) + selectable cards
- **Config Panel**: env/user/browser `<select>` dropdowns + auth warning
- **Run Controls**: Run/Running button + windowed terminal + PASSED/FAILED badge
- **Storage Manager**: 13×4 grid with color-coded status badges + per-env Refresh Auth

### Technical Specifications

#### 5-Layer Input Validation (POST /playwright/run)
```
1. Pydantic model: env ∈ Enum{prod,test,smoke,qa}, browser ∈ Enum{chromium,firefox,webkit}
2. Metachar regex: test_id ∄ [;&|`$(){}] → HTTP 422
3. Allow-list: test_id ∈ playwright_index.json entries → HTTP 422 if unknown
4. User allow-list: user ∈ users.json → HTTP 422 if unknown
5. Path traversal: no ../ in any parameter → HTTP 422
```

#### Log Scrubber Patterns
```python
_SCRUB_PATTERNS = [
    re.compile(r'(?i)(SHARED_TEST_PASSWORD\s*[:=]\s*)\S+'),
    re.compile(r'(?i)(ADMIN_TEST_PASSWORD\s*[:=]\s*)\S+'),
    re.compile(r'"value"\s*:\s*"[A-Za-z0-9+/=]{20,}"'),   # base64 tokens
    re.compile(r'eyJ[A-Za-z0-9_-]{20,}'),                   # JWT prefix
]
```

#### Storage Status Logic
```
valid   = file exists AND mtime < 24 hours ago
expired = file exists AND mtime >= 24 hours ago
missing = storageState_{User}.json does not exist in playwright/storage/{env}/
```

---

## Testing

### Strategy

1. **Unit tests** — `PlaywrightRegistry` canonical loading, scrubber pattern correctness
2. **Security tests** — Shell injection attempts, invalid test_id, path traversal
3. **Integration tests** — HTTP-level validation, semaphore 429 response
4. **Manual E2E** — `GET /playwright/tests` → 40 entries, storage status matrix, run endpoint

### Results

| Test Type | Count | Pass Rate |
|-----------|-------:|----------:|
| Canonical registry (new) | 11 | 100% |
| Log scrubber (new) | 12 | 100% |
| Security/injection (new) | 7 | 100% |
| **New playwright-standard-library-integration-full-runtime-wiring total** | **30** | **100%** |
| Full regression suite | 716 | 100% (8 pre-existing) |
| TypeScript errors | 0 | — |

### Coverage

- **AC Coverage**: 36/36 ✅
  - Backend API (AC-BACK-1 to AC-BACK-15): 15/15
  - Fixtures & Storage (AC-STOR-1 to AC-STOR-4): 4/4
  - Frontend Dashboard (AC-FE-1 to AC-FE-14): 14/14
  - Config & Package (AC-CFG-1 to AC-CFG-3): 3/3
- **Security ACs**: 6/6 ✅
- **Regressions introduced**: 0

---

## Deployment

### Procedures

1. Merge `feature/FEAT-052-playwright-standard-library` into `main`
2. Ensure `.env` has `PLAYWRIGHT_INDEX_FILE=playwright/playwright_index.json` and `SHARED_TEST_PASSWORD` set
3. Run `npm run playwright:install` (if fresh environment) or verify `@playwright/test` installed
4. Restart backend: `./start.sh`
5. Verify: `GET /playwright/tests` returns 40 entries; navigate to `/playwright` in dashboard

### Configuration

Required environment variables (add to `.env`):
```bash
PLAYWRIGHT_TESTS_DIR=playwright/tests
PLAYWRIGHT_INDEX_FILE=playwright/playwright_index.json
SHARED_TEST_PASSWORD=<your-shared-password>
ADMIN_TEST_PASSWORD=<your-admin-password>
TEST_ENV=test
```

Optional:
```bash
PLAYWRIGHT_MAX_CONCURRENT=2    # default: 2 (semaphore limit)
```

### Rollback

1. Revert merge commit on `main` (git revert `<merge-sha>`)
2. Remove `playwright_routes.py` from `backend/api/`
3. Remove `include_router(playwright_router)` from `main.py`
4. Remove `/playwright` route from `frontend/src/router.tsx`
5. Restart backend + frontend

No database migrations required (in-memory only).

---

## Maintenance

### Monitoring

| Signal | What to Check |
|--------|--------------|
| `POST /playwright/run` → 429 | 2 concurrent runs in progress; wait for completion |
| `POST /playwright/storage/generate` → 429 | Generation already in progress |
| Terminal shows no output | WebSocket disconnected; check `ws://{host}/ws/{run_id}` |
| Storage status shows all `missing` | `generateStorageStates.mjs` never run; trigger via UI or `npm run playwright:auth` |

### Common Issues

| Issue | Resolution |
|-------|-----------|
| `GET /playwright/tests` returns empty list | Check `PLAYWRIGHT_INDEX_FILE` points to `playwright/playwright_index.json` (40 entries) |
| Run starts but no log output | Check WebSocket connection; verify `_broadcast_terminal_log` is imported in `playwright_routes.py` |
| `POST /playwright/storage/generate` → 500 | `SHARED_TEST_PASSWORD` env var not set; check `.env` |
| Frontend console error on `/playwright` | Check `api_client.ts` has `runPlaywrightTest`, `getStorageStatus`, `generateStorageStates` methods |
| Playwright subprocess fails to start | Verify `@playwright/test` installed: `cd playwright && npx playwright --version` |

### Operational Procedures

**Re-index tests** (add new `.test.ts` files to index):
```bash
python scripts/sync_playwright_index.py
```

**Regenerate all storage states**:
```bash
npm run playwright:auth
# or via UI: Storage Manager → Refresh Auth for each env
```

**Run a test manually**:
```bash
npm run playwright:run -- --grep "qa-321"
```

**View test report**:
```bash
npm run playwright:report
```

---

## Lessons Learned

See full reflection: `memory-bank/reflection/reflection-playwright-standard-library-integration-full-runtime-wiring.md`

### L1 — Dedicated FastAPI sub-routers for feature modules
For any feature adding ≥3 endpoints, create a dedicated `backend/api/{feature}_routes.py` sub-router. Module-level semaphores/locks scoped to the sub-module prevent cross-feature state leakage.

### L2 — Allow-list as the primary security control for subprocess invocation
When user-supplied parameters are used in subprocess construction, the primary control is an **allow-list** derived from an authoritative source. A metacharacter denylist is secondary only. Never use `shell=True`.

### L3 — Worktree build state must be propagated to main branch memory-bank
When a build runs in a git worktree, the main-branch `memory-bank/tasks/TASK-XXX.md` stays stale. The /vc-reflect and /vc-archive commands must read from the worktree's task file as authoritative and sync status to main.

### L4 — Hardcoded response counts vs. filesystem-derived counts
When an endpoint reports "N items processed" by a subprocess, derive N by post-hoc filesystem inspection rather than returning a constant. Hardcoded counts create false success signals.

### L5 — Large frontend pages need co-located CSS from day one
When creating a new React page with >300 lines of CSS, create a co-located `PageName.module.css` rather than appending to `index.css`.

---

## References

- **Reflection**: `memory-bank/reflection/reflection-playwright-standard-library-integration-full-runtime-wiring.md`
- **User Journey Design**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-user-journey.md`
- **Architecture Design**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-architecture.md`
- **UI/UX Design**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-uiux.md`
- **Algorithm Design**: `memory-bank/creative/playwright-standard-library-integration-full-runtime-wiring-playwright-dashboard-algorithm.md`
- **Progress Log**: `memory-bank/progress.md` (2026-05-27 entries)
- **Feature**: `memory-bank/roadmap.md` → FEAT-052

---

## Future Considerations

1. **Tech Debt — Frontend component splitting**: Split `PlaywrightPage.tsx` (793 lines) into dedicated component files per the original spec (`TestBrowserPanel.tsx`, `TestConfigPanel.tsx`, `RunControlPanel.tsx`, `StorageManagerPanel.tsx`)
2. **Tech Debt — CSS co-location**: Move Playwright CSS from `index.css` to `PlaywrightPage.module.css`
3. **Enhancement — ANSI rendering**: Add `ansi-to-html` or `ansi-regex` for full color-coded Playwright terminal output
4. **Enhancement — Filesystem-derived generated count**: Replace hardcoded `{\"generated\": 13}` with `len(list(storage_dir.glob("storageState_*.json")))` after subprocess completion
5. **Enhancement — `pytest-asyncio`**: Add dependency and write true async integration tests for semaphore/streaming logic
6. **Enhancement — Test history panel**: Persist run history (run_id, test_id, exit_code, timestamp) in a lightweight store for the History tab
7. **Infrastructure — `playwright:install` script**: Add to `package.json` for fresh environment setup

---

## Level 4 Archive Checkpoint

```
✓ LEVEL 4 ARCHIVE COMPLETE
- System documentation created? YES
- Architecture documented? YES (diagram + component breakdown)
- Design decisions compiled? YES (5 decisions with rationales + alternatives)
- Implementation detailed? YES (phases, key components, tech specs)
- Testing documented? YES (30 new tests, 36/36 ACs, 0 regressions)
- Deployment documented? YES (procedures, config, rollback)
- Maintenance guide prepared? YES (monitoring, common issues, operational procedures)
- Archive package complete? YES
```
