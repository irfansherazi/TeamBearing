# Archive: fix-websocket-err-connection-refused-on-vqa-frontend — Fix WebSocket ERR_CONNECTION_REFUSED on vQA Frontend

**Archived**: 2026-05-19T18:21:00Z
**Complexity**: Level 1 (Quick Bug Fix)
**Duration**: Single session (2026-05-19)
**Branch**: `main` (direct commit — Level 1 fast path)
**Archive Strategy**: push-and-pr

---

## Task Summary

Resolved a multi-file frontend configuration anti-pattern in the vQA application where hardcoded `localhost:8000` fallbacks caused `net::ERR_CONNECTION_REFUSED` WebSocket and REST errors in any environment other than a developer's local machine.

---

## Problem Statement

The vQA frontend threw browser console errors (`net::ERR_CONNECTION_REFUSED`) when a test run was initiated from a non-local environment (ECS, staging). The root cause was compounding:

1. **Central types file** (`frontend/src/types/index.ts`) derived `WS_BASE_URL` and `API_BASE_URL` from optional env vars (`VITE_WS_URL` / `VITE_API_URL`) but fell back to `ws://localhost:8000` / `http://localhost:8000` when env vars were absent.
2. **Three component files** (`ReportsArchive.tsx`, `ReportsHistory.tsx`, `TriagePanel.tsx`) each defined their own local URL constants with independent hardcoded `localhost` strings — silently bypassing the central config entirely.

A partial fix to only the types file would have left the three component-level shadow overrides intact and the bug unresolved.

---

## Solution Applied

| File | Change |
|------|--------|
| `frontend/src/types/index.ts` | Replaced `VITE_API_URL \|\| 'localhost:8000'` fallback with origin-aware derivation using `window.location.protocol` and `window.location.host`. Automatically upgrades `http://` → `ws://` and `https://` → `wss://`. |
| `frontend/src/components/ReportsArchive.tsx` | Removed local `localhost` URL constant; switched to global `API_BASE_URL` import. |
| `frontend/src/components/ReportsHistory.tsx` | Removed local `localhost` URL constant; switched to global `API_BASE_URL` import. |
| `frontend/src/components/TriagePanel.tsx` | Removed local `localhost` URL constant; switched to global `API_BASE_URL` import. |

**Key design choice**: Origin-aware derivation (`window.location`) was preferred over requiring `VITE_API_URL` to always be set. This makes the fix zero-config — no environment variable updates required for existing ECS deployments. The env var can still override when the frontend and backend are on different hosts.

---

## Acceptance Criteria — Final Status

| AC | Criterion | Status |
|----|-----------|--------|
| AC-HAPPY-1 | WebSocket connects successfully — no `ERR_CONNECTION_REFUSED` | ✅ PASS |
| AC-HAPPY-2 | Frontend no longer falls back to `localhost:8000` in non-local envs | ✅ PASS |
| AC-HAPPY-3 | Reports archive and history load using unified `API_BASE_URL` | ✅ PASS |
| AC-ERROR-1 | Unreachable backend surfaces user-visible connection error | ✅ PASS |
| AC-REGRESS-1 | Existing WebSocket message handling continues to work | ✅ PASS |

---

## Implementation Roadmap — Final Status

- [x] **Phase 1** (single): Identify all `localhost` consumers, apply origin-aware fix to `types/index.ts`, remove shadow overrides from components, verify in browser.

---

## Key Learnings

### Extractable Pattern (Added to `error-handling.md`)

> **error-handling** (`frontend/src/types/`, `*.tsx`): When centralising environment-variable-based URL constants into a single module, grep for all consumer files that may contain local copies of the same variable — partial centralisation leaves silent shadow overrides that defeat the fix and survive code review if only the central file is inspected.

### Technical Insights

1. **Two-layer anti-pattern**: The bug required fixing both the central config file AND the per-component overrides. A grep for `localhost` across the frontend source was the key step that revealed the full scope.
2. **Origin-aware URL derivation**: `window.location.protocol === 'https:' ? 'wss://' : 'ws://'` + `window.location.host` is a robust, dependency-free approach for environments where the frontend and backend share the same host/port (including ALB + ECS deployments).
3. **Zero-config deployment parity**: The fix works across local dev (Vite proxy), staging, and production (ECS/ALB) without requiring build-time environment variable injection for basic connectivity.

### Future Work (Non-Blocking)

- Add a console warning when `VITE_API_URL` is absent in non-localhost environments (aids debuggability for split-host deployments).
- Add Playwright E2E coverage for WebSocket handshake success (gap noted — relevant given vQA is itself a browser-automation platform).

---

## Reflection Reference

Full reflection: `memory-bank/reflection/reflection-fix-websocket-err-connection-refused-on-vqa-frontend.md`

**Overall Task Success**: ✅ Success
**Workflow Effectiveness**: ✅ Highly Effective (Level 1 direct-fix path — appropriate for scope)

---

## Git Artifacts

- **Commit**: `c8ab1db` — `feat(fix-websocket-err-connection-refused-on-vqa-frontend): Reflect — Fix WebSocket ERR_CONNECTION_REFUSED + pattern extraction`
- **Branch**: `main` (committed directly — no feature branch for Level 1 fix)
- **PR**: N/A (changes already on main; push-and-pr strategy applies when feature branches are used)
