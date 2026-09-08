---
legacy_id: FEAT-052
version: next
linked_tasks: [playwright-standard-library-integration-full-runtime-wiring]
status: complete
---

### FEAT-052: Playwright Standard Library Integration — Full Runtime Wiring
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: This feature wires the real `playwright/` folder (35+ test files, 22 utility files, storage-state auth system) into the vQA product. Key requirements:
    1. **BACKEND**: Wire the real `playwright/` folder into the existing `backend/playwright_tests` stub. (a) Point `PLAYWRIGHT_TESTS_DIR` env var at `playwright/tests/`; (b) Enhance `GET /playwright/tests` and `POST /playwright/refresh` to parse real `.test.ts` filenames and extract metadata (JIRA key, description, step count) from `playwright_index.json`; (c) New `POST /playwright/run` endpoint that accepts `{ test_id, env, user, browser }`, shells out to `npx playwright test`, streams stdout/stderr back over SSE, and returns a `run_id`; (d) Wire storage-state infrastructure to call `node playwright/utils/generateStorageStates.mjs`, with a `POST /playwright/auth/refresh` endpoint triggering this.
    2. **FIXTURES / USERS / STORAGE**: (a) Populate `fixtures/users/users.json` with 13 real users (Demo* + Admin) and `SHARED_TEST_PASSWORD`; (b) Ensure `storage/test/`, `storage/smoke/`, `storage/prod/` directories are created and `storageState_<User>.json` files are generated via `generateStorageStates.mjs`; (c) New `GET /playwright/storage/status` endpoint; (d) New `POST /playwright/storage/generate` endpoint.
    3. **FRONTEND**: Promote `PlaywrightLibrary.tsx` to a FULL PAGE at `/playwright`. Include: (a) Test Browser panel (searchable/filterable, grouped by JIRA prefix); (b) Configuration panel (env/user/browser); (c) Run Controls panel with real-time streaming log output; (d) Storage State Manager (13 users x 4 environments matrix); (e) Test History panel with link to HTML report. UI must match dark-mode aesthetic.
    4. **PLAYWRIGHT CONFIG & PACKAGE WIRING**: (a) Verify/create root-level `playwright.config.ts`; (b) Ensure `package.json` has `playwright` and `@playwright/test` devDeps; (c) Add npm scripts: `playwright:run`, `playwright:auth`, `playwright:report`; (d) Update `.env.example` with correct default values.
- **Linked Tasks**: playwright-standard-library-integration-full-runtime-wiring
- **Branch**: feature/FEAT-052-playwright-standard-library
- **Created**: 2026-05-27
- **Completed**: 2026-05-27 ✅
