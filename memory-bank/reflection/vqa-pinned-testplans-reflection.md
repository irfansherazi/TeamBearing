# Reflection: vqa-pinned-testplans - vQA Pinned TestPlans for Deterministic Fail→Pass

**Date**: 2026-08-18T18:30:00Z
**Task Complexity**: Level 3
**Total Phases**: 5
**Duration**: 2026-08-18T13:31 (scaffold) to 2026-08-18T15:30 (Phase 5 commit) — approximately 2 hours wall-clock

## Executive Summary

This task implemented Lock B for the `/vc:diagnose → /vc:testwrite → /vc:fix → /vc:testrun` pipeline: an explicit pinned-TestPlan primitive that makes a red→green transition a byte-identical replay rather than two independent LLM parses. The core mechanism — `POST /preview-steps` authors and persists a plan under an opaque `plan_id`; `POST /execute` with `plan_id` injects it verbatim, bypassing every LLM stage and every cache lookup — was delivered cleanly across five phases with 48 new tests, zero regressions against the 2,028-test baseline, and all commit guards passing on first attempt.

The task had an unusual shape for Level 3: it skipped the `/bmb:creative` phase entirely because a pre-existing source-of-truth plan doc (`docs/todo/pinned-plans-PR.md`) had already resolved the single material design decision (new on-disk primitive vs. repurposing the content-hash cache). Every acceptance criterion was met, including the strongest one — AC-INVARIANT-1, the `call_count == 0` assertion that proves the LLM stages are unreachable, not merely producing the same output. One structural drift (source doc pointed at `backend/api/app.py`, which does not exist; lifespan lives in `backend/main.py:139`) was identified during planning and wired correctly in Phase 4 without incident.

The build demonstrates that a well-specified external plan doc can substitute for a creative phase and give an implementation team higher confidence than a typical Level-3 architecture exploration session would yield, provided the spec is treated as the authoritative source for diffs — not just high-level intent.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement

**Status**: All Met

All 10 acceptance criteria were satisfied:

- **AC-VERIFY-1** (store round-trip): `pinned_plans.save` / `pinned_plans.load` round-trips byte-identical JSON; file exists at `storage/pinned_plans/<plan_id>.json`. Covered by 16 Phase-1 tests.
- **AC-VERIFY-2** (TTL expiry on read — lazy prune): `PinnedPlanExpired` raised and file deleted on read when `created_at` > TTL. Distinct from `PinnedPlanNotFound`. Covered in Phase-1 suite.
- **AC-VERIFY-3 + AC-INVARIANT-1** (`ac_parser_node` short-circuit, zero-LLM assertion): `_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` are literal assertions in `tests/test_ac_parser_short_circuit.py`. The invariant holds before cache lookup, before KB guidance fetch, before any LLM call. 8 Phase-3 tests.
- **AC-VERIFY-4** (`POST /preview-steps` persists and returns `plan_id`): Existing `GET /preview-steps?ticket_id=` continues unmodified; the new POST body variant is additive. 7 Phase-4 integration tests.
- **AC-VERIFY-5** (execute with valid `plan_id` injects state): `VQAState["pinned_plan"]` and `["pinned_plan_id"]` populated before `ac_parser_node` is reached. Phase-4 integration.
- **AC-VERIFY-6** (durability — process restart): Storage is on-disk JSON under `storage/pinned_plans/`. Startup prune call wired in `backend/main.py` lifespan on-startup block. Phase-5 additive contract tests verify non-interference with this path.
- **AC-ERROR-1** (404 on unknown `plan_id`): HTTP 404 with `{"detail": "pinned plan not found: <id>"}`. LLM never invoked. Phase-4.
- **AC-ERROR-2** (410 on expired `plan_id`): HTTP 410 Gone with `{"detail": "pinned plan expired: <id>"}`. File deleted. Phase-4.
- **AC-ERROR-3** (400 mutex — `plan_id` + `override_steps`): HTTP 400 validated before any plan resolution attempt. Phase-4.
- **OpenAPI contract** (out-of-band): `ExecuteRequest.plan_id`, `PreviewStepsRequest`, `PreviewStepsResponse.plan_id` verified present by Phase-5 `test_openapi_pinned_fields.py` (10 tests covering OA-1..4).

