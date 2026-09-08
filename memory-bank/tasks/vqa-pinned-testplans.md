---
slug: vqa-pinned-testplans
feature: vqa-pinned-testplans
status: COMPLETE
---

# vqa-pinned-testplans: vQA Pinned TestPlans for Deterministic Fail→Pass

**Complexity**: Level 3
**Status**: COMPLETE
**Archived**: memory-bank/archive/vqa-pinned-testplans-archive.md
**Completed**: 2026-08-18
**Reflection**: memory-bank/reflection/vqa-pinned-testplans-reflection.md
**Roadmap**: vqa-pinned-testplans
**Branch**: feature/vqa-pinned-testplans
**Worktree**: ~/banyan-wt/vQA/feature-vqa-pinned-testplans/

## Task Description

Add an explicit **pinned TestPlan** primitive to vQA so the `/vc` pipeline's red→green transition is a byte-identical replay, not two independent LLM parses. This is **Lock B** for the `/vc:diagnose → /vc:testwrite → /vc:fix → /vc:testrun` chain.

The source-of-truth plan doc lives at [`docs/todo/pinned-plans-PR.md`](../../docs/todo/pinned-plans-PR.md) — it carries the verbatim diffs, tests, and implementer notes. That doc explicitly says *"Do not implement from the plugin session."* This task file exists to schedule the work into vQA's own `/bmb:plan` + `/bmb:build` cycle; the Specification section below distills the plan doc into BMB shape for review.

### Motivation (from source doc)

The current pipeline authors a `TestPlan` from Jira AC via multiple LLM stages at `temperature=0.0`. `T=0` on Bedrock is not bit-exact deterministic, and the content-hash disk cache that would otherwise pin the parse can evict/invalidate between the red run (`two-test.vcreative.net`) and the green run (`test.vcreative.net`) hours or days later. Without pinning, "the test failed then passed" is not a proof — the plan itself could have shifted between runs.

### Mechanism (additive only)

1. `POST /preview-steps` accepts inline `acceptance_criteria`, authors the TestPlan from that text, persists it under an opaque `plan_id`, returns the id.
2. `POST /execute` accepts `plan_id`; when present, `ac_parser_node` short-circuits at the top and injects the pinned plan **verbatim** — no LLM, no cache, no re-parse.
3. Missing / expired `plan_id` errors loudly (404 / 410). **Never** silent fallback to re-parse.

### File touch list (from source doc)

- NEW `backend/engine/pinned_plans.py` — TTL-scoped on-disk store.
- `backend/config/__init__.py` — new `pinned_plan_ttl_days` setting.
- `backend/api/schemas.py` — `ExecuteRequest.plan_id`, new `PreviewStepsRequest` (POST variant), `PreviewStepsResponse.plan_id`.
- `backend/engine/state.py` — `pinned_plan` + `pinned_plan_id` state fields.
- `backend/engine/ac_parser.py` — short-circuit at top of `ac_parser_node`.
- `backend/api/routes.py` — new `POST /preview-steps` handler; `execute_single` resolves `plan_id`.
- `backend/api/app.py` — startup hook calls `pinned_plans.prune_expired()`. **DRIFT NOTE:** the app has no `backend/api/app.py`; the lifespan handler lives in `backend/main.py` (`@asynccontextmanager async def lifespan(app: FastAPI)` at line ~139). Phase 4 must call `pinned_plans.prune_expired()` from that lifespan block, not from a non-existent `app.py`.
- NEW `tests/test_pinned_plans.py` — store unit tests.
- NEW `tests/test_execute_plan_id.py` — integration; **load-bearing assertion**: `_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` when `state["pinned_plan"]` is set. Covers 404 / 410 / mutex-400.

## Specification

**Feature Type**: NFR/Infrastructure
*Note: This is an internal-pipeline determinism guarantee (Lock B) — no end-user UI, but a hard behavioral invariant on the `POST /preview-steps` → `POST /execute` API contract that the `/vc:testwrite → /vc:testrun` chain depends on.*

