# vQA Technical Debt Report
*Synthesized from 31 reflection files: TASK-001 → TASK-050*  
*Generated: 2026-05-21*

---

## Executive Summary

After cross-analyzing all 31 post-task reflections, **five critical engine-level debt items** have been open since early in the project and remain unresolved. The codebase is well-architected overall — Level 4 tasks ship clean with zero regressions — but a cluster of **architectural contract mismatches** in `VQAState`, **under-tested subsystems** (frontend, live E2E), and **recurring process gaps** (status header drift, missing `ruff`/`pyflakes` gate) are generating compounding maintenance cost.

---

## 🔴 Critical (Engine-breaking or data-integrity risk)

### TD-001 · `recipe_runner.py` Idempotency Pre-check — MITIGATED (TASK-054)
- **Mitigation**: Refactored to support `force_wait_before_next` and `force_wait_ms` signals. Interaction blueprints retrofitted.

### TD-002 · `VQAState` Architectural Contract Mismatch — MITIGATED (TASK-054)
- **Mitigation**: Added `ac_steps_coverage_gap: list[int]` to `VQAState`.

### TD-003 · 7 Pre-existing Test Failures — MITIGATED (TASK-054)
- **Mitigation**: Hardened `VQAState` and resolved failures in `test_evaluator_hardening.py`.

---

## 🟠 High (Compounding maintenance cost, production-visible defects)

### TD-004 · No Static Analysis Gate — MITIGATED (TASK-054)
- **Mitigation**: Integrated `ruff` and updated `Makefile`.

### TD-005 · `failure_classifier.py` Dead Code — OPEN

### TD-006 · `dropdown_registry.json` Manual Curation — MITIGATED (TASK-054)
- **Mitigation**: Created `scripts/sync_dropdown_registry.py` for auto-sync.

### TD-007 · Frontend Unit Tests — MITIGATED (TASK-054)
- **Mitigation**: Established Vitest suite with core coverage.

### TD-008 · `ExplorationRunner` Integration Test — OPEN

### TD-009 · `AcceptedTestStore` Local-only — OPEN

### TD-010 · `last_used` Pruning Logic — MITIGATED (TASK-054)
- **Mitigation**: Implemented age/count-based pruning.

---

## 🟡 Medium (Process friction, not engine-breaking)

### TD-011 · `**Status**` Header Drift in Task Files — OPEN

### TD-012 · `TestMatcher` Class Warning — MITIGATED (TASK-054)
- **Mitigation**: Renamed to `JiraTestMatcher` and added `__test__ = False`.

### TD-013 · `SelectorRAG` Pickle Serialization — MITIGATED (TASK-054)
- **Mitigation**: Implemented JSON manifest fallback.

### TD-014 · Blueprint Coverage Gap — MITIGATED (TASK-054)
- **Mitigation**: Retrofitted 4 major blueprints with verification assertions.

### TD-015 · Missing `anyio_mode` in pytest Config — MITIGATED (TASK-054)
- **Mitigation**: Added to `pyproject.toml`.

### TD-016 · `VNC Event Debouncing` — MITIGATED (TASK-054)
- **Mitigation**: Implemented time-based debouncing in injection layer.

### TD-017 · `Shadow DOM SoM Gap` — MITIGATED (TASK-054)
- **Mitigation**: Pierced shadow roots in accessibility and SoM logic.

### TD-018 · `JIRA_AC_FIELDS` Hardcoded — MITIGATED (TASK-054)
- **Mitigation**: Implemented override capability.

### TD-019 · Boilerplate Duplication in Tests — OPEN

### TD-020 · No E2E Test for WebSocket — MITIGATED (TASK-054)
- **Mitigation**: Added E2E handshake verification.


---

## 🟢 Low / Nice-to-Have

| ID | Item | Source |
|----|------|--------|
| TD-021 | `component_registry.py` file removal (deprecated but left as file) | TASK-001 |
| TD-022 | `FEAT-006` synonym expansion in `LocalKnowledgeBase._SYNONYM_MAP` | TASK-001 |
| TD-023 | `reflection-agent-prompt.md` is a one-line stub — merge or remove | TASK-030 |
| TD-024 | AC checkbox auto-marking at test-authoring time (not deferred to reflection) | TASK-030 |
| TD-025 | Benchmark script as standard `/vc-verify --benchmark` flag (not per-task one-off) | TASK-030 |
| TD-026 | No `memory-bank/technical-debt.md` as a first-class file — this report should become it | TASK-001 |
| TD-027 | `tasks.md` registry auto-sync on task completion | TASK-032, TASK-018 |
| TD-028 | Report line: Phase gate conflict — Level 1 archive blocks on reflection even when marked optional | TASK-048 |
| TD-029 | `vision_token_usage` in `VQAState` — telemetry tracked but not exported to frontend | TASK-047 |
| TD-030 | `PDF support` in `VisionAnalyzer` (many Jira tickets attach PDF mockups) | TASK-047 |
| TD-031 | `CLIP-based image selection` for high-attachment Jira tickets | TASK-047 |
| TD-032 | CSS/CORS explicit headers for VNC iframe (currently implicit) | TASK-033 |
| TD-033 | Live run telemetry for `ExplorationRunner` (≥70%/≥40% targets not yet measurable) | TASK-029 |
| TD-034 | RAG index: very short AC steps (2-word) may produce sparse TF-IDF vectors | TASK-030 |
| TD-035 | Blueprint corpus thin (10 YAMLs) — future growth needs per-step chunking | TASK-030 |
| TD-036 | Playwright Registry Auto-Sync: Manual management of test discovery is fragile | TASK-059 |
| TD-037 | Playwright Dependency Injection: No standard way to pass dashboard secrets to static tests | TASK-059 |
| TD-038 | Rich Terminal Log Parsing: Logs are raw text; missing rich failure traces/screenshots in UI | TASK-059 |
| TD-039 | Execution Engine State Management: VQAState bloat from engine-specific fields | TASK-059 |
