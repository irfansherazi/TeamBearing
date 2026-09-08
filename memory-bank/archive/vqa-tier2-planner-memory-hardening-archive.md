---
slug: vqa-tier2-planner-memory-hardening
feature: FEAT-117-vqa-tier2-planner-memory-hardening
legacy_id: FEAT-117
complexity: Level 4
status: COMPLETE
completed: 2026-07-28
---

# Archive: vqa-tier2-planner-memory-hardening — vQA Tier 2, Planner & Memory Hardening (Structural)

**Date Completed**: 2026-07-28
**Complexity**: Level 4 (Enterprise/architectural changes)
**Branch**: `feature/FEAT-117-vqa-tier2-planner-memory-hardening`
**Worktree**: `.worktrees/FEAT-117` (preserved post-archive; auto-removed at next discovery)

## Executive Summary

FEAT-117 delivered five structural reliability fixes to the vQA LangGraph engine, addressing the failure modes surfaced by the 2026-07-27 QA-358 analysis:

- **T2-a — Deterministic AC Parsing**: content-hash disk cache (`storage/ac_parse_cache/`) + `temperature=0.0` + min/max step gate. Same ticket now parses to a byte-identical step array across runs.
- **T2-b — HITL Playwright Tracing Memory**: replaced the amnesic JS click-capture listener with a Playwright tracing session (`.zip` per takeover) + a synchronous trace-to-Recipe parser inside `human_takeover_node`. Every HITL now becomes a replayable Recipe.
- **T2-c — Diagnostic Routing for `mark_id=None`**: eliminated the silent `get_by_text` DOM click fallback that re-emitted the exact failure it was meant to escape. CV vision misses now surface as diagnostic prompt fragments ("open a container", "scroll", "try synonyms") to the planner.
- **T2-d — Split Verifier (DomVerifier + VisionVerifier cascade)**: fast DOM check runs BEFORE any Sonnet vision call. Default probe set resolves >= 60% of transitions without an LLM call; wall-clock savings >= 500ms / >= 90% token cost reduction per DOM-resolved case.
- **T2-e — PromptBudget Eviction Priority**: `evictable: bool = True` field on `PromptSection`; `reasoning_workflow`, `current_task`, `interactive_elements`, `selector_hints`, `skill_hints` marked `evictable=False`; `EVICTION_FIRST_NAMES` enforces failure-diary-first drop order.

All 8 acceptance criteria met (AC-INTEGRATION-1 deferred to manual live-run per test strategy). 30 new pytest tests, 11 production files, 4 fixture files, 1 backfill script. 271/280 tests pass (9 pre-existing failures unchanged, all unrelated). Ruff clean on all new files.

## Phases (5) — Commit Timeline

| Phase | Description | Commit SHA |
|-------|-------------|------------|
| Phase 1 | T2-a — Deterministic AC Parsing (content-hash disk cache + min/max step gate) | `a4a75f3` |
| Phase 2 | T2-b — HITL Playwright Tracing Memory (trace session + Recipe parser) | `343ff9b` (+ `ed5d682` chore) |
| Phase 3 | T2-c — Diagnostic routing for `mark_id=None` (planner fragment + executor diagnostic) | `aceaec3` |
| Phase 4 | T2-d — Split Verifier (DomVerifier + VisionVerifier cascade) | `4767ed3` |
| Phase 5 | T2-e — PromptBudget Eviction Priority (`evictable` field + enforced ordering) | `68b1693` |
| Reflect | Reflection document (Success rating, 4 extractable learnings) | `15b0f3f` (+ `8836489` status bump) |

Plan/creative preambles: `0a87e60` (plan), `1125e4d` (creative — Architecture Design, 1049 lines resolving Q1/Q2/Q3).

## Acceptance Criteria (all 8 met)

See `memory-bank/reflection/vqa-tier2-planner-memory-hardening-reflection.md § Dimension 1` for per-AC verification detail. Summary:

