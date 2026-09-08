---
legacy_id: sso-keepalive-for-react-frontend
---
# sso-keepalive-for-react-frontend: SSO Keepalive for React Frontend

## Header

- **ID**: sso-keepalive-for-react-frontend
- **Task**: SSO Keepalive for React Frontend
- **Complexity**: Level 2
- **Status**: COMPLETE
- **Roadmap Link**: FEAT-107
- **Branch**: feature/FEAT-107-sso-keepalive
- **Created**: 2026-06-08

## Description

Implement a minimal SSO keepalive module for the React frontend using only the existing vcAPI auth pattern. The sole goal is to prevent users from being logged out every few minutes. Do not redesign auth or add unrelated features.

## Specification

### Feature Type
Infrastructure — session management improvement

### User Journey
- **Trigger**: User logs in or app boots with existing SSO token
- **During session**: SSO token silently refreshed every 15 seconds
- **On failure**: Network errors silently retried; 401/403 forces logout
- **On logout**: Keepalive timer stopped and cleaned up

### Acceptance Criteria

- **AC-HAPPY-1**: ✅ `start()` begins a 15s interval calling `POST /auth/ssoRefresh` with `Authorization: Bearer <token>` and body `{ "spotIdsVisible": [] }`
- **AC-HAPPY-2**: ✅ Successful response with valid `ssoToken` updates stored token immediately
- **AC-ERROR-1**: ✅ Network/temporary errors preserve token and continue interval
- **AC-ERROR-2**: ✅ 401 response triggers forced logout and stops timer
- **AC-ERROR-3**: ✅ 403 response triggers forced logout and stops timer
- **AC-ERROR-4**: ✅ 200 response with missing/empty `ssoToken` triggers forced logout
- **AC-EDGE-1**: ✅ `stop()` clears the interval
- **AC-EDGE-2**: ✅ Calling `start()` twice does not create duplicate timers
- **AC-EDGE-3**: ✅ Keepalive starts on auth, stops on logout, cleans up on unmount

### Test Strategy
- **Emphasis**: Unit-heavy
- **Tests written**: 11 (all passing)
- **Test file**: `frontend/src/auth/ssoKeepalive.test.ts`

## Implementation Roadmap

- `[x] Phase 1: SSO Keepalive Module + Integration + Tests`
  1. ✅ Created `ssoKeepalive.ts` with `createSsoKeepalive()` factory
  2. ✅ Wrote `ssoKeepalive.test.ts` with 11 test cases (all passing)
  3. ✅ TypeScript clean (`tsc --noEmit`)
  4. ✅ Modified `AuthProvider.tsx` — replaced 60-min SSO interval with 15s keepalive
  5. ✅ Code review: APPROVED

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/auth/ssoKeepalive.ts` | NEW | SSO keepalive module (132 lines) |
| `frontend/src/auth/ssoKeepalive.test.ts` | NEW | 11 unit tests |
| `frontend/src/auth/AuthProvider.tsx` | MODIFIED | Replaced 60-min SSO interval with 15s keepalive |

## Execution State

- **Build Status**: COMPLETE
- **Current Phase**: BUILD_COMPLETE
- **Phase Built**: Phase 1 (1 of 1)
- **Tests**: 11/11 PASS
- **TypeScript**: CLEAN
- **Code Review**: APPROVED
- **Can Resume**: NO
