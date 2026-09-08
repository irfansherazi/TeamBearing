---
legacy_id: FEAT-002
version: v1.1.0
linked_tasks: []
status: complete
---

### FEAT-002: Domain-Aware AC Enrichment Engine
- **Version**: v1.1.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Pre-processing enrichment stage that runs BEFORE Stage 1 BDD normalization in the AC parsing pipeline. Detects workflow domains from ticket summary + AC text (9 domain categories: table_sort, quick_order, voice_workflow, login_auth, file_upload, approval_flow, view_navigation, status_change, date_picker) and queries the KB using FEAT-006's BM25 + synonym expansion to retrieve relevant workflow articles. Builds an XML-tagged `<domain_context>` block appended to the raw AC text, providing the Stage 1 BDD normalizer with grounded domain facts (component names, interaction patterns, preconditions) to eliminate hallucination. Zero LLM cost — purely KB-retrieval + template-based enrichment. Integrated as a function called from ac_parser_node (not a separate LangGraph node) for simplicity. Enrichment applies to all passing quality grades (good + fair). Graceful no-op when no domains detected or KB returns no articles. HTML reporter shows enrichment banner with detected domains and KB articles used. 30 tests passing, 0 regressions on FEAT-001 (38 tests).
- **Linked Tasks**: None
- **Branch**: feature/FEAT-002-ac-enrichment-engine
- **Created**: 2026-05-07
- **Completed**: 2026-05-08
