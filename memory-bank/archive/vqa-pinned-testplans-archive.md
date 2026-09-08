---
slug: vqa-pinned-testplans
feature: vqa-pinned-testplans
complexity: 3
status: COMPLETE
archived: 2026-08-18
---

# Task Archive: vQA Pinned TestPlans for Deterministic Fail→Pass

**Slug**: `vqa-pinned-testplans`
**Feature**: `vqa-pinned-testplans` (roadmap)
**Complexity**: Level 3
**Started**: 2026-08-18
**Completed**: 2026-08-18
**Reflection**: [`memory-bank/reflection/vqa-pinned-testplans-reflection.md`](../reflection/vqa-pinned-testplans-reflection.md)
**Source Doc**: [`docs/todo/pinned-plans-PR.md`](../../docs/todo/pinned-plans-PR.md)

## Executive Summary

Added an explicit **pinned TestPlan** primitive to vQA so the `/vc` pipeline's red→green transition is a byte-identical replay, not two independent LLM parses. This closes **Lock B** for the `/vc:diagnose → /vc:testwrite → /vc:fix → /vc:testrun` chain — the LLM parser is now *unreachable by construction* when a `plan_id` is presented, not merely "probably deterministic."

All 5 planned phases shipped clean end-to-end with **no regressions**: full suite went from 2047 → 2105 passing, and the 77 pre-existing failures remained unchanged across every phase. Every phase's code review returned APPROVED and every commit guard passed on the first attempt.

## Requirements & Acceptance Criteria — All Met

| AC | Requirement | Verified By | Result |
|---|---|---|---|
| AC-VERIFY-1 | Pinned-plan store round-trips a TestPlan by opaque `plan_id` | `tests/test_pinned_plans.py::TestSaveLoadRoundTrip` | PASS |
| AC-VERIFY-2 | `pinned_plan_ttl_days` config controls expiry (default 14) | `TestConfigSetting`, `TestTTLExpiry` | PASS |
| AC-VERIFY-3 | `ac_parser_node` short-circuits when `state["pinned_plan"]` is set | `tests/test_ac_parser_short_circuit.py` | PASS |
| AC-VERIFY-4 | `POST /preview-steps` persists and returns opaque `plan_id` | `tests/test_execute_plan_id.py::test_preview_steps_persists_and_returns_plan_id` | PASS |
| AC-VERIFY-5 | `POST /execute` with `plan_id` replays verbatim (no LLM/cache/re-parse) | `tests/test_execute_plan_id.py::test_execute_with_pinned_plan_id_replays_verbatim` | PASS |
| AC-ERROR-1 | Unknown `plan_id` → HTTP 404 (never silent re-parse) | `tests/test_execute_plan_id.py::test_execute_unknown_plan_id_returns_404` | PASS |
| AC-ERROR-2 | Expired `plan_id` → HTTP 410 (never silent re-parse) | `tests/test_execute_plan_id.py::test_execute_expired_plan_id_returns_410` | PASS |
| AC-ERROR-3 | Both `plan_id` and `override_steps` → HTTP 400 (mutex) | `tests/test_execute_plan_id.py::test_execute_plan_id_and_override_steps_mutex_400` | PASS |
| **AC-INVARIANT-1** | **`_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` when pinned** | `tests/test_ac_parser_short_circuit.py::TestShortCircuit::test_stages_are_unreachable_when_pinned` | **PASS — load-bearing** |
| EC-COMPAT-1..5 | Additive contract: callers omitting new fields behave identically | `tests/test_additive_contract.py` (7 tests) | PASS |
| OA-1..4 | OpenAPI schema exposes `ExecuteRequest.plan_id`, `PreviewStepsRequest`, `PreviewStepsResponse.plan_id`, POST `/preview-steps` | `tests/test_openapi_pinned_fields.py` (10 tests) | PASS |

**Why AC-INVARIANT-1 matters**: an output-equality assertion passes whenever Bedrock happens to reproduce the parse — `temperature=0.0` is *not* bit-exact deterministic on Bedrock. `call_count == 0` proves the forbidden path is unreachable by construction, which is the correct invariant for a determinism guarantee.

## Implementation Roadmap — Delivery Trace

