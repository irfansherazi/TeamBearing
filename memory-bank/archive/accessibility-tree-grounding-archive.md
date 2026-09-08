---
slug: accessibility-tree-grounding
feature: accessibility-tree-grounding
complexity: Level 3
status: COMPLETE
completed: 2026-07-30
---

# Archive: accessibility-tree-grounding — Accessibility Tree Grounding

**Date Completed**: 2026-07-30
**Complexity**: Level 3 (Intermediate feature — NFR / infrastructure)
**Branch**: `feature/accessibility-tree-grounding`
**Roadmap**: `memory-bank/roadmap/accessibility-tree-grounding.md` (umbrella: `agentic-testing-sota-adoption-2026`)

## Executive Summary

Introduced an a11y-first locator resolution chain to vQA's executor. The new `A11yLocatorResolver` prefers `page.get_by_role(role, name=name)` (with a two-tier exact-then-normalized-regex probe) before falling back to the existing CSS/PrimeNG selector and then to the CV/SoM fallback (FEAT-037). Adds `aria_role` / `aria_name` / `aria_disambiguators` to `StructuredACStep`, a canonical 7-value `locator_resolution_path` audit vocabulary on `ExecutionStep.locator_strategy`, an AC-parser ARIA-enrichment pass, a `RecoveryType.A11Y_AMBIGUOUS` recovery action, and verifier evidence annotation.

All 12 acceptance criteria met; 61 new tests (20 + 6 + 35) added across 3 phases; zero suite regressions (1861 passing / 73 pre-existing failures unchanged); clean commit guard on every phase. Rollout is fully gated — three independent flags (`a11y_resolver_enabled`, `a11y_enrichment_enabled`, `recovery_a11y_ambiguous_enabled`) all default **OFF**, so this is a zero-blast-radius deployment. When `aria_role=None`, the executor takes the bit-for-bit `selector_only_legacy` path.

## Phases (3 + Creative × 2) — Commit Timeline

| Phase | Description | Commit SHA |
|-------|-------------|------------|
| Plan | Task provisioned; Level 3 with 2 creative phases required | (plan commits) |
| Creative — Architecture | Module boundaries + enrichment placement (Opus) | (creative commits) |
| Creative — Algorithm | Two-tier probe design + hybrid recovery cascade (Opus) | (creative commits) |
| Phase 1 | Schema + `A11yLocatorResolver` foundation (20 tests) | `ce592b5` (+ guard fix `b464068`) |
| Phase 2 | Executor integration + telemetry + regression fixture (6 tests, 26 cumulative) | `0a5385b` + state `1bb7c70` |
| Phase 3 | Recovery-router + verifier + AC-parser enrichment (35 tests, 61 cumulative) | `b07577e` + state `4627d35` |
| Reflect | Reflection doc (Excellent quality / Highly Effective ecosystem) | `6a59fe7` |

Cumulative: **6 production files modified + 3 production files new, 3 test files new + 2 test files extended, 61 new tests (all passing), no suite regressions**.

## Acceptance Criteria (all 12 met)

See `memory-bank/reflection/accessibility-tree-grounding-reflection.md § Dimension 1` for per-AC verification detail. Summary:

- **AC-VERIFY-1** — `StructuredACStep` schema accepts `aria_role`/`aria_name`/`aria_disambiguators` as `Optional[None]` — backward-compatible: MET
- **AC-VERIFY-2** — AC parser ARIA enrichment (`ac_aria_enricher.py`, 248 LOC) populates fields from live tree; wired into `planner_node` at iteration==1; flag-gated: MET
- **AC-VERIFY-3** — Exact `get_by_role(role, name)` unambiguous match → `resolution_path="a11y_primary"`: MET
- **AC-VERIFY-4** — Zero a11y matches → `selector_fallback` (DEBUG log, CSS locator returned): MET
- **AC-VERIFY-5** — Ambiguous match (N≥2) → `selector_fallback_ambiguous` (WARN log with count; no silent `.first`): MET
- **AC-VERIFY-6** — Both a11y + CSS fail → `cv_fallback_required` signal (no new HITL escalation): MET
- **AC-VERIFY-7** — `ExecutionStep.locator_strategy` populated on every click/fill/check/uncheck: MET
- **AC-VERIFY-8** — `RecoveryType.A11Y_AMBIGUOUS` added, feature-flagged OFF; hybrid disambiguator cascade + Failure Diary guard per Algorithm Decision 2D: MET
- **AC-VERIFY-9** — `aria_role=None` → immediate `selector_only_legacy` with zero a11y probe (bit-for-bit legacy behavior): MET
- **AC-ERROR-1** — Probe exception → WARN log + `selector_fallback_error`; run continues, no propagation: MET
- **AC-ERROR-2** — Exhaustion diagnostic string `A11Y_RESOLVER_EXHAUSTED: tried a11y(...) → 0; tried selector(...) → 0`: MET
- **AC-ASYNC-1** — Verifier evidence annotated with `locator=<resolution_path>` tag: MET

