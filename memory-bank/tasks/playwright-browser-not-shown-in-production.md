---
legacy_id: playwright-browser-not-shown-in-production
---
# playwright-browser-not-shown-in-production: Playwright Browser Not Shown in Production

**Status**: COMPLETE
**Phase**: DONE
**Complexity**: Level 2
**Created**: 2026-05-20
**Roadmap Link**: N/A
**Branch**: main

---

## Summary

In the production environment (AWS ECS Fargate) or after running `deploy.sh`, the Playwright browser is not visible to the user via the noVNC stream. This prevents operators from observing or taking control of the browser during test runs. The issue was identified as a combination of incorrectly constructed VNC URLs and missing infrastructure routing rules.

---

## Specification

### Invocation Location
- **Backend VNC URL Generation**: `backend/browser/vnc_builder.py` constructs the URL returned to the frontend.
- **ALB Routing**: AWS Application Load Balancer rules in `deploy.sh`.
- **ECS Task Environment**: Environment variables in the ECS task definition.

### Success Criteria
- The noVNC URL constructed by the backend uses the correct protocol (HTTPS) and does not append internal ports (6080) that are not exposed by the ALB.
- The ALB correctly routes traffic for `/vnc.html` and `/websockify` to the VNC target group.
- The Playwright browser launches in a headed state within the Docker container using a virtual display (Xvfb).

### Data Persistence
- None (infrastructure and configuration change).

---

## Acceptance Criteria

### AC-HAPPY-1: Correct VNC URL Construction
**Priority**: MUST

**Given** the application is running in a remote production environment (HTTPS)
**When** the frontend requests the VNC URL
**Then**:
  - The URL uses `https://`
  - The URL does not include port `6080`
  - The URL includes necessary noVNC parameters: `path=websockify`, `autoconnect=true`, `reconnect=true`

**Verification**:
- [x] Unit test: `tests/test_vnc_url_builder.py` verifies HTTPS URL construction without port.

### AC-HAPPY-2: ALB Routing for WebSockets
**Priority**: MUST

**Given** the VNC stream uses WebSockets via `websockify`
**When** a connection is made to `https://<domain>/websockify`
**Then**:
  - The ALB forwards the request to the VNC target group (port 6080)

**Verification**:
- [x] Inspection of `deploy.sh` confirms `/websockify` is added to path patterns.

### AC-HAPPY-3: Headed Browser in Production
**Priority**: MUST

**Given** the vQA agent is running in `interactive` mode in ECS
**When** a browser task starts
**Then**:
  - Playwright connects to `:99` (Xvfb)
  - Headless mode is explicitly set to `False`

**Verification**:
- [x] `deploy.sh` updated to set `DISPLAY=:99` and `VQA_HEADLESS=0`.

---

## Component Analysis

### Affected Components

| Component | File | Change |
|---|---|---|
| `VncUrlBuilder` | `backend/browser/vnc_builder.py` | Updated `build_url` to support path-based routing for HTTPS production environments. |
| `Deploy Script` | `deploy.sh` | Added `/websockify` to ALB rules and injected `DISPLAY`, `VQA_HEADLESS` into ECS task. |
| `Tests` | `tests/test_vnc_url_builder.py` | Updated test expectations to match new URL format. |

---

## Implementation Strategy

### Phase 1 — Infrastructure & Config Update
**Goal**: Ensure ALB and ECS are configured to support headed browser and VNC streaming.

1. Update `deploy.sh` ALB rules to include `/websockify`.
2. Update `deploy.sh` ECS task environment with `DISPLAY` and `VQA_HEADLESS`.

### Phase 2 — Logic Update & Verification
**Goal**: Update URL construction logic and verify with tests.

1. Modify `vnc_builder.py` for path-based routing.
2. Update and run `test_vnc_url_builder.py`.

---

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| **Port Conflicts** | 6080 is used internally. **Mitigation**: ALB maps 443/websockify to internal 6080. |
| **Xvfb Not Starting** | Browser fails to launch. **Mitigation**: Supervised process in Docker ensures Xvfb is up before backend starts. |

---

## Observability Requirements

- **Logs**:
  - `INFO`: `"[VncUrlBuilder] Constructed production URL: https://..."`

---

## Work Items

### WI-045-001: Backend URL Logic
**Status**: Complete
**Completed**: 2026-05-20
**Implementation**: Modified `backend/browser/vnc_builder.py` to use path-based routing for HTTPS.

### WI-045-002: Infrastructure Routing
**Status**: Complete
**Completed**: 2026-05-20
**Implementation**: Updated `deploy.sh` with ALB rules and ECS environment variables.

---

## Test Strategy

| Test File | Coverage |
|---|---|
| `tests/test_vnc_url_builder.py` | Path-based routing and HTTPS detection |

---

## Validation Gate ✅

- [x] Correct production URL generated.
- [x] ALB rules updated.
- [x] ECS environment variables set.

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: DONE
**Can Resume**: NO
**Completed Phases**: PLAN, Phase 1, Phase 2
**Phase Being Built**: N/A
**Phase Number**: 2 of 2
**Is Multi-Phase**: YES
**Build Started**: 2026-05-20T11:00:00-05:00
**Build Completed**: 2026-05-20T12:00:00-05:00

### Completed Steps
- Step 1 Research: COMPLETE
- Step 2 Implementation: COMPLETE
- Step 3 Verification: COMPLETE