| Phase | Scope | Commit | Tests (RED→GREEN) | Guard |
|---|---|---|---|---|
| 1 | Pinned-plan store + config (`pinned_plans.py`, `config/__init__.py`) | `ebe1cc8` | 16 → 16 | PASS (prod=2, test=1) |
| 2 | Schemas + state (`schemas.py`, `state.py`) — additive-only | `86ae35a` | 24 → 24 | PASS (prod=2, test=2) |
| 3 | `ac_parser_node` short-circuit + `AC-INVARIANT-1` proof | `14e8110` | 8 → 8 | PASS (prod=1, test=1) |
| 4 | Routes wiring: `POST /preview-steps`, `execute_single` plan_id resolution, lifespan prune | `1cde237` | 7 → 7 | PASS (prod=2, test=1) |
| 5 | Additive-contract + OpenAPI field verification (test-only) | `dcd92cd` | 17 → 17 | PASS (prod=0, test=2) |
| Reflect | Task reflection document | `1979a8c` | — | — |
| Finalize | Task file marked REFLECTION_COMPLETE | `0a56a46` | — | — |

**Cumulative**: 48 new pinned-plan-specific tests; full suite 2047 → 2105 (all Δ from this task); pre-existing 77 failures unchanged across every phase.

## File Touch List

**New production code**
- `backend/engine/pinned_plans.py` — TTL-scoped on-disk store (`storage/pinned_plans/<plan_id>.json`); `save`, `load`, `prune_expired`, `PinnedPlanNotFound`, `PinnedPlanExpired`.

**Extended production code**
- `backend/config/__init__.py` — `pinned_plan_ttl_days` field (default 14).
- `backend/api/schemas.py` — `ExecuteRequest.plan_id`, `PreviewStepsRequest` (new POST variant), `PreviewStepsResponse.plan_id`.
- `backend/engine/state.py` — `pinned_plan` + `pinned_plan_id` fields on `VQAState`.
- `backend/engine/ac_parser.py` — short-circuit block at top of `ac_parser_node`.
- `backend/api/routes.py` — new `POST /preview-steps` handler; `execute_single` resolves `plan_id` before invoking the parser.
- `backend/main.py` — startup `lifespan()` calls `pinned_plans.prune_expired()`.

**New tests**
- `tests/test_pinned_plans.py` (16 unit tests — store roundtrip, TTL expiry, prune, config)
- `tests/test_schemas_pinned_plans.py` (15 tests — schema additivity)
- `tests/test_state_pinned_plans.py` (9 tests — state defaults + roundtrip)
- `tests/test_ac_parser_short_circuit.py` (8 tests — includes the load-bearing AC-INVARIANT-1)
- `tests/test_execute_plan_id.py` (7 tests — 404/410/mutex-400 + verbatim replay)
- `tests/test_additive_contract.py` (7 tests — EC-COMPAT-1..5)
- `tests/test_openapi_pinned_fields.py` (10 tests — OA-1..4)

## Drift Handled at Planning Time (free — no build cost)

The source doc referenced `backend/api/app.py` for the startup lifespan hook. That file does not exist — the lifespan handler lives in `backend/main.py:139`. The Spec Writer's codebase-verification pass caught this at plan time and recorded a `DRIFT NOTE` in the task file; Phase 4 read that note and wired the prune into the existing `lifespan()` block. Zero debugging cost.

This became learning: `planning-time-drift-notes` in `_learned/workflow-compliance.md`.

## Level-3 Fast Path: Creative Skipped, Design Was Externalized

`Creative Exploration Needed: **No.**` was the correct call. The source-of-truth doc (`docs/todo/pinned-plans-PR.md`) had already resolved the single design fork (new pinned-plan primitive vs. re-use `ac_parse_cache.py`) with verbatim diffs, concrete file targets, and named test cases. The Spec Writer's codebase-verification pass provided the drift-catching safety net that a creative session would have provided — and no phase required re-architecture in flight.

This became learning: `external-plan-doc-creative-waive` in `_learned/workflow-compliance.md`. **Gap flagged**: no structured `creative_waived_reason` field yet distinguishes "external plan doc" from a low-complexity waive — reason lives in prose only.

## Learning Consolidation (Step 4B)

Three learnings from the reflection folded into two existing topic files (additive-only; no merges, retirements, or expirations — this is an **additive** consolidation, not mutating):