- **AC-VERIFY-1** — Deterministic parse across 5 runs: MET (`test_ac_parser_determinism.py::test_same_ticket_same_steps`)
- **AC-VERIFY-2** — Cache invalidates on content change; hit < 50ms: MET (2 tests)
- **AC-VERIFY-3** — Playwright tracing `.zip` per HITL + Recipe emission: MET (2 tests, `test_hitl_tracing.py`)
- **AC-INTEGRATION-1** — QA-358 Contest dropdown auto-replay: DEFERRED to post-archive manual live probe (per spec)
- **AC-VERIFY-4** — `mark_id=None` diagnostic routing, no text-click fallback: MET (`test_cv_fallback_diagnostic.py`)
- **AC-VERIFY-5** — DomVerifier >= 60% resolution; >= 500ms & >= 90% token savings: MET (3 tests, `test_verifier_split.py`)
- **AC-VERIFY-6** — False-NOT_YET rate <= 10% on 50-case set: MET (`test_verifier_split.py::test_false_not_yet_rate_at_most_10pct`)
- **AC-VERIFY-7** — PromptBudget `evictable` protects reasoning/interactive/current-task; diary trimmed first: MET (3 tests, `test_prompt_budget.py`)
- **AC-ERROR-1** — Trace-parse failure surfaced (WARN log + zip preserved + no stub recipe): MET (`test_hitl_tracing.py::test_trace_parse_failure_surfaces_and_preserves_zip`)

## Test Artifacts

- **30 new pytest tests** (spec target was 15 — over-delivered on T2-b tracing and T2-e budget coverage)
- **11 production files** modified or created (`ac_parser.py`, `ac_parse_cache.py` new, `human_takeover.py`, `hitl_trace_parser.py` new, `recipe_runner.py`, `cv_resolver.py`, `planner.py`, `executor.py`, `state.py`, `verifier.py`, `prompt_budget.py`)
- **4 fixture files** (`verifier_transitions.jsonl`, `verifier_false_not_yet.jsonl`, `hitl_trace_sample.zip`, `hitl_trace_empty.zip`)
- **1 backfill script** (`scripts/backfill_ac_parse_cache.py`)

Full test suite: 271 pass / 9 pre-existing failures unchanged (`test_aria_pruning`, `test_hitl_learning`, `test_matcher` ×3, `test_selector_completeness` ×4 — all data/env-dependent, unrelated to this feature). Ruff PASS on all new files.

## Learning Consolidation

Additive-only. Four learnings extracted, applied to `memory-bank/agent-rules/_learned/`:

| Learning | Rule File | Action |
|---|---|---|
| DomVerifier → VisionVerifier cascade + `StateExpectation` + `verifier_path` telemetry | `verification-patterns.md` | APPEND (new bullet + frontmatter bump: `evidence_count` 4→5, `derived_from` += slug, `last_validated` → 2026-07-28) |
| Synchronous HITL trace-parse in-node + result-dataclass never-raise + preserve `.zip` on failure | `memory-patterns.md` | CREATE (new file, 5 bullets; no overlap with existing rules) |
| `PromptSection.evictable` field + `EVICTION_FIRST_NAMES` + protect reasoning_workflow / current_task / interactive_elements | `prompt-budget.md` | CREATE (new file, 4 bullets; `context-budget.md` covers reference-not-copy for artifacts — no overlap with eviction ordering) |
| SHA-256 content-hash cache key for LLM outputs + `temperature=0.0` on cache-miss + min/max gate before cache write + layer-above-not-replace | `caching-patterns.md` | CREATE (new file, 5 bullets; `storage-layer-pattern.md` covers generic filesystem stores — no overlap with LLM-output determinism) |

No mutating changes to existing rules (`verification-patterns.md` was additive-append with frontmatter bump). No mass consolidation performed on unrelated rules.

**Post-archive human action**: run `/bmb:rules-index` to regenerate `memory-bank/agent-rules-index.md` (it lists 30 rules today; the index is mechanically generated and was not updated by this archive).

## Follow-ups (Suggested, from Reflection Doc)

1. **AC-INTEGRATION-1 manual live probe** (Highest priority — must happen soon after merge): `python -m backend.cli --ticket QA-358 --role qa_analyst` twice. First run to seed HITL memory when the Contest dropdown step triggers HITL; second run to verify the auto-generated Recipe drives the dropdown open + selects "Contest" without re-HITL. Success = `execution_log.jsonl` shows `strategy: "recipe"` on the Contest step in run 2. This is the end-to-end validation of the T2-b path in production.