**Primary Persona**: QA Lead / Automation Engineer (per `productBrief.md`), specifically when driving the `/vc` slash-command pipeline. Secondary: Release Engineer / DevOps who consumes the red→green transition as CI/CD deploy proof. The persona interacts through the `/vc` plugin, not through the vQA React dashboard.

**Creative Exploration Needed**: **No.** The source-of-truth plan doc has already resolved the single design decision (introduce a new pinned-plan primitive rather than trying to re-use the content-hash disk cache in `backend/engine/ac_parse_cache.py`). The proposed diffs and test files are concrete. No creative phase is required.

### Verification Method

- **Test method**:
  - `pytest tests/test_pinned_plans.py tests/test_execute_plan_id.py -v`
  - Plus a one-time out-of-band check on merge: regenerate `openapi.json` and confirm `ExecuteRequest.plan_id`, `PreviewStepsRequest`, and `PreviewStepsResponse.plan_id` are present. (`/vc` plugin preflights `/openapi.json` to detect support.)
- **Success metrics**:
  - `_stage_1_normalize.call_count == 0` and `_stage_2_compile.call_count == 0` on the `ac_parser_node` call where `state["pinned_plan"]` is set. This is the **load-bearing** invariant — strictly stronger than "same output on two runs."
  - `POST /execute` with an unknown `plan_id` returns HTTP **404** with a machine-readable error body; the LLM parser is NEVER invoked as a fallback.
  - `POST /execute` with an expired `plan_id` (older than `pinned_plan_ttl_days`, default 14) returns HTTP **410**; the LLM parser is NEVER invoked as a fallback.
  - `POST /execute` carrying BOTH `plan_id` and `override_steps` returns HTTP **400** (mutex — the caller must choose one input path).
  - `POST /preview-steps` (POST variant) with inline `acceptance_criteria` in the body persists a pinned plan file at `storage/pinned_plans/<plan_id>.json` and returns the opaque `plan_id` in `PreviewStepsResponse`.
  - Pinned plans survive process restart: the store is on-disk (JSON files under `storage/pinned_plans/`), not in-memory. Startup prune (`pinned_plans.prune_expired()` called from `backend/main.py`'s lifespan on-startup block) removes entries older than TTL and logs the count.
- **Observable at**:
  - pytest terminal output (assertions above).
  - `storage/pinned_plans/<plan_id>.json` file inspection (JSON with `plan_id`, `created_at`, `test_plan`, `acceptance_criteria` fields).
  - Structured INFO logs from the `backend.engine.pinned_plans` module: `pinned_plans SET <plan_id>`, `pinned_plans HIT <plan_id>`, `pinned_plans MISS <plan_id> reason=<not_found|expired>`, `pinned_plans PRUNED count=<N>`.
  - `/openapi.json` on the running server — the three new fields must be present after merge (checked out-of-band by `/vc:testrun` preflight).
- **Verification frequency**:
  - On every `pytest` run during Phase 1–4 build.
  - On every merge to `main` (OpenAPI regeneration + `/vc` plugin preflight).
  - Continuously in production: the `/vc:testwrite → /vc:testrun` chain fails loudly if the invariants regress (unknown plan_id → 404, not silent re-parse).

### Acceptance Criteria

#### AC-VERIFY-1: Pinned-plan store round-trips a TestPlan by opaque plan_id
**Priority**: MUST
**Given** a caller invokes `pinned_plans.save(test_plan, acceptance_criteria)`
**When** the caller later invokes `pinned_plans.load(plan_id)` with the returned opaque id
**Then** the loaded object is byte-identical to the saved `test_plan` (same JSON serialization), AND a file exists on disk at `storage/pinned_plans/<plan_id>.json`

#### AC-VERIFY-2: TTL-based expiry is enforced on read (lazy prune)
**Priority**: MUST
**Given** a pinned plan exists at `storage/pinned_plans/<plan_id>.json` with a `created_at` older than `settings.pinned_plan_ttl_days` (default 14)
**When** any code path calls `pinned_plans.load(plan_id)`
**Then** the call raises `PinnedPlanExpired` (custom exception distinct from `PinnedPlanNotFound`), AND the expired file is deleted from disk

#### AC-VERIFY-3: `ac_parser_node` short-circuits when `state["pinned_plan"]` is set
**Priority**: MUST
**Given** a `VQAState` where `state["pinned_plan"]` is a non-None TestPlan dict
**When** `ac_parser_node(state)` is invoked
**Then** the node returns a patch whose `test_plan` is the injected `pinned_plan` verbatim, AND `_stage_1_normalize` is called ZERO times, AND `_stage_2_compile` is called ZERO times, AND the content-hash disk cache (`backend.engine.ac_parse_cache`) is NOT consulted. This is the load-bearing invariant.

#### AC-VERIFY-4: `POST /preview-steps` with inline AC persists a pinned plan and returns its id
**Priority**: MUST
**Given** the server is running and receives `POST /preview-steps` with a body containing `acceptance_criteria: "<text>"` (new `PreviewStepsRequest` schema)
**When** the request completes successfully (HTTP 200)
**Then** the response body is a `PreviewStepsResponse` whose `plan_id` field is a non-empty opaque string, AND a file exists at `storage/pinned_plans/<plan_id>.json` whose contents match the returned `steps`, AND the existing `GET /preview-steps?ticket_id=...` path continues to work identically for callers who don't pass a body

#### AC-VERIFY-5: `POST /execute` with a valid `plan_id` executes the pinned plan verbatim
**Priority**: MUST
**Given** a pinned plan authored via `POST /preview-steps` is available at `storage/pinned_plans/<plan_id>.json`
**When** `POST /execute` is called with `{jira_ticket_id, role, plan_id: "<id>"}` (no `override_steps`)
**Then** the run's initial `VQAState` has `state["pinned_plan"]` and `state["pinned_plan_id"]` populated, AND `ac_parser_node` short-circuits (see AC-VERIFY-3), AND the run proceeds to the setup_role / login / executor path with the pinned steps

#### AC-VERIFY-6: Pinned plans survive process restart (durability)
**Priority**: MUST
**Given** a pinned plan file exists at `storage/pinned_plans/<plan_id>.json` before restart
**When** the FastAPI process is terminated and restarted (lifespan startup runs, including `pinned_plans.prune_expired()`)
**Then** if the file's `created_at` is within TTL, it remains on disk and is loadable via `pinned_plans.load(plan_id)`; if it is beyond TTL, it is removed and the startup log records `pinned_plans PRUNED count=<N>`

#### AC-ERROR-1: Unknown `plan_id` returns HTTP 404 — never silent re-parse
**Priority**: MUST
**Given** the caller invokes `POST /execute` with `plan_id: "<id-that-does-not-exist>"`
**When** the route handler attempts to load the pinned plan
**Then** the response is HTTP **404** with a machine-readable error body (`{"detail": "pinned plan not found: <id>"}`), AND `_stage_1_normalize` is called ZERO times, AND `_stage_2_compile` is called ZERO times, AND no fallback re-parse path is invoked. Determinism guarantee: a missing pin is a loud failure, never a silent regeneration.

#### AC-ERROR-2: Expired `plan_id` returns HTTP 410 — never silent re-parse
**Priority**: MUST
**Given** a pinned plan file exists but its `created_at` is older than `settings.pinned_plan_ttl_days`
**When** `POST /execute` is called with that `plan_id`
**Then** the response is HTTP **410** Gone with a machine-readable error body (`{"detail": "pinned plan expired: <id>"}`), AND the expired file is deleted from disk (lazy prune), AND `_stage_1_normalize` / `_stage_2_compile` are called ZERO times

#### AC-ERROR-3: Passing both `plan_id` and `override_steps` returns HTTP 400 (mutex)
**Priority**: MUST
**Given** the caller invokes `POST /execute` with a body containing BOTH `plan_id: "<id>"` AND `override_steps: [...]`
**When** the request is validated
**Then** the response is HTTP **400** with a machine-readable error body identifying the conflict (`{"detail": "plan_id and override_steps are mutually exclusive"}`), AND no run is started, AND no LLM call is issued. The two mechanisms serve different intents and must not silently interact.

#### AC-INVARIANT-1: Load-bearing zero-LLM assertion when pinned plan is present
**Priority**: MUST
**Given** a `VQAState` is constructed with `state["pinned_plan"] = <TestPlan dict>`
**When** the LangGraph executes the `ac_parser_node`
**Then** `_stage_1_normalize.call_count == 0` AND `_stage_2_compile.call_count == 0` at the moment control leaves `ac_parser_node`. This assertion appears literally in `tests/test_execute_plan_id.py` and is the singular, machine-checkable invariant that makes red→green a byte-identical replay rather than two independent LLM parses. **Never soften this assertion to "counts stay unchanged from previous call" or similar — the pinned-plan path must not touch the LLM stages at all.**

### Scope Boundaries

- **In scope**:
  - New `backend/engine/pinned_plans.py` module implementing `save`, `load`, `prune_expired`, plus `PinnedPlanNotFound` and `PinnedPlanExpired` custom exceptions.
  - Adding `pinned_plan_ttl_days: int = 14` to `Settings` in `backend/config/__init__.py`.
  - Adding `plan_id: str | None` to `ExecuteRequest` and `plan_id: str | None` to `PreviewStepsResponse` in `backend/api/schemas.py`, plus a new `PreviewStepsRequest` model for the POST variant carrying inline `acceptance_criteria`.
  - Adding `pinned_plan: dict | None` and `pinned_plan_id: str | None` fields to `VQAState` in `backend/engine/state.py`, with defaults in `make_initial_state()` (currently at `backend/engine/state.py:1462`).
  - A short-circuit block at the very top of `ac_parser_node` in `backend/engine/ac_parser.py` that returns the pinned plan verbatim when `state["pinned_plan"]` is set — BEFORE any cache lookup, BEFORE any LLM call, BEFORE any KB guidance fetch.
  - New `POST /preview-steps` handler in `backend/api/routes.py` that authors a pinned plan from inline `acceptance_criteria` and returns the id. The existing `GET /preview-steps?ticket_id=` must continue to work identically.
  - Wiring in `execute_single` (`backend/api/routes.py:1362`) to resolve `plan_id` from the request, load the pinned plan, inject it into `state["pinned_plan"]` / `state["pinned_plan_id"]`, and enforce the 404 / 410 / 400 error contracts.
  - Startup prune call in the lifespan on-startup block of `backend/main.py` (see DRIFT NOTE above — the source doc says `backend/api/app.py`, which does not exist in this repo).
  - Two new test files: `tests/test_pinned_plans.py` (store unit tests) and `tests/test_execute_plan_id.py` (integration + load-bearing assertion).
- **Out of scope**:
  - Any change to the LLM stages (`_stage_1_normalize`, `_stage_2_compile`) themselves — they remain exactly as-is.
  - Any change to the existing `backend/engine/ac_parse_cache.py` content-hash disk cache — pinned plans are a NEW, orthogonal mechanism.
  - Any change to the React frontend — the `/vc` plugin is the sole client of this contract.
  - Retroactively pinning historical runs — only new preview→execute chains that opt in by passing `plan_id` are pinned.
  - Cross-container replication or shared-storage backends — a single container / mounted volume is sufficient (see NFR below).
  - Any change to `POST /execute-batch` — batch runs are out of scope for Lock B.
- **Dependencies**:
  - Storage volume: `storage/pinned_plans/` must be on a **persistent** filesystem (not container-ephemeral). If the vQA deploy is stateless-container, this requires a volume mount — call out during Phase 1 review.
  - No new external services, no new AWS resources, no new IAM changes.
  - No new Python packages — uses stdlib `json`, `time`, `pathlib`, `uuid`.
- **NFR implications**:
  - **Reliability**: strengthens the red→green determinism guarantee (Lock B) that the `/vc` pipeline depends on. Aligns with the `productBrief.md` guiding principle of "auditable regression reports credible enough to share with engineering."
  - **Observability**: adds structured `pinned_plans SET|HIT|MISS|PRUNED` INFO logs — consistent with the existing `state-driven reporting` pattern in `systemPatterns.md`.
  - **Performance**: eliminates ~2 Bedrock calls (Stage 1 + Stage 2) on every `/execute` that carries a `plan_id` — reduces `/execute` latency by roughly the Stage 1+2 compile time (~5–10s typical).
  - **Security**: pinned plan files carry no credentials and no PII — only the AC text and compiled TestPlan. Standard filesystem permissions on `storage/pinned_plans/` are sufficient.
  - **Storage**: at 14-day TTL and typical usage (~10 preview calls/day × ~50 KB/file), the on-disk footprint is bounded at roughly 7 MB. Startup prune keeps it there.
  - **Availability**: does not change vQA's availability posture — a missing plan file fails loudly (404), which is the correct behavior. A caller can always re-preview to author a new plan.

## User Journey Definition

*(NFR — superseded by the `## Specification` section above. That section is the authoritative Verification Method + Acceptance Criteria.)*

## Test Strategy

### Approach
- **Emphasis**: unit + integration (per source doc — two new test files).
- **Target test count**: ~8-10 across two new test files (7 explicit in the source doc + a small buffer for edge cases surfaced during implementation).

### File Organization
- **New test files**:
  - `tests/test_pinned_plans.py` — store roundtrip, missing, expired-lazy-prune, prune-expired-batch.
  - `tests/test_execute_plan_id.py` — short-circuit assertion (load-bearing), 404 miss, 410 expiry, 400 mutex.
- **Extend existing**: none anticipated (contract is additive; existing `/preview-steps` GET and `/execute` callers behave identically without the new fields).

### What NOT to Test
- Byte-identical replay across two separate `/execute` calls — the load-bearing assertion (`call_count == 0` on the LLM stages) is a strictly stronger invariant than "same output on two runs."
- Bedrock non-determinism itself — that's the constraint we're routing around; testing it would be flaky by definition.
- OpenAPI regeneration — verified out-of-band on merge (see source doc).

### Per-Phase Test Guidance
*(Spec Writer + Step 5 will finalize phase count. Provisional phases below.)*
- Phase 1 (store): all 4 tests in `test_pinned_plans.py`.
- Phase 2 (schemas + state): no dedicated tests (verified in Phase 4 integration).
- Phase 3 (short-circuit in `ac_parser`): the `test_ac_parser_short_circuits_on_pinned_plan` case.
- Phase 4 (routes wiring): 404 / 410 / mutex-400 tests in `test_execute_plan_id.py`.

## Implementation Roadmap

### New Source Files (pin path + extension)
- [ ] `backend/engine/pinned_plans.py` — pinned TestPlan store (save/load/prune, TTL, custom exceptions).
- [ ] `tests/test_pinned_plans.py` — unit tests for the store.
- [ ] `tests/test_execute_plan_id.py` — integration tests for the `/execute` `plan_id` path.
- [ ] `backend/config/__init__.py` — extend (add `pinned_plan_ttl_days`).
- [ ] `backend/api/schemas.py` — extend (add `ExecuteRequest.plan_id`, `PreviewStepsRequest`, `PreviewStepsResponse.plan_id`).
- [ ] `backend/engine/state.py` — extend (`pinned_plan`, `pinned_plan_id` fields + `make_initial_state` defaults).
- [ ] `backend/engine/ac_parser.py` — extend (short-circuit at top of `ac_parser_node`).
- [ ] `backend/api/routes.py` — extend (POST `/preview-steps` handler + `execute_single` resolution at `:1362`).
- [ ] `backend/main.py` — extend (add `pinned_plans.prune_expired()` call inside the existing `lifespan()` on-startup block at `:139`). **NOTE:** the source doc points at `backend/api/app.py`, which does not exist in this repo — this line is the drift-corrected target.

### Phases
- [x] Phase 1: Pinned-plan store + config (`pinned_plans.py`, `config/__init__.py`, all store unit tests).
- [x] Phase 2: Schemas + state (`schemas.py`, `state.py`) — no runtime behavior yet.
- [x] Phase 3: `ac_parser_node` short-circuit + short-circuit assertion test.
- [x] Phase 4: Routes wiring (POST `/preview-steps`, `execute_single` plan_id resolution at `backend/api/routes.py:1362`) + 404 / 410 / mutex-400 tests + startup prune wired into `backend/main.py`'s existing `lifespan()` block at `:139`.
- [x] Phase 5: Verify additive contract (grep callers of `/preview-steps` and `/execute`; ensure omitting new fields is a no-op) + regen OpenAPI + smoke.

## Creative Phases

- [x] **Not required.** Confirmed by Spec Writer (Step 3.3): the source-of-truth plan doc has already resolved the single design decision (introduce a new pinned-plan primitive vs. re-using the content-hash cache in `backend/engine/ac_parse_cache.py`). Spec confidence is HIGH across Verification Method, Success Criteria, and Acceptance Criteria.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Current Step**: Archived
**Latest Commit**: 0a56a46 (pre-archive) — archive commit to follow
**Can Resume**: NO
**Current Build**: Phase 5: Additive contract verification (vqa-pinned-testplans)
**Build Started**: 2026-08-18T16:30:00Z
**Phase Number**: 5 of 5 COMPLETE — BUILD_COMPLETE
**Is Multi-Phase**: YES

### Current Build Step
**Step**: Step 11 - Git Completion (Phase 5)
**Status**: COMPLETE
**Completed**: 2026-08-18T18:15:00Z

### Completed Steps
- Step 0.0: Resolved `vqa-pinned-testplans` as a feature slug (feature file present on `chore/banyan-admin` via PR #85).
- Step 0.1: Task file auto-provisioned; feature branch `feature/vqa-pinned-testplans` created off `origin/main`; roadmap `linked_tasks` set to `[vqa-pinned-testplans]` (rides feature branch — collapsed pr_target/metadata_branch).
- Step 0.2: Phase gate — plan preconditions met (feature exists with complexity Level 3; task file present).
- Step 0.3: Branch setup — on `feature/vqa-pinned-testplans`.
- Step 3 (plan): Spec Writer Agent (Sonnet) — appended `## Specification` section with 10 canonical ACs (6 × AC-VERIFY, 3 × AC-ERROR, 1 × AC-INVARIANT); code verification PASSED for 8/9 targets (drift: `backend/api/app.py` does not exist, wired to `backend/main.py` lifespan instead — fixed in Roadmap).
- Step 3.2 (plan): Human review — auto-approved under user directive "work without stopping for clarifying questions."
- Step 3.2a (plan): Taxonomy lint — CLEAN.
- Step 3.3 (plan): Creative Phase decision — none required.
- Step 4 (plan): Codebase analysis — completed by Spec Writer.
- Step 5 (plan): Implementation Plan — 5 phases documented.
- Step 6 (plan): Validation Gate — PASSED.
- Step 0.5 (build P1): Worktree created at ~/banyan-wt/vQA/feature-vqa-pinned-testplans/.
- Step 0.6 (build P1): Phase gate PASSED.
- Step 1 (build P1): Phase 1 identified — Pinned-plan store + config.
- Step 2 (build P1): Level 3 implementation rules loaded.
- Step 3 (build P1): TDD Agent — RED CONFIRMED: 16 tests failing (no implementation). GREEN: 16/16 passing. Files: backend/engine/pinned_plans.py, backend/config/__init__.py (extend), tests/test_pinned_plans.py.
- Step 5 (build P1): Test batching — single batch (all tests in test_pinned_plans.py, single module).
- Step 6 (build P1): Batch execution — 16/16 passing.
- Step 7 (build P1): Integration verification — full suite 2047 passed / 79 pre-existing failures (none related to Phase 1); lint PASS; build PASS.
- Step 8 (build P1): Code review — APPROVED. No blocking issues.
- Step 11 (build P1): Phase 1 committed + pushed (ebe1cc8).
- Step 1 (build P2): Phase 2 identified — Schemas + state.
- Step 3 (build P2): RED CONFIRMED: ImportError (PreviewStepsRequest not in schemas). GREEN: 24/24 passing (15 schema tests + 9 state tests).
- Step 5 (build P2): Test batching — 2 batches (test_schemas_pinned_plans.py, test_state_pinned_plans.py), no source file overlap, parallel-eligible.
- Step 6 (build P2): Batch execution — 24/24 passing.
- Step 7 (build P2): Integration verification — 2066 passed / 79 pre-existing failures (same count as Phase 1); no regression.
- Step 8 (build P2): Code review — APPROVED. Additive schema/state changes, no logic, no security surface.
- Step 1 (build P3): Phase 3 identified — ac_parser_node short-circuit + short-circuit assertion test.
- Step 3 (build P3): RED CONFIRMED: 6 tests failing (no short-circuit implementation). GREEN: 8/8 passing. Files: backend/engine/ac_parser.py (extend), tests/test_ac_parser_short_circuit.py (NEW).
- Step 5 (build P3): Test batching — single batch (test_ac_parser_short_circuit.py / ac_parser.py, single component).
- Step 6 (build P3): Batch execution — 8/8 passing.
- Step 7 (build P3): Integration verification — 2076 passed / 77 pre-existing failures (2 fewer than Phase 2; no regression from Phase 3).
- Step 8 (build P3): Code review — APPROVED. Additive short-circuit at top of ac_parser_node; structured log; no fallback; 8 tests covering AC-VERIFY-3 and AC-INVARIANT-1.

### Sub-Agents
- Step 3 TDD (P1): COMPLETE (2026-08-18) — 16 tests (RED→GREEN), 2 source files (backend/engine/pinned_plans.py NEW, backend/config/__init__.py EXTENDED), 1 test file (tests/test_pinned_plans.py NEW).
- Step 3 TDD (P2): COMPLETE (2026-08-18) — 24 tests (RED→GREEN), 2 source files (backend/api/schemas.py EXTENDED, backend/engine/state.py EXTENDED), 2 test files (tests/test_schemas_pinned_plans.py NEW, tests/test_state_pinned_plans.py NEW).
- Step 3 TDD (P3): COMPLETE (2026-08-18) — 8 tests (RED→GREEN), 1 source file (backend/engine/ac_parser.py EXTENDED: short-circuit block added), 1 test file (tests/test_ac_parser_short_circuit.py NEW).

- Step 3 TDD (P4): COMPLETE (2026-08-18) — 7 tests (RED→GREEN), 2 source files (backend/api/routes.py EXTENDED, backend/main.py EXTENDED), 1 test file (tests/test_execute_plan_id.py NEW). RED: 6/7 failing (1 already passing — unknown plan_id 404). GREEN: 7/7 passing.
- Step 7 (build P4): Integration verification — 2088 passed / 77 pre-existing failures (same baseline as Phase 3); no regression from Phase 4. Lint pre-existing issues only (routes.py import sort, main.py F401/I001 — all pre-Phase 4).
- Step 8 (build P4): Code review — APPROVED. Mutex guard (400) before plan_id resolution; startup prune non-fatal; no new dependencies; no PII/injection surface.
- Step 3 (build P5): TDD (verification phase) — 17 tests (all GREEN immediately; prior phases implement the contract being verified). 2 new test files: tests/test_additive_contract.py (7 tests, EC-COMPAT-1..5), tests/test_openapi_pinned_fields.py (10 tests, OA-1..4). Lint PASS.
- Step 7 (build P5): Integration verification — 2105 passed / 77 pre-existing failures (same baseline); +17 from Phase 5 tests. No regression.
- Step 8 (build P5): Code review — APPROVED. Test-only phase; no production code; additive contract proofed.
- Step 11 (build P5): Phase 5 committed + pushed. BUILD_COMPLETE.

### Guard & Recovery Log
Phase 1: commit guard PASS (prod=2 test=1) commit ebe1cc8.
Phase 2: commit guard PASS (prod=2 test=2) — schemas.py + state.py extended; 2 new test files.
Phase 3: commit guard PASS (prod=1 test=1) — ac_parser.py extended; test_ac_parser_short_circuit.py new.
Phase 4: commit guard PASS (prod=2 test=1) — routes.py + main.py extended; test_execute_plan_id.py new.
Phase 5: commit guard PASS (prod=0 test=2) — test-only phase; C2 not triggered (prod=0).

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A
**Notes**: All 5 phases + reflection + archive complete. Feature status set to `completed`; two `_learned/` files updated additively. Feature PR opens next.
