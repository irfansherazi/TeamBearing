---
legacy_id: FEAT-090
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-090: KB Theme Detection Synonym Expansion
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 2
- **Pillar**: P4 — Knowledge Base / Domain Context
- **Gap ID**: P4-C
- **Estimated Effort**: ~2h
- **Description**: KB enrichment theme detection is exact-match keyword only, causing synonyms like "condensed layout" to miss themes matched by "compact view". Fix: replace exact-match keyword lookup with a synonym-aware mapping (static dictionary) so common synonyms resolve to the same theme key.
- **Acceptance Criteria**:
  - AC-1: Theme detection supports a configurable synonym dictionary (e.g., `{"compact view": ["condensed layout", "dense view", "small view"]}`).
  - AC-2: Synonym matches produce the same theme enrichment as exact matches.
  - AC-3: The synonym dictionary is stored in `backend/kb/theme_synonyms.json` for easy operator extension.
  - AC-4: Unit tests cover at least 3 synonym pairs per existing theme keyword.
- **Key Files**:
  - `backend/kb/rag.py` — theme detection
  - `backend/kb/theme_synonyms.json` (new)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-090-kb-theme-synonym-expansion
- **Created**: 2026-06-03
