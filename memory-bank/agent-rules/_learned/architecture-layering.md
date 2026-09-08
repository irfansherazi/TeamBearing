---
name: Architecture Layering & Single-Insertion-Point Patterns
globs: ["backend/engine/*.py", "backend/**/*.py"]
paths: ["backend/engine/", "backend/kb/"]
topics: ["architecture", "layering", "insertion-point", "retry-chain", "large-legacy-files"]
priority: low
auto_generated: true
derived_from: [FEAT-118-vqa-tier3-architectural-hardening, accessibility-tree-grounding]
evidence_count: 2
last_validated: 2026-07-30
---

# Learned Rules: architecture-layering

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **new-layer-as-first-link-fall-through** (`backend/engine/reflex/`, `backend/engine/evaluator.py`, `backend/engine/recovery_router.py`): When adding a new interception layer to an existing multi-step retry pipeline (e.g., a new deterministic recovery layer in front of an LLM-based recovery pipeline), always insert the new layer as the **first link in the existing chain** with fall-through semantics — never replace, wrap, or modify later links. This preserves proven recovery logic byte-identical, limits the test surface to the new layer only, and enables clean rollback via feature flag on the new layer alone. FEAT-118 Phase 3 evidence: `reflex` layer inserted at `evaluator.py:~1327` BEFORE `recovery_router` with `recovery_router.py` byte-identical; boundary tests in `test_recovery_router.py` confirm hand-off works.
  - _Source_: reflection-FEAT-118-vqa-tier3-architectural-hardening (2026-07-29)
  - _Reinforced_: 0x

- **single-pre-emit-gate-over-inline-patches** (`backend/engine/planner.py`, any file >2000 LOC with multiple fallback sites): When an audit reveals 7+ fallback sites for a pattern (e.g., `get_by_text` fallbacks scattered across a large planner), introduce a single pre-emit gate at the shared entry point (e.g., `_build_action()` entry) rather than patching each site individually. Benefits: (1) single test surface, (2) single maintenance point, (3) zero "missed one site" regression risk, (4) test asserts the gate's behavior once and covers all downstream sites. FEAT-118 Phase 2 evidence: `RegistryFirstGate.check()` at `_build_action()` entry in the 5,460-line `planner.py`; 6 unit tests confirm 0 `get_by_text` on registered targets across all invocation paths.
  - _Source_: reflection-FEAT-118-vqa-tier3-architectural-hardening (2026-07-29)
  - _Reinforced_: 0x