## Key Decisions (from Creative)

All 4 open design questions resolved before code was written across the two Opus creative documents:

| Q | Decision | Rationale |
|---|---|---|
| Arch-Q3 module location | `backend/browser/a11y_resolver.py` mirroring FEAT-037 `cv_resolver.py` | Layer boundary respected; import cycle avoided by passing primitives (not `TestPlanStep`) |
| Arch-Q2 enrichment placement | Post-compilation Python pass (`ac_aria_enricher.py`) invoked from `planner_node` at iteration==1 | Keeps LLM prompt lean; enrichment testable in isolation; safe to feature-flag off |
| Algo-Q1 fuzzy-match policy | Two-tier probe: exact `get_by_role(role, name)` then normalized-regex retry only on N==0 | Normalization can only increase matches — applying it on N≥2 would amplify false positives, so ambiguous fires selector fallback immediately |
| Algo-Q4 `A11Y_AMBIGUOUS` retry | Hybrid: disambiguator whitelist cascade (`aria-label`, `aria-labelledby`, `role`) + Playwright STRICT_MODE tail + Failure Diary guard | Handles the common "2-3 buttons named 'Save'" case without a full recovery loop |

Adversarial critique: SKIPPED (`unresolved:no-companion` — Codex not installed; `availability: auto` silent fallback per project config).

## Files Changed

**Production (9 files: 3 new, 6 modified)**:
- `backend/browser/a11y_resolver.py` — **new** — `A11yLocatorResolver` (355 LOC) with two-tier probe + `_normalize_name` (NFC, casefold, icon glyph strip, ellipsis strip)
- `backend/engine/ac_aria_enricher.py` — **new** — Post-compilation ARIA enrichment pass (248 LOC)
- `tests/fixtures/a11y_css_flake_regression.json` — **new** — PrimeNG trailing-NBSP regression fixture documenting Success Metric #2
- `backend/engine/schemas.py` — extended `StructuredACStep` with `aria_role`/`aria_name`/`aria_disambiguators` Optional fields; extended `ExecutionStep.locator_strategy` vocabulary
- `backend/engine/executor.py` — added `_resolve_locator_a11y_first` + `_A11Y_RESOLVER` singleton; ARIA field injection in `action_with_transient`
- `backend/engine/recovery_router.py` — added `RecoveryType.A11Y_AMBIGUOUS` + `_recover_a11y_ambiguous` handler (hybrid cascade)
- `backend/engine/verifier.py` — `annotate_evidence_with_resolution_path()` inline evidence tag
- `backend/engine/planner_node.py` — wired `ac_aria_enricher` at iteration==1 (feature-flag gated)
- `backend/config/__init__.py` — added `a11y_resolver_enabled` / `a11y_enrichment_enabled` / `recovery_a11y_ambiguous_enabled` (all default False)

**Tests (5 files: 3 new, 2 extended, 61 new tests total)**:
- `tests/test_a11y_resolver.py` — **new** — 20 tests covering all resolution branches + error paths + normalization variants
- `tests/test_executor_a11y_integration.py` — **new** — 6 tests for executor wiring, telemetry, backward compat
- `tests/test_ac_parser_a11y_enrichment.py` — **new** — 17 tests for enrichment hit/miss/ambiguous/empty-tree branches
- `tests/test_recovery_router.py` — extended — coverage for `A11Y_AMBIGUOUS` recovery type + flag gating
- `tests/test_verifier_semantic.py` — extended — resolution-path evidence tag coverage

