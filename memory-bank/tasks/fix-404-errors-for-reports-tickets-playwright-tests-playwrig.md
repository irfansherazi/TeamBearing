---
legacy_id: fix-404-errors-for-reports-tickets-playwright-tests-playwrig
---
# fix-404-errors-for-reports-tickets-playwright-tests-playwrig: Fix 404 errors for /reports, /tickets, /playwright/tests, /playwright/storage/status

**Complexity**: Level 1
**Status**: INITIALIZED
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: hotfix/fix-404-errors-for-reports-tickets-playwright-tests-playwrig-fix-api-proxy-404-errors
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

The backend log shows repeated 404 responses for these routes:

```
GET /reports         → 404 Not Found
GET /tickets         → 404 Not Found
GET /playwright/tests → 404 Not Found
GET /playwright/storage/status → 404 Not Found
```

**Root Cause**: The Vite dev server proxy in `frontend/vite.config.ts` is configured to strip the `/api` prefix from requests before forwarding them to the backend:

```ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ''),  // ← strips /api
    },
  },
}
```

The frontend's `API_BASE_URL` (defined in `frontend/src/types/index.ts`) resolves to `${window.location.origin}/api` (e.g., `http://localhost:3000/api`) in development. So a fetch to `/api/reports` goes through the Vite proxy, gets rewritten to `/reports`, and arrives at the backend as `GET /reports HTTP/1.1`.

However, all backend routes are registered via `app.include_router(router, prefix="/api")` and `app.include_router(playwright_router, prefix="/api")` in `backend/main.py`. This means the actual backend paths are:

- `/api/reports`
- `/api/tickets`
- `/api/playwright/tests`
- `/api/playwright/storage/status`

The stripped path `/reports` does not match any backend route → **404**.

**Fix**: Remove the `rewrite` rule from the Vite proxy config so that `/api/reports` hits the backend as `/api/reports`.

---

## Acceptance Criteria

- AC-HAPPY-1: `GET /api/reports` on the backend returns 200 (not 404) during local development
- AC-HAPPY-2: `GET /api/tickets` on the backend returns 200 (not 404) during local development
- AC-HAPPY-3: `GET /api/playwright/tests` on the backend returns 200 (not 404) during local development
- AC-HAPPY-4: `GET /api/playwright/storage/status` on the backend returns 200 (not 404) during local development
- AC-HAPPY-5: The same routes continue to work correctly in production (no regression — production routes through ALB, no Vite proxy)
- AC-REGRESS-1: No regressions in existing tests
- AC-REGRESS-2: Other proxied routes (e.g., `/ws/*`) continue to work correctly

---

## Open Questions

None — task is well-defined.

---

## Affected Components

- `frontend/vite.config.ts` — Remove the `rewrite` rule from the `/api` proxy entry. This is the only change needed.

---

## Test Strategy

### Approach
- **Emphasis**: Manual verification (no unit tests for Vite config)
- **Target test count**: 0 automated / 1 manual smoke test

### Test Targets
- Verify backend log no longer shows 404s for the four routes after removing the rewrite
- Verify `GET /api/health` still works (sanity check that non-rewritten routes still proxy correctly)

### What NOT to Test
- Backend route logic (no changes there)
- Production ALB routing (unaffected)

---

## Implementation Roadmap
- [ ] Phase 1: Remove `rewrite` line from Vite proxy config in `frontend/vite.config.ts`
- [ ] Phase 2: Restart dev server and confirm 404s are gone in backend.log

---

## Execution State

**Build Status**: IDLE
**Last Completed**: N/A
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
(none)
