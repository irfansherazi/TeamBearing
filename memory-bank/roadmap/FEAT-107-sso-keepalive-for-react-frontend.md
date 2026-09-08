---
legacy_id: FEAT-107
version: next
linked_tasks: []
status: planned
---

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