**`_learned/testing-patterns.md`** (evidence 7 → 8)
- Added: `assert-mechanism-not-just-output-for-invariants` — call_count == 0 vs. output equality for correctness-critical invariants.

**`_learned/workflow-compliance.md`** (evidence 4 → 5)
- Added: `external-plan-doc-creative-waive` — legitimate Level-3 fast-path when a source-of-truth external doc has already done the design.
- Added: `planning-time-drift-notes` — Spec Writer must document source-doc-to-repo drift at plan time, not defer to build phase.

`derived_from` on both files now includes `vqa-pinned-testplans`; `last_validated` set to `2026-08-18`. Neither promotion nor pruning triggered.

**Reindex not run**: `agent-rules-index.md` has pre-existing stale line-count entries and my edits were purely additive (no globs/paths/topics changed). A future `/bmb:rules-index` should refresh the whole index; not this archive's responsibility.

## Security & Dependencies

- **Zero new packages**: stdlib only (`json`, `pathlib`, `uuid`, `time`).
- **No credentials/PII** in pinned plan files; `plan_id` is opaque UUID4.
- **No injection surface**: writes are atomic (tempfile + rename); reads are `json.load` on a resolved path constrained under `storage/pinned_plans/`.
- **Never-silent-fallback**: unknown/expired/mutex conditions all return typed HTTP errors (404/410/400) — the LLM parser is never invoked as a fallback.
- **No new external services, AWS resources, or IAM changes**.

## Observability

New structured INFO logs from `backend.engine.pinned_plans`:
- `pinned_plans SET <plan_id>` — on `POST /preview-steps` save
- `pinned_plans HIT <plan_id>` — on `ac_parser_node` short-circuit
- `pinned_plans MISS <plan_id> reason=<not_found|expired>` — on 404/410 paths
- `pinned_plans PRUNED count=<N>` — on startup lifespan prune

## Ecosystem Improvements Flagged (Not Implemented)

The reflection identified three workflow gaps — flagged here for a future roadmap item, **not implemented in this task**:

1. **Task-scoped agent log indexing missing for v2 slug-based tasks**: `.agent-logs/claude/by-task/vqa-pinned-testplans/` did not exist during reflection, so tool-use / sub-agent invocation counts could not be extracted mechanically. The reflection fell back to task-file Execution State prose. Adds friction to ecosystem-effectiveness measurement.
2. **`creative_waived_reason` structural field**: today the reason for skipping `/bmb:creative` lives only in the task file prose. A structured field (`external-plan-doc` | `too-simple` | `spec-writer-flagged-none-needed`) would let discovery aggregate the shape of Level-3 workloads.
3. **Baseline failure count in task frontmatter**: this task's guard log carries "77 pre-existing failures unchanged" as prose across five phases. Encoding the baseline as a frontmatter field would let the commit guard enforce "no new failures" mechanically instead of relying on human-parseable prose.

## Related Documents

- **Reflection**: [`memory-bank/reflection/vqa-pinned-testplans-reflection.md`](../reflection/vqa-pinned-testplans-reflection.md)
- **Task file**: [`memory-bank/tasks/vqa-pinned-testplans.md`](../tasks/vqa-pinned-testplans.md)
- **Roadmap feature**: [`memory-bank/roadmap/vqa-pinned-testplans.md`](../roadmap/vqa-pinned-testplans.md)
- **Source design doc**: [`docs/todo/pinned-plans-PR.md`](../../docs/todo/pinned-plans-PR.md)

## Commit Timeline

```
dc822ed  plan: scaffold task + link to feature
a4eea1b  plan: planning complete (Level 3, 5 phases)
ebe1cc8  feat: Phase 1 — pinned TestPlan store + config
2b50b6b  chore: update execution state after Phase 1 commit
86ae35a  feat: Phase 2 — pinned TestPlan schemas + state
14e8110  feat: Phase 3 — ac_parser_node short-circuit
1cde237  feat: Phase 4 — routes wiring (Lock B)
dcd92cd  feat: Phase 5 — additive contract verification + OpenAPI field checks
1979a8c  reflect: add task reflection — Level 3, 5 phases, all ACs met
0a56a46  chore: mark REFLECTION_COMPLETE
```

Base: `origin/main` @ `8a5ffba`. 17 files changed, +3075 / -1.
