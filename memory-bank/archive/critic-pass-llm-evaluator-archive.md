---
slug: critic-pass-llm-evaluator
feature: critic-pass-llm-evaluator
complexity: Level 3
status: COMPLETE
completed: 2026-07-30
---

# Archive: critic-pass-llm-evaluator — Critic-Pass LLM Evaluator

**Date Completed**: 2026-07-30
**Complexity**: Level 3 (Intermediate feature)
**Branch**: `feature/critic-pass-llm-evaluator`
**Roadmap**: `memory-bank/roadmap/critic-pass-llm-evaluator.md`

## Executive Summary

Inserted a Haiku LLM critic pass between AC parsing (Stage 2) and browser execution (Stage 3) that re-reads the acceptance criteria against the compiled TestPlan and flags drift before any browser time is spent. On `mismatch`, the critic emits typed reason codes and a `feedback_summary` that feeds back into `ac_parser` for one bounded retry cycle (max 2). Mirrors the Playwright Healer / Anthropic Skill Creator test-measure-refine loop.

All 8 acceptance criteria met; 27 new unit tests added across 3 phases; zero regressions; zero guardrail misses. Delivered as a single `/bmb:auto-build` continuous run — plan through BUILD_COMPLETE in one orchestrated pass with no deviations recorded.

## Phases (3 + Creative) — Commit Timeline

| Phase | Description | Commit SHA |
|-------|-------------|------------|
| Plan | Auto-provision + planning (Level 3, 3 phases + creative) | `a81413c`, `624ac5e` |
| Creative | Architecture Design — 4 questions HIGH confidence; Q4 evidence-based refutation | `a0cb991` |
| Auto-build init | Execution state seeded | `08318ac` |
| Phase 1 | Verdict schema + critic node core (schemas.py, state.py, critic_node.py, config.py, 16 tests) | `26f6fb5` |
| Phase 2 | Graph wiring + ac_parser feedback integration (graph.py both graphs, ac_parser.py 2-turn HumanMessage, 4 topology tests) | `8b2cead` |
| Phase 3 | Observability + grounded-verdict verification (reporter.py `_render_critic_pass_section`, `run_metrics.critic_verdicts`, WebSocket broadcast, 7 tests) | `298abc3` |
| Reflect | Reflection document (Good rating, 3 extractable learnings) | `80ce798`, `819997f` |

Cumulative: **11 files changed, +1928 insertions, 27 new tests (all passing)**.

## Acceptance Criteria (all 8 met)

See `memory-bank/reflection/critic-pass-llm-evaluator-reflection.md § Dimension 1` for per-AC verification detail. Summary:

- **AC-VERIFY-1** — Critic registered in both `build_graph()` and `build_supervisor_graph()`; static bypass guard inside `critic_node`: MET
- **AC-VERIFY-2** — `CriticVerdict` Pydantic schema (flat `Literal[...]` reason_codes + peer `feedback_summary`); 5 schema tests: MET
- **AC-VERIFY-3** — `route_after_critic` returns `"setup_role"` on pass; state identity preserved: MET
- **AC-VERIFY-4** — `mismatch` + `retry_count < 2` → `ac_parser` with 2-turn HumanMessage feedback: MET
- **AC-VERIFY-5** — `retry_count == 2` → route to `"setup_role"` with WARNING log; retry cap enforced: MET
- **AC-ERROR-1** — Haiku API exception → `_SYNTHETIC_PASS` (`critic_skipped=True`); no run abort: MET
- **AC-INTEGRATION-1** — `_render_critic_pass_section()` renders badge, reason codes, feedback_summary; grounded reasons in HTML audit report: MET
- **AC-ASYNC-1** — `_broadcast_critic_mismatch()` lazy-imports `_ws_connections`; non-fatal; < 500ms broadcast: MET

## Key Decisions (from Creative)

All 4 architecture questions resolved at HIGH confidence in one creative pass:

| Q | Decision | Rationale |
|---|---|---|
| Q1 verdict schema | Flat `Literal[...]` reason_codes + peer `feedback_summary: str` | Mirrors existing `VerifierResult` pattern (`verifier.py:275-295`); minimal Pydantic surface |
| Q2 feedback grammar | 2-turn HumanMessage; `BDD_NORMALIZER_PROMPT` byte-identical | Preserves Bedrock implicit prompt cache; saves ~1.2-1.6s per retry cycle |
| Q3 retry counter | Per-run `critic_result.retry_count` inside verdict dict | Matches every existing retry counter (Failure Diary pattern) |
| Q4 pipeline placement | `ac_parser → critic → setup_role` (position A) | **Refuted plan's LOW-confidence hypothesis**: `role_key` already in `initial_state["role_queue"][0]` + `ROLE_REGISTRY` lookup, so `persona_mismatch` works at position A with zero login cost. Saves 5-10s per mismatch retry. |

Creative critique: skipped (Codex companion absent; `availability: auto`).

## Files Changed