The only gap worth noting is that AC-VERIFY-6 (process-restart durability) is proven by structural argument (on-disk files + startup prune) rather than by a test that literally terminates and restarts the FastAPI process. This was a deliberate scoping decision from the source doc and is acceptable, but a future E2E smoke test that asserts `plan_id` survives a uvicorn bounce would close this entirely.

### Code Quality Assessment

**Overall Rating**: Good

- **Maintainability**: `backend/engine/pinned_plans.py` (234 lines) is a clean, self-contained module. Custom exceptions (`PinnedPlanNotFound`, `PinnedPlanExpired`) are distinct and machine-catchable — no string-matching needed at call sites. The module has no dependencies outside stdlib (`json`, `pathlib`, `uuid`, `time`) which will not drift or require pinning.
- **Architecture**: The short-circuit block in `ac_parser_node` is placed correctly — at the very top of the node, before any state read or function call. It is not interleaved with existing logic; it is a clean `if state["pinned_plan"]: ... return patch` guard. This placement means any future refactor of the LLM stages cannot accidentally bypass it.
- **Error Handling**: Errors are loud, HTTP-status-coded, and machine-readable. The mutex-400 fires during route-level validation before any I/O, which is the correct placement. The "never silent re-parse" invariant is enforced both at the route level (404/410 immediately returned) and at the engine level (short-circuit fires before LLM).
- **Testing**: The test files are thorough. `test_execute_plan_id.py` (490 lines) covers the integration path end-to-end. `test_pinned_plans.py` (328 lines) exhaustively covers store semantics including TTL edge cases. The `call_count == 0` assertion in `test_ac_parser_short_circuit.py` is the right kind of test — it checks mechanism, not just output. One style note: at 7 test files totaling 1,942 lines against 533 net new production lines (pinned_plans.py + ac_parser.py additions + routes.py additions + schema + state + main), the test-to-prod ratio is approximately 3.6:1. This is appropriate for a correctness-critical infrastructure primitive, but the OpenAPI test file (`test_openapi_pinned_fields.py`, 278 lines / 10 tests) verifies what amounts to schema presence — these tests could be combined into the existing schema tests or expressed more concisely.
- **Observability**: Structured `pinned_plans SET|HIT|MISS|PRUNED` INFO log calls are present in `pinned_plans.py`, consistent with `systemPatterns.md`'s state-driven reporting pattern.

### Technical Decisions

**Key Decisions:**

1. **New on-disk primitive vs. repurposing the content-hash cache** — The design decision to introduce `backend/engine/pinned_plans.py` as a separate module rather than modifying `backend/engine/ac_parse_cache.py` was made upstream in the source doc. This was correct: the content-hash cache is keyed on AC text and can evict/invalidate between runs; the pinned-plan store is keyed on an opaque UUID with explicit TTL and never silently evicts mid-chain. Conflating them would have required the cache to understand "pinned" vs "evictable" semantics — a leaky abstraction.

2. **Lifespan drift resolution — `backend/main.py` instead of `backend/api/app.py`** — The source doc referenced a `backend/api/app.py` that does not exist. The planning phase caught this and documented the correct target (`backend/main.py` lifespan at line ~139) in the task file. Phase 4 wired correctly to this location. This is a good example of source-doc-to-codebase structural drift being caught during planning rather than during implementation, which avoids a wasted Phase-4 RED cycle.

3. **`call_count == 0` over "same output" for the load-bearing invariant** — The spec was explicit that softening this assertion would undermine the guarantee. A "same output" test would pass even if the LLM happened to produce identical output on two calls (which `T=0` on Bedrock almost but not exactly guarantees). The `call_count == 0` assertion proves the LLM stages are unreachable by construction, which is a fundamentally stronger guarantee. This distinction is well understood by the implementation and the tests reflect it precisely.

4. **Additive-only schema extension (Phase 5)** — Phase 5 verified via `test_additive_contract.py` that callers omitting `plan_id` from `ExecuteRequest` continue to receive identical behavior, and callers of `GET /preview-steps?ticket_id=` are unaffected by the new POST handler. This is the right final gate for an NFR/infrastructure change — explicitly proving backward compatibility rather than assuming it.

