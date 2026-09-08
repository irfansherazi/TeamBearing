---
legacy_id: FEAT-097
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-097: AppProfile-Driven Quality Gate Keywords
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 2
- **Pillar**: P6 — Test Coverage & Quality Gates
- **Gap ID**: P6-B
- **Estimated Effort**: ~4h
- **Description**: The quality gate keyword lists (`_SPECIFIC_COMPONENT_PATTERNS`) are hardcoded vSuite strings, causing all AC to score POOR when vQA is run against any other application. Fix: move `_SPECIFIC_COMPONENT_PATTERNS` into `AppProfile` so each profile defines its own component vocabulary. The default vSuite profile retains existing keywords; new profiles start with empty lists.
- **Acceptance Criteria**:
  - AC-1: `_SPECIFIC_COMPONENT_PATTERNS` is removed from `ac_quality_gate.py` and moved into the `AppProfile` schema.
  - AC-2: The vSuite `AppProfile` retains all existing keyword entries.
  - AC-3: A new blank `AppProfile` (no keywords) does not cause AC to score POOR by default.
  - AC-4: Quality gate tests are updated to use profile-injected keywords.
- **Key Files**:
  - `backend/engine/ac_quality_gate.py`
  - `backend/kb/profiles/` — `AppProfile` schema
- **Linked Tasks**: None
- **Branch**: feature/FEAT-097-appprofile-quality-keywords
- **Created**: 2026-06-03