**Production (7 files)**:
- `backend/engine/schemas.py` — added `CriticVerdict` Pydantic model
- `backend/engine/state.py` — added `critic_result: dict | None`, `critic_feedback: dict | None`
- `backend/engine/critic_node.py` — **new**; async `critic_node()` + `route_after_critic()` + `_broadcast_critic_mismatch()` + `_SYNTHETIC_PASS` constant
- `backend/engine/graph.py` — registered critic node + conditional edges in both `build_graph()` and `build_supervisor_graph()`
- `backend/engine/ac_parser.py` — accept `critic_feedback: dict | None` param; append HumanMessage 2nd turn when non-None
- `backend/engine/reporter.py` — added `_render_critic_pass_section()`; wired into `reporter_node`; `run_metrics.critic_verdicts` field
- `backend/config.py` — `settings.critic_enabled` (default True), `settings.max_critic_retries` (default 2)

**Tests (1 file, 27 new tests)**:
- `tests/engine/test_critic_node.py` — **new**; classes: `TestCriticVerdictSchema`, `TestRouteAfterCritic`, `TestCriticNode`, `TestGraphTopology`, `TestCriticPassReporter`, `TestCriticMismatchBroadcast`; `_make_state()` factory

**Memory Bank (4 files)**:
- `memory-bank/tasks/critic-pass-llm-evaluator.md` — status transitions through plan → creative → build → reflect → COMPLETE
- `memory-bank/creative/critic-pass-llm-evaluator-architecture.md` — 4 decisions all HIGH confidence
- `memory-bank/reflection/critic-pass-llm-evaluator-reflection.md` — Good task quality, Highly Effective ecosystem
- `memory-bank/roadmap/critic-pass-llm-evaluator.md` — status → completed (this archive)

## Learning Consolidation

Additive-only. Three learnings extracted from the reflection document:

| Learning | Rule File | Action |
|---|---|---|
| `asyncio.get_event_loop().run_until_complete()` deprecated in Python 3.12; always use `@pytest.mark.asyncio` in test bodies | `testing-patterns.md` | APPEND (new bullet; `derived_from` += slug; `evidence_count` bumped; `last_validated` → 2026-07-30) |
| LOW-confidence creative questions require 3+ file:line evidence references before deciding; evidence-based refutation saves build time worth more than the evidence-gathering overhead | `phase-zero-checkpoint.md` | APPEND (new bullet; broadens file from L4-specific to general creative-validation) |
| `_render_*` functions that introduce new CSS class names must either reuse existing stylesheet classes or define new ones in the same commit; dangling references render silently unstyled in production | `reporter-html-coupling.md` | CREATE (new file; 1 bullet; targets `backend/engine/reporter.py` and similar reporter modules) |

No mutating changes (no merges, no retirements, no expirations, no prunes). PR carries the `banyan:learning-consolidation` label but no `REVIEW: mutating change` callout.

**Post-archive human action**: run `/bmb:rules-index` if desired to refresh `memory-bank/agent-rules-index.md`.

## Known Follow-ups (all non-blocking; captured in reflection)

| # | Finding | Files | Severity | Suggested Follow-on |
|---|---------|-------|----------|---------------------|
| 1 | `test_static_execution_engine_bypasses_critic` uses `asyncio.get_event_loop().run_until_complete()` — deprecated in Python 3.12 | `tests/engine/test_critic_node.py` | Minor | 5-min fix; Level 1 |
| 2 | `_render_critic_pass_section()` references CSS classes not defined in report stylesheet (renders unstyled) | `backend/engine/reporter.py`, report stylesheet | Minor | ~30-min fix; recommended before next stakeholder demo |
| 3 | `run_metrics["critic_verdicts"]` stores only final `critic_result` dict, not full per-cycle history | `backend/engine/reporter.py`, `backend/engine/critic_node.py` | Minor | ~1-hour fix; enables retry forensics |
| 4 | Bedrock cache-hit logging (validate Q2 cache-preservation design at runtime via `cache_read_input_tokens`) | `backend/engine/ac_parser.py` | Nice-to-have | Low effort; high signal |

## Linked Artifacts

- Task: `memory-bank/tasks/critic-pass-llm-evaluator.md`
- Creative: `memory-bank/creative/critic-pass-llm-evaluator-architecture.md`
- Reflection: `memory-bank/reflection/critic-pass-llm-evaluator-reflection.md`
- Roadmap feature: `memory-bank/roadmap/critic-pass-llm-evaluator.md`
- Parent roadmap umbrella: `memory-bank/roadmap/agentic-testing-sota-adoption-2026.md`

## Workflow Effectiveness

- **Overall Task Success**: Success
- **Overall Workflow Effectiveness**: Highly Effective
- **Deviations Recorded**: 0
- **Guardrail Misses**: 0
- **Systemic Gaps Flagged for Future Banyan Improvement**:
  1. Auto-build deviation tracking should widen to catch implicit scope reductions within an AC's implementation boundary (the `critic_verdicts` single-dict vs. list gap was not recorded).
  2. `.agent-logs/claude/by-task/<slug>/` directory not initialized at auto-build session start; blocks reflection's tool-utilization analysis.
  3. Creative critique fallback to Anthropic when Codex absent and any question is not HIGH confidence.