**Trade-offs:**

- **On-disk file store vs. in-memory store**: Files survive process restart (the durability requirement) at the cost of disk I/O on each `save`/`load`. At the projected volume (~50 KB/file, ~10 files/day, 14-day TTL), the I/O cost is negligible. The correct trade-off.
- **TTL lazy prune vs. background sweeper**: Lazy prune (on `load`) plus startup prune is simpler and avoids background threads. The downside is that expired files accumulate between process restarts if `load` is never called on them. At vQA's expected usage volume, this is not a practical problem, but a periodic background sweeper would be cleaner at scale.
- **No `/vc` plugin changes in scope**: The plugin is expected to adopt `plan_id` out-of-band (the OpenAPI preflight check). This is appropriate for Lock B — the backend contract is stable and complete; plugin adoption is a separate task.

### What Went Well

1. **Zero regressions across all 5 phases**: The pre-existing failure baseline of 77 tests was tracked explicitly and remained unchanged from Phase 1 through Phase 5 (the Phase 2 count of 79 briefly diverged, then returned to 77 in Phase 3 when 2 pre-existing failures were coincidentally fixed by the Phase-3 imports — net: no regressions introduced). This confirms the additive-only property held throughout.

2. **Structural drift caught at planning time, not at build time**: The `backend/api/app.py` → `backend/main.py:139` drift was identified during the Spec Writer's codebase analysis and documented in the task file's DRIFT NOTE before any implementation began. Phase 4 required no debugging time on this issue.

3. **RED→GREEN discipline on every phase**: Each TDD agent started with confirmed RED (Phase 1: 16 failing; Phase 2: ImportError + 24 failing; Phase 3: 6/8 failing; Phase 4: 6/7 failing; Phase 5: all GREEN immediately — appropriate for a contract-verification phase). The one-GREEN-from-the-start in Phase 4 (the unknown-plan-id 404 test) was already passing because prior phases had wired the not-found case; this is expected in layered implementation.

4. **AC-INVARIANT-1 asserted with the correct mechanism**: The load-bearing zero-LLM assertion using `mock.call_count` is the strongest possible test for the short-circuit guarantee. It is present, specific, and cannot be accidentally softened without failing the test.

5. **5-phase decomposition matched the architecture naturally**: Phase 1 (data layer), Phase 2 (type layer), Phase 3 (engine layer), Phase 4 (API layer), Phase 5 (contract verification) followed the dependency graph cleanly. No phase had to reach across layer boundaries or depend on incomplete adjacent work.

### Challenges Encountered

1. **Phase 2 test count overshoot from source doc**: The source doc estimated "~8-10 tests across two new test files." Phase 2 alone delivered 24 tests (15 schema + 9 state), and the overall count landed at 48 new tests across 7 test files. This is not a problem — more specific tests are better for an invariant-heavy NFR change — but the task file's test-count estimate should be read as a lower bound for infrastructure tasks where each field and state transition warrants an explicit test.

2. **Phase 2 started with ImportError RED**: `PreviewStepsRequest` did not exist in schemas before Phase 2 implemented it. The test harness importing the new symbol failed before running any assertions. This is the cleanest possible RED for a schema extension — it proves the test was written against the intended API, not against a stub.

3. **Source doc not committed to the feature branch**: The plan doc (`docs/todo/pinned-plans-PR.md`) was referenced in the task file as the source of truth but was not present in the feature branch worktree (confirmed: `docs/todo/` directory does not exist under the feature branch at worktree root). This means reflection tooling must read it from main or another branch, which adds friction. The source doc should either be committed to the feature branch at planning time or absorbed entirely into the task file.

### Technical Debt & Future Work

- **Process-restart durability smoke test**: A test that verifies `plan_id` survives a uvicorn process restart would complete AC-VERIFY-6 with mechanical proof rather than structural argument. Low urgency given the simple on-disk design, but worth adding before vQA operates in auto-scaling environments.
- **Background TTL sweeper**: The startup-prune + lazy-prune model works, but if the process runs continuously for weeks without touching expired plans, disk usage could accumulate. A low-frequency background asyncio task (e.g., every 6 hours) would be cleaner than relying solely on startup and read-time prune.
- **`/vc` plugin adoption of `plan_id`**: Lock B's backend is complete, but the `/vc:testwrite → /vc:testrun` chain does not yet pass `plan_id`. This is a separate, out-of-scope task that should be scheduled immediately as the next step in the Lock B initiative.
- **`execute-batch` scoping**: `POST /execute-batch` was explicitly out of scope. Pinned plans for batch runs should be considered when the batch endpoint matures.

