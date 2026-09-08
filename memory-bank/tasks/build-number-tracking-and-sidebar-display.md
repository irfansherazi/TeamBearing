---
legacy_id: build-number-tracking-and-sidebar-display
---
# build-number-tracking-and-sidebar-display: Build Number Tracking & Sidebar Display

**Complexity**: Level 1 (Simple)
**Status**: INITIALIZED
**Roadmap Link**: N/A
**Branch**: feature/build-number-tracking-and-sidebar-display-build-number

---

## Description

Introduce a build number tracking mechanism to improve auditability and deployment visibility. The build number will be loaded from the environment variable `VQA_BUILD_NUMBER` (with fallback to a local `.build_number` / `BUILD_NUMBER` file, defaulting to `"dev"`), propagated from the backend `/health` endpoint to the frontend, and rendered in the navigation sidebar directly beneath the logout button.

---

## Specification

### Acceptance Criteria

#### Backend Config & API (`backend/`)
- **AC-1**: Add `vqa_build_number` as a string config field in the `Settings` class (`backend/config.py`). It must load case-insensitively from `VQA_BUILD_NUMBER`.
- **AC-2**: Support fallback tracking: if the environment variable is not set or is empty/`"dev"`, the backend should check if a `.build_number` or `BUILD_NUMBER` file exists at the root, reading its contents if present.
- **AC-3**: Update the `HealthCheck` Pydantic model (`backend/api/schemas.py`) to include `build_number: str`.
- **AC-4**: Include `settings.vqa_build_number` in the return payloads for:
  - `/api/health` (liveness probe in `backend/api/routes.py`)
  - `/api/health/ready` (readiness probe in `backend/api/routes.py`)
  - `/health` (passthrough endpoint in `backend/main.py`)

#### Frontend Display (`frontend/`)
- **AC-5**: Update the `HealthResponse` TypeScript interface (`frontend/src/types/index.ts`) to include `build_number?: string`.
- **AC-6**: Render the retrieved build number (e.g. `Build: #123` or similar) in the `AppNav.tsx` sidebar footer, directly underneath the Logout button.
- **AC-7**: Ensure the build number is rendered using standard CSS with appropriate padding, a muted text style, and a CSS class `.nav-build-number` matching the project design guidelines in `frontend/src/index.css`.
- **AC-8**: Gracefully handle missing or default values (if `build_number` is undefined or empty, display a placeholder or hide the build number line).

---

## Implementation Roadmap

### Phase 1: Backend Setup
- Define `vqa_build_number` in `backend/config.py` with fallback lookup logic.
- Update `HealthCheck` schema in `backend/api/schemas.py`.
- Update `/health` routes in `backend/api/routes.py` and `backend/main.py`.

### Phase 2: Frontend Integration
- Add `build_number` to `HealthResponse` typescript types.
- Modify `AppNav.tsx` to render the build number under the logout button.
- Style `.nav-build-number` in `frontend/src/index.css`.

### Phase 3: Verification & Testing
- Add backend unit test in `tests/test_health_build_number.py` to verify build number loading and `/health` output.
- Add frontend unit test or update `AppNav.test.tsx` to verify the build number element is in the document under AppNav.

---

## Test Strategy

### Backend Test (`tests/test_health_build_number.py`)
- Test loading of build number from environment variable `VQA_BUILD_NUMBER`.
- Test loading of build number from fallback file.
- Verify `/health` response contains the correct `build_number` field.

### Frontend Test (`AppNav.test.tsx`)
- Assert that the build number element exists when `healthResponse` is populated with a `build_number`.
