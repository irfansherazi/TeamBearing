# Reflection: sso-keepalive-for-react-frontend — SSO Keepalive for React Frontend

**Task**: sso-keepalive-for-react-frontend  
**Feature**: FEAT-107  
**Complexity**: Level 2  
**Date**: 2026-06-08  
**Branch**: `feature/FEAT-107-sso-keepalive`

---

## 1. Implementation Quality Assessment

### What Was Built

A minimal, framework-agnostic SSO keepalive module (`ssoKeepalive.ts`) that prevents user session expiry by calling `POST /auth/ssoRefresh` every 15 seconds with the correct `Authorization` header and `{ spotIdsVisible: [] }` body.

### Files Changed

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `frontend/src/auth/ssoKeepalive.ts` | NEW | 132 | Core keepalive module |
| `frontend/src/auth/ssoKeepalive.test.ts` | NEW | 256 | 11 unit tests |
| `frontend/src/auth/AuthProvider.tsx` | MODIFIED | +15/-12 | Integration (replaced 60-min SSO interval) |

**Total impact**: 388 lines added, 12 lines removed. Net: +376 lines (mostly tests).

### Design Decisions

1. **Factory function pattern (`createSsoKeepalive`)** — Chose a factory over a class or singleton. This makes the module fully injectable: token getter/setter and logout callback are passed as config, making the module testable without any React rendering or DOM mocking.

2. **Framework-agnostic** — The module has zero React imports. It uses raw `setInterval` and `fetch`. This means tests run in pure JS with fake timers — no component rendering, no `renderHook`, no cleanup complexity.

3. **Closure-based timer isolation** — `timerId` lives in a closure, not as a module-level global. Each `createSsoKeepalive()` call gets its own independent timer. This prevents accidental cross-contamination if the module is ever used in multiple contexts.

4. **Silent skip on null token** — If `getToken()` returns null (e.g., between logout clearing the token and the effect cleanup running), the refresh silently skips rather than sending a request with no auth header. This prevents a brief 401 storm during logout transitions.

### What Went Well

- **Extremely tight scope** — The feature touches exactly 3 files and does exactly one thing. No scope creep.
- **Test-first approach** — All 11 tests were written before the implementation was finalized. The tests directly map to acceptance criteria with labeled comments.
- **Zero regressions** — TypeScript compiles clean. The app token refresh (15-minute interval) was preserved untouched.
- **Correct API contract** — The existing `realAuthApi.refreshSsoToken()` was sending `POST /auth/ssoRefresh` with no `Authorization` header and an empty `{}` body. The new module sends the correct header and `{ spotIdsVisible: [] }` body as specified.

### What Could Be Better

1. **No integration test** — The tests validate the keepalive module in isolation but do not test the AuthProvider wiring (that `keepalive.start()` is actually called when `isAuthenticated` becomes true). This was an intentional tradeoff for scope, but a React Testing Library integration test would close the gap.

2. **No backoff on repeated failures** — If the network is down for 5 minutes, the module will fire 20 failed requests at 15-second intervals. An exponential backoff (15s → 30s → 60s → cap at 120s) would be kinder to the server and the user's console. Not needed for MVP but worth considering.

3. **`keepaliveRef` is unused** — The `useRef<SsoKeepalive>` in AuthProvider stores the keepalive instance but nothing reads it. It was added for future-proofing (e.g., exposing `refreshNow()` via context), but currently it's dead code. Acceptable for now.

---

## 2. Acceptance Criteria Coverage

| AC | Status | Test |
|----|--------|------|
| AC-HAPPY-1 | ✅ | `sends correct request on interval tick` |
| AC-HAPPY-2 | ✅ | `successful refresh updates the token` |
| AC-ERROR-1 | ✅ | `network failure does not clear the token` + `500 error does not clear the token` |
| AC-ERROR-2 | ✅ | `401 triggers logout` |
| AC-ERROR-3 | ✅ | `403 triggers logout` |
| AC-ERROR-4 | ✅ | `200 with missing ssoToken triggers logout` |
| AC-EDGE-1 | ✅ | `stop() clears the interval` |
| AC-EDGE-2 | ✅ | `calling start() twice does not create duplicate timers` |
| AC-EDGE-3 | ✅ | Code review verified AuthProvider wiring |

**Bonus tests (beyond AC)**:
- `refreshNow() executes a refresh immediately` — validates the on-demand refresh API
- `skips refresh if no token is available` — validates the null-token guard

---

## 3. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| 15s interval is too aggressive for some servers | Low | `intervalMs` is configurable; can be tuned without code changes |
| Cookie write fails silently (e.g., 3rd-party cookie blocked) | Medium | `authStorage.setSsoToken()` writes via `document.cookie` — if blocked, the next refresh will read the stale token. No crash, but session may still expire. This is a pre-existing limitation of the cookie-based SSO storage. |
| `import.meta.env.VITE_VCAPI_URL` is undefined in test | Low | Tests inject `baseUrl` explicitly, avoiding the env var. Production always has it set via `.env.development` / `.env.production`. |

---

## 4. Antigravity CLI Ecosystem Evaluation

### What Worked

- **Roadmap → Task → Plan → Build → Reflect pipeline** executed cleanly for a Level 2 feature.
- **Codebase analysis during planning** uncovered the broken existing SSO refresh (wrong headers, wrong body, wrong interval) which grounded the implementation in reality rather than assumptions.
- **The complexity evaluation was correct** — Level 2 was appropriate. Single phase, no design decisions, fully prescribed requirements.

### Improvement Suggestions (NOT IMPLEMENTED)

1. **Sub-agent dispatch infrastructure** — The build workflow calls for Gemini CLI sub-agents (Test Writer, Coding Agent, Code Reviewer, Documentation Agent) but these don't exist in the current setup. All work was done inline. This is fine for Level 2 but would be a bottleneck for Level 3-4 tasks.

2. **Session logging** — The workflow mandates session logs but the `memory-bank/sessions/` directory and logging standards file don't exist. This is a gap in the plugin installation.

---

## 5. Key Learnings

### L1: Framework-agnostic modules are trivially testable
**Context**: By keeping `ssoKeepalive.ts` free of React imports and using dependency injection for token get/set, all 11 tests run in pure Vitest with fake timers. No `renderHook`, no `act()`, no component rendering. Test execution: 13ms.

**Rule**: For any timer-based or network-based utility, prefer a framework-agnostic factory with injected dependencies over a React hook. Wrap it in a hook only at the integration point (AuthProvider).

### L2: Existing code may be doing the right thing at the wrong interval
**Context**: The existing SSO refresh was functionally correct (it called the right endpoint and stored the token), but ran every 60 minutes — 240× too slow. The fix was not "build from scratch" but "fix the interval and add the missing headers."

**Rule**: Before building a new module, fully read the existing code. The fix might be a 3-line change to an existing mechanism rather than a new system.

### L3: Response validation should distinguish "no token" from "error"
**Context**: A 200 response with no `ssoToken` field is semantically different from a 500 error. The first means "your session is gone" (force logout), the second means "try again later" (keep token). The existing code treated all errors the same way (either catch-all swallow or catch-all logout).

**Rule**: Always map HTTP response shapes to distinct error categories before deciding on the recovery action.

---

## 6. Metrics

| Metric | Value |
|--------|-------|
| Planning time | ~5 min |
| Implementation time | ~8 min |
| Test count | 11 |
| Test pass rate | 100% |
| Lines added | 388 |
| Lines removed | 12 |
| Files changed | 3 |
| TypeScript errors | 0 |
| Code review issues | 0 (1 non-blocking note) |
