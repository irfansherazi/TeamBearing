---
legacy_id: add-vtrade-user-personas
---
# add-vtrade-user-personas: Add vTrade User Personas

**Complexity**: Level 2
**Status**: IN_PROGRESS
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: Medium
**Branch**: feature/vtrade-personas

## Problem Statement
The vQA execution panel needs to support testing with specific vTrade user roles. Currently, these roles are not available in the role selection dropdown, and their personas (credentials, permissions, and constraints) are not defined in the backend.

## Proposed Solution
Add three new vTrade roles to the system:
1. **vTrade Exec** (`imail-test+vTradeExec@vcreativeinc.com`)
2. **vTrade Business Manager** (`imail-test+vTradeBusinessManager@vcreativeinc.com`)
3. **vTrade Sales Manager** (`imail-test+vTradeSalesManager@vcreativeinc.com`)

This requires updates to:
- Backend API schemas for validation.
- Backend role registry and aliases for credential resolution and planning constraints.
- Frontend types and display names for the UI dropdown.

## Execution State
### Phase 1: Documentation (COMPLETE)
- [x] Create add-vtrade-user-personas.md
- [x] Register task in tasks.md

### Phase 2: Backend Updates (COMPLETE)
- [x] Update `VALID_ROLES` in `schemas.py`
- [x] Update `ROLE_REGISTRY` and `ROLE_ALIASES` in `roles.py`
- [x] Update `_VSUITE_ROLES` in `vsuite.py` profile

### Phase 3: Frontend Updates (COMPLETE)
- [x] Update `RoleKey` and `ROLE_DISPLAY_NAMES` in `types/index.ts`

### Phase 4: Validation (COMPLETE)
- [x] Verify roles appear in frontend dropdown
- [x] Verify backend validation passes for new roles
