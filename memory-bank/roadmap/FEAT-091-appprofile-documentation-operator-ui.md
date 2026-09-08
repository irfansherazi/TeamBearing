---
legacy_id: FEAT-091
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-091: AppProfile Documentation & Operator UI
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 2
- **Pillar**: P4 — Knowledge Base / Domain Context
- **Gap ID**: P4-D
- **Estimated Effort**: ~3h
- **Description**: The `AppProfile` system (`backend/kb/profiles/`) is undocumented and has no operator-facing configuration path or UI visibility. Fix: (1) write comprehensive docstrings and a `docs/appprofile.md` guide; (2) expose the active profile name in the dashboard settings panel with a dropdown to switch profiles.
- **Acceptance Criteria**:
  - AC-1: `backend/kb/profiles/` modules have comprehensive module-level and function-level docstrings.
  - AC-2: `docs/appprofile.md` explains what AppProfiles are, how to create one, and how they affect enrichment and quality gating.
  - AC-3: The dashboard settings panel shows the currently active AppProfile name.
  - AC-4: Operators can switch the active AppProfile via a dropdown in the settings panel (persisted to config/env).
- **Key Files**:
  - `backend/kb/profiles/` — docstrings
  - `docs/appprofile.md` (new)
  - `frontend/src/components/SettingsPanel.tsx` (or equivalent)
  - `backend/api/routes.py` — profile switch endpoint
- **Linked Tasks**: None
- **Branch**: feature/FEAT-091-appprofile-docs-ui
- **Created**: 2026-06-03