---

## Dimension 2: Claude Code Ecosystem Effectiveness

### Build Session Analysis

**Build Sessions**: 5 (one per phase — each /bmb:build invocation handled exactly one phase)
**Sub-Agents Spawned**: 5 TDD agents (one per phase) + 5 code-review passes (one per phase)
**Total Tool Calls**: Not available — task-scoped agent logs are missing (see note below)
**Errors Recovered**: 0 (all commit guards passed on first attempt; no re-invocations)

**Session Log Availability**: The `.agent-logs/claude/by-task/vqa-pinned-testplans/` directory does not exist in this worktree. The `.agent-logs/claude/` directory contains date-directory entries from prior tasks but uses the legacy `TASK-XXX` naming. This task uses the v2 slug-based identity (`vqa-pinned-testplans`), which has no corresponding by-task index. Precise per-tool call counts are therefore unavailable. **Recommendation**: Run `/bmb:init` to upgrade the project's log indexing to v2 task-slug-based indexing so future reflections can extract precise session metrics.

#### Tool Utilization (estimated from phase structure)

| Tool | Est. Count | Notes |
|------|-----------|-------|
| Read | High | Codebase exploration during each TDD agent dispatch — `ac_parser.py` (1928 lines), `routes.py` (4724 lines), `schemas.py` (1737 lines) require extensive reading before targeted extension |
| Edit | Moderate | 6 production files extended (targeted inserts, not rewrites) |
| Write | Moderate | 7 new test files + `pinned_plans.py` (new) |
| Bash | High | pytest runs per phase, lint checks, git operations |
| Task | 5 | One TDD sub-agent dispatched per phase |

#### Sub-Agent Performance

| Agent Type | Invocations | Model | Effectiveness |
|------------|-------------|-------|---------------|
| TDD Agent (P1) | 1 | Sonnet | High — 16 RED→GREEN, clean new module |
| TDD Agent (P2) | 1 | Sonnet | High — ImportError RED correctly confirmed |
| TDD Agent (P3) | 1 | Sonnet | High — `call_count == 0` assertion written correctly |
| TDD Agent (P4) | 1 | Sonnet | High — 6/7 RED correctly (1 already passing from prior phases) |
| TDD Agent (P5) | 1 | Sonnet | High — contract verification, all GREEN immediately (correct for this phase type) |
| Code Review | 5 | Sonnet | All APPROVED on first pass — no blocking issues across any phase |

### Creative Phase Evaluation (Level-3 Required Section)

**Decision**: Creative phase explicitly waived. The Spec Writer agent confirmed HIGH confidence in the spec and set `Creative Exploration Needed: No`.

**Was this the right call?** Yes, and it reveals an important workflow pattern.

The creative phase exists to resolve ambiguous design decisions before implementation — specifically, forks where two or more architecturally distinct approaches have different downstream implications that are hard to reverse. For this task, the single material design fork (pinned-plan primitive vs. repurposed content-hash cache) was already resolved in the source doc with explicit justification. The source doc went further: it provided verbatim proposed diffs, exact file targets, and concrete test case names. This is more resolution than a `/bmb:creative` session typically produces.

**What the creative phase would have cost vs. gained**: A creative session would have re-examined the primitive-vs-cache decision and likely arrived at the same answer, adding ~30 minutes of elapsed time and a creative doc of ~200 lines that would largely restate the source doc's reasoning. The gain would have been near zero for this specific task.

**What this reveals about the workflow shape**: A Level-3 classification is correct for this task — the implementation surface is substantial (6 files extended, 1 new module, 7 test files, 48 tests), and the behavioral invariant is complex enough that a simple bug fix or Level-2 enhancement couldn't handle it. But the creative phase's value is proportional to *design ambiguity at the time of planning*, not to implementation complexity. When a pre-existing external document has already done the design work at high fidelity, the workflow should accommodate a "design-resolved-by-external-artifact" fast-path without treating skipping creative as a warning signal.

