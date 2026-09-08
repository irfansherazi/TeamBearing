---
legacy_id: FEAT-076
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-076: ADF Blockquote & InlineCard Node Support
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 1
- **Pillar**: P1 — Jira Ingestion
- **Gap ID**: P1-B
- **Estimated Effort**: <30min
- **Description**: ADF `blockquote` and `inlineCard` nodes are currently silently dropped by `_extract_text_from_adf()`, losing NOTE/Prerequisite preconditions and Jira issue cross-references. Fix: handle `blockquote` by extracting its inner text with a `> ` prefix, and handle `inlineCard` by emitting its `url` attribute as a markdown link.
- **Acceptance Criteria**:
  - AC-1: `blockquote` ADF nodes are extracted with `> ` prefix (not silently dropped).
  - AC-2: `inlineCard` ADF nodes emit their `url` attribute as a `[Jira ref](url)` markdown fragment.
  - AC-3: No regression on existing ADF node types (paragraph, bulletList, orderedList, codeBlock, etc.).
- **Key Files**:
  - `backend/jira/client.py` — `_extract_text_from_adf()`
- **Linked Tasks**: None
- **Branch**: feature/FEAT-076-adf-blockquote-inlinecard
- **Created**: 2026-06-03
