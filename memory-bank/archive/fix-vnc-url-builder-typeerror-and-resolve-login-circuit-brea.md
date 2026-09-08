# fix-vnc-url-builder-typeerror-and-resolve-login-circuit-brea: Fix VNC URL Builder TypeError and Resolve Login Circuit Breaker

**Status**: COMPLETED
**Priority**: HIGH
**Complexity**: Level 2
**Roadmap Link**: N/A
**Feature**: N/A

## Overview
A critical `TypeError` was encountered in `human_takeover_node` where `VncUrlBuilder.build_url()` is called with unexpected keyword arguments (`host_header`, `protocol`). This prevented the human takeover screen from loading properly. Additionally, an "AC-LEVEL CIRCUIT BREAKER" was triggered during the login step (1/11), indicating the agent is getting stuck in an execution loop.

## Acceptance Criteria
- [x] `VncUrlBuilder.build_url()` correctly handles calls with `host_header` and `protocol` strings.
- [x] `human_takeover_node` successfully generates a valid `novnc_url` without crashing.
- [x] Investigate and mitigate the "AC-LEVEL CIRCUIT BREAKER" trigger during the "Login as Demo Prod Director" step.
- [x] Verify that VNC URL construction works in both local and proxied environments.

## Implementation Plan

### Phase 1: Fix VncUrlBuilder TypeError
1.  [x] **Action**: Refactor `backend/browser/vnc_builder.py` to accept optional `host_header` and `protocol` arguments in `build_url`.
2.  [x] **Action**: Ensure `build_url` uses these arguments if provided, falling back to `request` headers if not.
3.  [x] **Validation**: Create a unit test for `VncUrlBuilder` covering both `Request` and raw string inputs.

### Phase 2: Investigate Login Circuit Breaker
1.  [x] **Action**: Analyze logs for `run-78d4536b` to understand why it took 10 actions for the login step.
2.  [x] **Action**: Check if there's an issue with the "Demo Prod Director" credentials or the login blueprint.
3.  [x] **Action**: Improve the login node or evaluator to handle this scenario more gracefully if applicable.

### Phase 3: Verification
1.  [x] **Action**: Run the full suite of backend tests.
2.  [x] **Action**: (If possible) Manually trigger a human takeover to verify the VNC URL.