**Concrete suggestion**: The BMB workflow could add a task-file frontmatter field `creative_waived_reason: external-plan-doc` (alongside the existing `[x] Not required`) so that reflection agents and archive agents can distinguish "creative was skipped because this was actually Level 2" from "creative was skipped because a higher-fidelity external artifact already did the work." The distinction matters for calibrating complexity estimates on future similar tasks.

**Did anything go wrong because creative was skipped?** No. The structural drift (`app.py` → `main.py`) was caught at planning time by the Spec Writer's codebase verification pass, which is specifically designed to catch this kind of source-doc-vs-codebase divergence. No implementation phase required re-architecture. The absence of a creative doc did not create any ambiguity that had to be resolved mid-build.

### Command Workflow Evaluation

**Commands Used**:
- `/bmb:plan` (1x) — planning + Spec Writer agent
- `/bmb:build` (5x) — one per phase
- `/bmb:reflect` (1x, this invocation)

**Workflow Efficiency**: Highly Effective

The 5-phase decomposition was the right granularity for this task. Each phase had a single-layer focus (data, types, engine, API, contract) and a clean test boundary. Phases were not so large that a mid-phase failure would have wasted significant work, and not so small that commit overhead became burdensome.

The decision to make Phase 5 a test-only verification phase rather than folding contract tests into Phase 4 was correct: Phase 4 was already substantial (routes wiring + startup prune + 7 integration tests), and the additive-contract and OpenAPI tests serve a different audience (they are the evidence that the implementation didn't break any existing callers). Separating them keeps Phase 4 focused on the new behavior and Phase 5 focused on non-regression.

One minor friction point: the task file's commit message for Phase 4 reads `"Phase 4: Routes wiring for pinned TestPlan (Lock B)"` — note no `feat(vqa-pinned-testplans):` prefix, unlike Phases 1, 2, and 5. This is a minor inconsistency with the repo's commit message style. Not a blocker, but the build agent should follow the repo's established `feat(<slug>):` / `fix(<slug>):` prefix pattern consistently across all phases.

### Context File Effectiveness

**Files Loaded**: task file, productBrief.md (for persona/NFR context during planning), techContext.md, systemPatterns.md, agent-rules index (30 rules: 1 human-authored, 29 learned)

**Assessment**:

- **Helpful**: The task file's Specification section was the primary guidance for all five phases. The DRIFT NOTE embedded during planning prevented a Phase-4 wasted cycle. The agent-rules index loaded `backend-api-patterns.md` (high priority) and `error-handling.md` (high priority) for the routes-relevant phases — both are directly applicable (the `subprocess-concurrency-gate` and `pid-tracking-cleanup` rules are route-adjacent; `error-handling` rules around `routes.py` exception handling patterns are relevant to the 404/410/400 contracts).

- **Gaps**: The source-of-truth plan doc (`docs/todo/pinned-plans-PR.md`) was referenced in the task file but was not committed to the feature branch and was not accessible from the worktree. Sub-agents that needed to reference the verbatim diffs would have had to rely on the task file's distillation of that doc. For future tasks that reference an external plan doc as authoritative, the doc should be committed to the feature branch at planning time (even as a read-only copy) so all sub-agents can access it without special branch-reading logic.

- **Redundancy**: None observed. The 30-rule index is large (an estimated 1,100 lines if fully loaded) but contextual loading by file pattern prevents loading all rules at once.

### Memory Bank Organization

**Assessment**:

- **Structure**: The taxonomy worked correctly. Work-Specific files (task doc, reflection doc) ride the feature branch; Core State (roadmap feature file) is on `chore/banyan-admin` via PR #85. The collapsed pr_target == metadata_branch means there is no split-PR complexity here.
- **Navigation**: The task file was the single source of truth for phase state and resumption notes throughout all 5 build invocations. The Execution State section was updated after each phase commit. This worked well — there was never ambiguity about what had been completed.
- **Completeness**: The missing `docs/todo/pinned-plans-PR.md` in the worktree is the one structural gap. See Context File Effectiveness above.

### Memory-Bank Corrections (from Guardrail Misses)

None — no guardrail misses this build.

All 5 phases passed the commit guard on first attempt:
- Phase 1: prod=2, test=1 — PASS
- Phase 2: prod=2, test=2 — PASS
- Phase 3: prod=1, test=1 — PASS
- Phase 4: prod=2, test=1 — PASS
- Phase 5: prod=0, test=2 — PASS (C2 not triggered; test-only phase)

No re-invocations. No recovery ladder steps taken.

### Suggested Improvements to Claude Code System

**High Priority**:

1. **Task-scoped agent log indexing for v2 slug-based tasks**: The `.agent-logs/claude/by-task/<slug>/` directory was not created for this task. Reflection agents cannot extract precise tool call counts, error recovery sequences, or session durations without this index. The by-task directory should be created at `/bmb:build` dispatch time (Phase 1, Step 0.5 — worktree creation) so all subsequent build sessions log to it automatically. This affects every v2 task reflection.

2. **`creative_waived_reason` field in task file frontmatter**: When `/bmb:plan` waives the creative phase, record the reason in frontmatter (`creative_waived_reason: external-plan-doc | low-ambiguity | level-2-scope | other`). This allows reflection agents to distinguish productive skips (external artifact did the design work) from under-investment skips (creative waived when it should have run). It also allows future calibration of which task shapes reliably produce waive-worthy confidence scores.

3. **External plan doc attachment at planning time**: When the Spec Writer references an external plan document as the source of truth, `/bmb:plan` should offer to copy or symlink that document into `memory-bank/tasks/<slug>-source-plan.md` (or similar) so it is accessible on the feature branch. The current gap where `docs/todo/pinned-plans-PR.md` is referenced but not accessible from the worktree is low-friction in practice but would be disqualifying if the source doc were on a private external URL.

**Medium Priority**:

4. **Commit message prefix enforcement**: The Phase 4 commit (`"Phase 4: Routes wiring..."`) lacks the `feat(vqa-pinned-testplans):` prefix used by Phases 1, 2, and 5. The build agent's commit-message template should enforce the `<type>(<slug>):` prefix pattern for all phase commits, not just some. A simple `commitlint`-style check in the commit guard would catch this.

5. **Explicit "contract-verification" phase type in task templates**: Phase 5 was a test-only phase specifically to verify the additive contract. This is a legitimate and valuable phase type for NFR/infrastructure tasks. The task file template or phase guide could call out "contract verification" as a named phase type (alongside TDD phases) so future task planners can include it explicitly without it appearing as scope creep at Phase-5 time.

6. **Baseline failure count tracked in task file**: The pre-existing failure count (77 tests) was tracked in the task file's Execution State for each phase. This should be a first-class field in the task file's test summary section (e.g., `baseline_failing_tests: 77` in frontmatter) rather than a prose note in each phase's step log. This would make it machine-readable and allow the commit guard to enforce "no new failures introduced" as a hard check.

**Low Priority / Nice to Have**:

7. **Phase commit-count summary in reflection dispatch context**: The reflection agent was given the phase summaries in the dispatch prompt, which is helpful. For larger tasks (Level 4, 7-10 phases), a machine-readable summary from the Execution State would be more reliable than prose reconstruction. A structured `phases_summary` block in the task file frontmatter (generated by each `/bmb:build` completion) would give reflection agents reliable data without requiring log file access.

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

- **testing-patterns** (`tests/test_*.py`, infrastructure invariants): For correctness-critical pipeline primitives (determinism guarantees, idempotency contracts, "never-silent-fallback" invariants), assert mechanism — `mock.call_count == 0` — not just output. An output-equality test passes when an LLM produces identical results twice; a call_count test proves the code path was never reached. The distinction is the difference between "probably deterministic" and "provably deterministic."

- **planning-patterns** (`memory-bank/tasks/*.md`, Level 3 creative-waive decisions): When a pre-existing external plan document provides verbatim diffs, exact file targets, and concrete test case names with HIGH spec confidence, record `creative_waived_reason: external-plan-doc` and proceed to build. This is a legitimate Level-3 fast-path, not under-investment. The Spec Writer's codebase verification pass (catching source-doc-to-repo structural drift at planning time) provides the same safety net that creative exploration would have provided.

- **drift-handling** (`memory-bank/tasks/*.md`, Spec Writer DRIFT NOTEs): When a source document references a file path that does not exist in the codebase (`backend/api/app.py`), document the correct target in a `DRIFT NOTE` in the task file at planning time. This converts a potential Phase-N debugging session into a one-line implementation note. Structural drift caught at planning time is free; caught at build time it costs a full RED cycle.

### Learned Rules Applied

The following rules from `memory-bank/agent-rules/_learned/` were relevant to this task:

- **backend-api-patterns.md** (`high` priority, matched on `backend/api/routes.py`): The `pid-tracking-cleanup` and `subprocess-concurrency-gate` rules are adjacently applicable (the lifespan startup prune pattern mirrors the shutdown cleanup pattern established there). The rule about FastAPI lifespan handlers reinforced the Phase-4 implementation decision to use the existing lifespan block rather than creating a new startup event. Loaded and applicable.

- **error-handling.md** (`high` priority, matched on `backend/api/routes.py`): The rules around HTTP status codes and machine-readable error bodies (`{"detail": "..."}`) were directly applicable to the 404/410/400 contract. The existing rule `"error_msg.lower() string matching over isinstance() on framework-internal error classes"` informed the exception handling style in the route handler. Loaded and applicable.

- **evaluator-routing.md** (`high` priority, matched on `backend/engine/state.py`): The pattern of adding new state fields with defaults in `make_initial_state()` rather than as optional parameters elsewhere was directly applicable to the Phase-2 `pinned_plan` / `pinned_plan_id` additions to `VQAState`. Loaded and applicable.

- **memory-bank-syncing.md** (`high` priority): Applicable — task file was updated with Execution State after each phase commit, consistent with the learned rule about keeping the task file as the ground truth for in-flight state. Loaded and applicable.

### For Claude Code Workflow

1. **External plan docs as creative substitutes** — When a task has an authoritative external plan document with concrete diffs and test case names, the `/bmb:plan` Spec Writer should surface a "creative-waived, reason: external-plan-doc" determination and proceed. The current workflow handles this correctly (Spec Writer sets confidence HIGH and marks creative as not required), but there is no structured reason field to distinguish this case from a low-complexity creative waive.

2. **Baseline-failure tracking as a first-class build metric** — Tracking the pre-existing failure count per phase was one of the most useful safety signals in this build. It would be valuable to make this machine-readable in the task file (not just prose in the Execution State) so future build phases can assert "count unchanged" as a commit-guard condition.

3. **Phase-type taxonomy** — The workflow would benefit from naming a "contract verification" phase type. Phase 5 of this task was pure test-verification with no production code changes. This is a distinct, valuable phase type for infrastructure tasks and should not look like a surprise or scope extension when encountered.

---

## Conclusion

This task delivered a clean, well-tested implementation of Lock B for the `/vc` pipeline's red→green determinism guarantee. All 10 acceptance criteria were met. The zero-LLM invariant (`call_count == 0`) is asserted mechanically. The additive-only contract was explicitly verified. No regressions were introduced across 5 phases and a 2,105-test suite run. Every commit guard passed on first attempt — a clean build by every metric.

The workflow shape — Level-3 complexity with creative phase legitimately waived due to a high-fidelity external plan document — reveals a productive pattern that the BMB system handles correctly but does not yet distinguish structurally from other creative waives. The two most actionable workflow improvements surfaced by this reflection are: task-scoped agent log indexing for v2 slugs (currently missing, breaking reflection metrics), and a `creative_waived_reason` field to distinguish design-resolved-by-external-artifact from under-investment skips.

The 5-phase decomposition was well-matched to the layered architecture (data, types, engine, API, contract), and the RED→GREEN discipline was maintained throughout. The structural drift in the source doc (`app.py` → `main.py`) was caught at planning time, not build time, which is the intended behavior of the Spec Writer's codebase verification pass.

**Overall Task Success**: Success

**Overall Workflow Effectiveness**: Highly Effective

**Recommendation**: Ready to archive. The only pre-archive action worth considering is committing the source plan doc (`docs/todo/pinned-plans-PR.md`) to the feature branch if it exists elsewhere in the repo — it is referenced in the task file but not accessible from the worktree, which would make future archaeology harder.
