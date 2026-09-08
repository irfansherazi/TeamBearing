---
legacy_id: fix-websocket-err-connection-refused-on-vqa-frontend
---
# fix-websocket-err-connection-refused-on-vqa-frontend: Fix WebSocket ERR_CONNECTION_REFUSED on vQA Frontend

**Status**: COMPLETE
**Phase**: ARCHIVE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: feature/fix-websocket-err-connection-refused-on-vqa-frontend-fix-ws-connection-refused
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

The vQA frontend throws browser console errors when a test run is initiated due to hardcoded `localhost` fallbacks for WebSockets and API calls.

### Root Cause Analysis

**Compounding configuration issues:**

1. **Hardcoded Fallbacks**: `WS_BASE_URL` in `frontend/src/types/index.ts` defaulted to `ws://localhost:8000` when `VITE_WS_URL` was not set, causing connection failures in production.
2. **Inconsistent Variable Names**: `ReportsArchive.tsx`, `ReportsHistory.tsx`, and `TriagePanel.tsx` were using different environment variables or had their own hardcoded `localhost` fallbacks.

### Solution Applied

1. **Unified & Dynamic Configuration**: Updated `frontend/src/types/index.ts` to derive `API_BASE_URL` and `WS_BASE_URL` from the current browser origin (`window.location`) if environment variables are missing. This removes the hardcoded `localhost:8000` fallback that was breaking production runs.
2. **Consolidated Fallbacks**: Removed locally hardcoded `localhost` definitions across multiple components (`ReportsArchive.tsx`, `ReportsHistory.tsx`, and `TriagePanel.tsx`), switching them to use the global constants from the central types registry.
3. **Cross-Environment Compatibility**: Ensured the frontend automatically points to the correct backend host whether it's running locally (via Vite proxy) or deployed on ECS (via the ALB), without requiring environment-specific build artifacts for basic connectivity.

---

## Acceptance Criteria

- [x] **AC-HAPPY-1**: Starting the vQA backend and initiating a run causes the WebSocket to connect successfully — no `ERR_CONNECTION_REFUSED` errors appear in the console.
- [x] **AC-HAPPY-2**: Frontend no longer falls back to `localhost:8000` in non-local environments; it correctly uses the current origin.
- [x] **AC-HAPPY-3**: Reports archive and history components load correctly by using the unified `API_BASE_URL`.
- [x] **AC-ERROR-1**: If the backend is genuinely unreachable, the UI surfaces a user-visible connection error state.
- [x] **AC-REGRESS-1**: Existing WebSocket message handling continues to work correctly.

---

## Changes Made

- **`frontend/src/types/index.ts`**: Implemented origin-aware `API_BASE_URL` and `WS_BASE_URL` derivation logic.
- **`frontend/src/components/ReportsArchive.tsx`**: Switched to global `API_BASE_URL`; removed local `localhost` fallback.
- **`frontend/src/components/ReportsHistory.tsx`**: Switched to global `API_BASE_URL`; removed local `localhost` fallback.
- **`frontend/src/components/TriagePanel.tsx`**: Switched to global `API_BASE_URL`; removed local `localhost` fallback.

---

## Execution State

**Build Status**: COMPLETE
**Last Completed**: Archive
**Can Resume**: NO
**Reflection Document**: `memory-bank/reflection/reflection-fix-websocket-err-connection-refused-on-vqa-frontend.md`
**Archive Document**: `memory-bank/archive/archive-fix-websocket-err-connection-refused-on-vqa-frontend.md`