**Memory Bank (7 files)**:
- `memory-bank/tasks/accessibility-tree-grounding.md` — status transitions through plan → creative → build → reflect → COMPLETE
- `memory-bank/roadmap/accessibility-tree-grounding.md` — status → completed (this archive)
- `memory-bank/creative/accessibility-tree-grounding-architecture.md` — 3 architecture decisions
- `memory-bank/creative/accessibility-tree-grounding-algorithm.md` — 4 algorithm decisions
- `memory-bank/reflection/accessibility-tree-grounding-reflection.md` — Excellent task quality, Highly Effective ecosystem
- `memory-bank/techContext.md` — dual-path config note added (from reflection Memory-Bank Corrections)
- `memory-bank/systemPatterns.md` — test-runtime artifact restoration pattern added (from reflection Memory-Bank Corrections)

## Success Metrics

- ✅ `locator_resolution_path` populated on every click/fill action (wired via `_resolve_locator_a11y_first`)
- ✅ Regression fixture demonstrating a11y path resolving previously-flaky selector (`tests/fixtures/a11y_css_flake_regression.json` — PrimeNG trailing-NBSP case)
- ✅ No existing test regression (1861 passing, 73 pre-existing failures unchanged across all 3 phases)
- ✅ AC-parser ARIA enrichment works when flag on (17 tests in `test_ac_parser_a11y_enrichment.py`)

## Guard & Recovery Log

All 3 phases passed the commit guard:
- **Phase 1**: prod=2 test=1 (C1 clean after restoring test-runtime chromadb/learned_workflows; C2 TDD-invariant satisfied; C3 all files present)
- **Phase 2**: prod=3 test=2 (C1 clean after restoring test-runtime chromadb/learned_workflows; C2 TDD-invariant satisfied; C3 all files present)
- **Phase 3**: prod=6 test=3 (C1 clean after restoring `backend/config.py` dead-file + chromadb; C2 TDD-invariant satisfied; C3 all files present)

**Pattern**: pre-C1 cleanup of test-runtime artifacts required on every phase. Root cause is a documentation gap in build agent instructions — no quality regression, but a recurring friction point. Memory-bank correction applied to `systemPatterns.md` this archive.

## Rollout Safety

All three feature flags default **OFF**:
- `a11y_resolver_enabled` — enable a11y-first resolution in executor
- `a11y_enrichment_enabled` — enable ARIA enrichment pass in planner
- `recovery_a11y_ambiguous_enabled` — enable `A11Y_AMBIGUOUS` recovery action

With flags off, the executor takes `selector_only_legacy` for every step and behavior is bit-for-bit identical to pre-change (verified by `AC-VERIFY-9` test). Post-merge rollout can enable flags independently in shadow mode (enrichment first, then resolution, then recovery) to validate telemetry before any production traffic depends on the new paths.

## Learning Consolidation (Additive)

This archive is a purely additive consolidation — no rules merged, retired, expired, or pruned.

**New `_learned/` rules**:
- `a11y-resolver.md` — Playwright `get_by_role` two-tier probe pattern; fire normalized-regex retry only on N==0, never on N≥2
- `feature-flag-rollout.md` — Independent flags for enrichment vs resolution allow shadow-mode validation before activation

**Appended bullets to existing `_learned/` rules**:
- `testing-patterns.md` — Per-resolution-path-variant test counting for mechanism modules (resolvers, recovery handlers)
- `config-validation.md` — `backend/config/__init__.py` is the active Pydantic settings class; `backend/config.py` root-level is a legacy stub

**Reinforced existing rules** (`derived_from` + `evidence_count` + `last_validated` updated):
- `fuzzy-matching.md` — Jaccard-style word-level matching applied in `ac_aria_enricher.py`
- `browser-patterns.md` — `standalone-verification-capture` pattern reinforced by verifier evidence annotation
- `architecture-layering.md` — `backend/browser/` vs `backend/engine/` split held
- `error-handling.md` — Non-fatal exception fallthrough pattern used for AC-ERROR-1

## References

- **Reflection**: `memory-bank/reflection/accessibility-tree-grounding-reflection.md`
- **Creative — Architecture**: `memory-bank/creative/accessibility-tree-grounding-architecture.md`
- **Creative — Algorithm**: `memory-bank/creative/accessibility-tree-grounding-algorithm.md`
- **Task file**: `memory-bank/tasks/accessibility-tree-grounding.md`
- **Roadmap feature**: `memory-bank/roadmap/accessibility-tree-grounding.md`
- **Umbrella feature**: `agentic-testing-sota-adoption-2026` (candidate 2)
- **FEAT-037 precedent**: `backend/browser/cv_resolver.py` (CV/SoM fallback layer — the module-location model)
- **External reference**: Playwright Test Agents v1.56 (Jan–Jul 2026 expansion), gap analysis §3.1