2. **`scripts/commit-guard.sh TEST_RE` Python extension** (High priority ecosystem fix): The commit-guard fired C2 false-positive on ALL 5 phases because `TEST_RE` doesn't match Python's `test_*.py` beside-source convention. One-line regex extension: add `\btest_[a-zA-Z0-9_]+\.py\b` to the alternation. Fix carries no false-negative risk for JS/TS.

3. **By-task log slug-keying fix** (Medium priority): `.agent-logs/claude/by-task/` currently keys on legacy numeric `TASK-117`, which collides with a pre-migration task of the same numeric ID. Switch to slug-based keying (`vqa-tier2-planner-memory-hardening/`) to eliminate the ambiguity.

## Documents

- **Reflection**: `memory-bank/reflection/vqa-tier2-planner-memory-hardening-reflection.md` (264 lines — Executive Summary, 8-AC verification detail, code quality assessment, tech decisions, ecosystem effectiveness, extractable learnings)
- **Task file**: `memory-bank/tasks/vqa-tier2-planner-memory-hardening.md` (Level 4, 5 phases, 8 ACs, full Execution State log)
- **Creative doc**: `memory-bank/creative/vqa-tier2-planner-memory-hardening-architecture.md` (1049 lines — resolved Q1/Q2/Q3: sync trace-parse, hybrid DomVerifier, top-N Jira re-fetch backfill)
- **Roadmap feature**: `memory-bank/roadmap/FEAT-117-vqa-tier2-planner-memory-hardening.md` (status: completed; linked_tasks: [vqa-tier2-planner-memory-hardening])

---

## Post-Archive Verification (AC-INTEGRATION-1) — 2026-07-28

Ran the deferred manual live probe against `two-test.vcreative.net` immediately after PR #48 merged. **Result: AC-INTEGRATION-1 FAILED.** No Recipe was produced by run 1 (the direct-browser HITL); run 2 was skipped as there was nothing to replay. See the reflection doc's *Post-Archive Verification* section for full evidence and root-cause analysis.

### One-line summary

Playwright's `tracing.start()` records **Playwright API actions**, not native user input on a headful browser. When the operator clicks the PrimeNG p-select directly in the popped-up Chromium window, those events never reach Playwright's dispatcher, so `trace.trace` has only `context-options` + `screencast-frame` entries — no `Action` records for the parser to convert. The parser correctly returns `NO_INTERACTIVE_EVENTS` and preserves the zip (AC-ERROR-1 works as designed).

### Outcome by AC (updated)

| AC | Status | Note |
|---|---|---|
| AC-VERIFY-1, AC-VERIFY-2, AC-VERIFY-5, AC-VERIFY-6, AC-VERIFY-7 | ✓ MET | Automated (unchanged from archive) |
| AC-ERROR-1 | ✓ MET | Verified by live probe |
| AC-VERIFY-3a (trace zip per HITL) | ✓ MET | Verified by live probe (1.86 MB zip) |
| AC-VERIFY-3b (trace parses into Recipe) | ✗ FAILED (outcome unreachable via direct-browser HITL) | Parser is correct; no interactive events available to extract |
| AC-4 (dropdown Recipe replays; skipped-KB line no longer appears) | ✗ FAILED | No Recipe produced; "KB auto-update skipped" line still fires |
| AC-INTEGRATION-1 | ✗ FAILED | Depends on AC-4 |

### Follow-up

Follow-up roadmap feature **`FEAT-119: HITL Portal-Aware Click Capture`** was created in the same PR as this amendment. Approach F1: restore a JS click-capture listener attached on `document.body` in capture phase, listen for `composed: true` events (Shadow DOM / portals), and route event data via CDP `Runtime.addBinding` so events survive PrimeNG's `stopPropagation()`. This addresses the actual root cause (the old JS listener's event-phase and portal handling), not the framework choice.

Feature branch is unblocked; `feature/FEAT-117-vqa-tier2-planner-memory-hardening` remains cleanly merged. This finding is durable and does not warrant reverting T2-b — its plumbing, error handling, and non-HITL side effects are all correct.
