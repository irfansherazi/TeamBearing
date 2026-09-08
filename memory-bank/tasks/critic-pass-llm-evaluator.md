---
slug: critic-pass-llm-evaluator
feature: critic-pass-llm-evaluator
status: COMPLETE
completed: 2026-07-30
---

# critic-pass-llm-evaluator: Critic-Pass LLM Evaluator

**Complexity**: Level 3
**Status**: COMPLETE
**Completed**: 2026-07-30
**Reflection**: memory-bank/reflection/critic-pass-llm-evaluator-reflection.md
**Archived**: memory-bank/archive/critic-pass-llm-evaluator-archive.md
**Roadmap**: critic-pass-llm-evaluator
**Branch**: feature/critic-pass-llm-evaluator
**Worktree**: N/A

## Task Description

Insert a small LLM critic pass between Stage 2 (TestPlan compilation) and execution that re-reads the acceptance criteria + compiled TestPlan and flags mismatches before we spend browser time. Mirrors the Playwright Healer / Anthropic Skill Creator test-measure-refine loop.

### Motivation

vQA today has a static heuristic ambiguity-detection pass but no LLM critic re-scoring the compiled plan against the AC. The compiled TestPlan can drift from the AC (missing steps, hallucinated success criteria, wrong persona, misordered actions) and today we only detect this at execution time — after the browser has already run steps. A cheap Haiku pass at plan-compile time catches these before any browser work happens, and gives the planner structured feedback to regenerate rather than a hard failure.

Promoted from candidate #1 of the [2026 agentic-testing SOTA adoption umbrella](../roadmap/agentic-testing-sota-adoption-2026.md).

### In scope

- New engine node between Stage 2 (`ac_parser` / TestPlan compilation) and Stage 3 (executor loop)
- Haiku model (small task, structured output)
- Verdict schema: `pass` | `mismatch` with typed reasons (missing_step, hallucinated_ac, persona_mismatch, order_violation, ambiguous_step)
- Feedback loop: on `mismatch`, structured reasons feed back into the planner for one retry pass
- Bounded retries (max 2 critic-planner cycles per AC) to prevent loops
- Observability: emit critic verdict + reason codes to the run report

### Out of scope

- Post-execution critic (candidate #8, self-healing recovery router — separate feature)
- Rewriting `ac_parser` or the executor
- Human-in-the-loop escalation from the critic (uses existing HITL if the critic-planner loop exhausts retries)
- Changes to the AC parsing itself (candidate #4, domain plugin registry, is separate)

### References

- Anthropic Skill Creator test-measure-refine loop (Mar 2026)
- Playwright Healer agent (Playwright v1.56)
- Existing vQA engine files: `backend/engine/verifier.py`, `backend/engine/preflight_check.py`, `backend/engine/recovery_router.py`, `backend/kb/preflight.py`

## Specification

**Feature Type**: NFR/Infrastructure
*Note: this is a new LangGraph engine node — no UI surface. Observability (verdict in run report) is the only user-visible output.*

**Creative Exploration Needed**: Yes — verdict schema field names and types, planner-feedback grammar (how structured reasons are injected into the ac_parser re-prompt), and retry-cycle detection mechanism require an Architecture Design creative phase before implementation.

### Verification Method

- **Test method**: `pytest tests/engine/test_critic_node.py -v` (new file); existing test suite `pytest tests/ -v` must continue to pass without modification. Manual smoke: run a Golden-10 ticket through `POST /execute` and inspect `GET /status/{run_id}` JSON for `run_metrics.critic_verdicts` field; run a known-bad TestPlan (artificially corrupted by removing one step from `test_plan.steps`) and verify the critic emits `verdict: "mismatch"` before the browser opens.
- **Success metrics**:
  - Critic emits `verdict: "pass"` for 9/10 of the Golden-10 sample (well-formed plans produced by the current parser pass the check)
  - Critic emits `verdict: "mismatch"` with at least one correctly classified `reason_code` for an injected bad plan (a step removed from `test_plan.steps` that exists in the raw AC text)
  - Added latency per run: p95 < 2 s per critic invocation (Haiku, structured output, no browser I/O)
  - Retry loop terminates within 2 cycles — `max_critic_retries = 2` is never exceeded per run
  - Haiku token budget per call: < 500 tokens input (AC text + TestPlan step summaries) + < 100 tokens output (structured verdict JSON); measurable from Bedrock usage metadata
- **Observable at**:
  - `GET /status/{run_id}` response body → `run_metrics.critic_verdicts` (new key — list of CriticVerdict dicts, one per retry cycle)
  - HTML audit report → new "Critic Pass" section rendered by `backend/engine/reporter.py::_render_critic_pass_section()` — one row per verdict: verdict badge, reason codes, retry count
  - Backend Python logs: `INFO [{run_id}] critic_node: verdict={verdict} reasons={reason_codes} retry={retry_count}` emitted by `backend/engine/critic_node.py`
- **Verification frequency**: Per-run — fires once per run (not per-step; the critic evaluates the full compiled TestPlan against the full AC text in a single call)

### Acceptance Criteria

#### AC-VERIFY-1: Critic node is registered in the LangGraph graph and fires on every AI-mode run
**Priority**: MUST
**Given** `build_graph()` is called in `backend/engine/graph.py`
**When** the compiled `StateGraph` object is inspected
**Then** `"critic"` is present in `graph.nodes`; the node `"critic"` is reachable from `"ac_parser"` and has outgoing conditional edges to both `"setup_role"` (pass path) and `"ac_parser"` (retry path); static Playwright runs (`execution_engine="static"`) bypass the critic node (route directly to `playwright_executor`)

#### AC-VERIFY-2: Critic emits a structured verdict conforming to the CriticVerdict schema
**Priority**: MUST
**Given** `critic_node` receives a `VQAState` with a non-None `test_plan` dict and non-empty `acceptance_criteria_steps`
**When** the Haiku LLM call completes successfully
**Then** the node writes `critic_result` to state as a dict that passes `CriticVerdict.model_validate(critic_result)` without error; specifically: `verdict` is exactly `"pass"` or `"mismatch"`; `reason_codes` is a list containing zero or more values from `["missing_step", "hallucinated_ac", "persona_mismatch", "order_violation", "ambiguous_step"]` and no other values; `retry_count` is an integer in range 0–2; `critic_skipped` defaults to `False`

#### AC-VERIFY-3: Pass verdict routes directly to setup_role without modifying the test plan
**Priority**: MUST
**Given** `critic_node` emits `critic_result.verdict == "pass"` (retry_count 0, 1, or 2)
**When** the LangGraph conditional edge function `route_after_critic` evaluates the updated state
**Then** the next node is `"setup_role"`; `state["test_plan"]` is identical to the value it had before the critic fired; `state["acceptance_criteria_steps"]` is unchanged; `state["critic_feedback"]` is `None` or absent

#### AC-VERIFY-4: Mismatch verdict with retries remaining triggers ac_parser re-run with structured feedback
**Priority**: MUST
**Given** `critic_node` emits `critic_result.verdict == "mismatch"` and `critic_result.retry_count < 2`
**When** `route_after_critic` evaluates the state
**Then** the next node is `"ac_parser"`; `state["critic_feedback"]` is set to a non-empty dict containing at minimum `{"reason_codes": [...], "guidance": "..."}` where `guidance` is a plain-English description of the detected mismatch for the re-parser to act on; `critic_result.retry_count` is incremented by 1 before the state is written

#### AC-VERIFY-5: Retry cap enforcement — exhausted retries fall through to setup_role
**Priority**: MUST
**Given** `critic_result.retry_count == 2` and the critic still returns `verdict: "mismatch"`
**When** `route_after_critic` evaluates the state
**Then** the next node is `"setup_role"` (not `"ac_parser"`); `critic_feedback` is cleared to `None`; the critic logs a WARNING: `[{run_id}] critic_node: max retries exhausted — proceeding with imperfect plan`; the run continues without aborting and the reporter renders the exhaustion in the Critic Pass section

#### AC-ERROR-1: Haiku API failure produces a safe synthetic pass verdict and does not abort the run
**Priority**: MUST
**Given** the Bedrock API call within `critic_node` raises any exception (timeout, throttling, `ClientError`, network error)
**When** the exception is caught in the node's `try/except` block
**Then** the node returns `critic_result` with `{"verdict": "pass", "reason_codes": [], "retry_count": 0, "critic_skipped": True}`; the node logs `WARNING [{run_id}] critic_node: Haiku call failed ({exc_type}: {exc}) — critic skipped, routing to setup_role`; `route_after_critic` routes to `"setup_role"`; the HTML report Critic Pass section shows "SKIPPED (API error)" rather than a pass/mismatch badge

#### AC-INTEGRATION-1: Mismatch reason codes in the run report are grounded in actual AC text vs TestPlan discrepancies
**Priority**: MUST
**Given** a completed run where `critic_result.verdict == "mismatch"` was emitted (either recovered or exhausted)
**When** a reviewer reads the HTML audit report Critic Pass section and cross-checks three cited reason codes against the raw AC text and compiled `test_plan.steps`
**Then** each `reason_code` corresponds to a specific, real discrepancy: `missing_step` means a step present in `acceptance_criteria_steps` has no `goal`-matching entry in `test_plan.steps`; `hallucinated_ac` means a `test_plan.steps` entry has no traceable origin in the raw AC text; `persona_mismatch` means the `target_persona` or `step_type` in a step contradicts the role stated in the AC; the critic does not invent discrepancies that do not exist

#### AC-ASYNC-1: Critic retry event is broadcast on the WebSocket stream within 500 ms of occurrence
**Priority**: SHOULD
**Given** a live run is active and `critic_node` emits `verdict: "mismatch"` triggering a retry
**When** a WebSocket client is connected to `/ws/{run_id}`
**Then** a log event is broadcast within 500 ms containing `event_type: "critic_mismatch"` (or equivalent structured log key), `retry_count: K`, and `reason_codes: [...]`; this allows the dashboard's CopilotSidebar to surface the critic retry as a log line without polling `GET /status`

### Scope Boundaries

- **In scope**:
  - New file `backend/engine/critic_node.py` — `critic_node(state: VQAState) -> dict` async function + `route_after_critic(state: VQAState) -> str` routing function
  - New `CriticVerdict` Pydantic model added to `backend/engine/schemas.py`
  - Graph wiring in `backend/engine/graph.py`: `graph.add_node("critic", critic_node)`, `graph.add_edge("ac_parser", "critic")`, `graph.add_conditional_edges("critic", route_after_critic, {"setup_role": "setup_role", "ac_parser": "ac_parser"})` — replacing the existing direct `graph.add_edge("ac_parser", "setup_role")` at line 1450
  - Two new VQAState fields in `backend/engine/state.py`: `critic_result: dict | None` and `critic_feedback: dict | None`
  - HTML report section: new `_render_critic_pass_section()` in `backend/engine/reporter.py`, wired into `reporter_node` at the report-assembly point
  - `run_metrics` key `critic_verdicts` surfaced in `GET /status/{run_id}` response via `backend/api/routes.py` (the `_run_states[run_id]["state"]` already carries `run_metrics` which is returned verbatim)
  - New test file `tests/engine/test_critic_node.py`
  - Minimal addition to `backend/engine/ac_parser.py`: read `state.get("critic_feedback")` at the top of `ac_parser_node` and, when non-None, append a `<critic_feedback>` block to the BDD normalizer prompt before the LLM call

- **Out of scope**:
  - `backend/engine/verifier.py` — NOT touched (post-execution verifier is a separate concern)
  - `backend/engine/executor.py` — NOT touched
  - `backend/engine/planner.py` — NOT touched
  - `backend/engine/preflight_check.py` — NOT touched
  - `backend/kb/preflight.py` — NOT touched
  - `frontend/` — no UI changes; CopilotSidebar already displays WebSocket log events; no new component needed
  - HITL escalation path — not added; existing HITL fires after execution retries exhausted, as today

- **Dependencies**:
  - AWS Bedrock Claude Haiku model access via `settings.haiku_model_id` (already configured in `backend/config.py` and used in `backend/engine/verifier.py`)
  - `langchain-aws` `ChatBedrockConverse` (already imported throughout `backend/engine/`)
  - `instructor` or Bedrock native tool-use for structured output (already used in `backend/engine/ac_parser.py` lines ~66–73)
  - Backward-compatible `VQAState` schema additions (`dict | None` fields default to `None`)

- **NFR implications**:
  - **Cost**: ~200–400 Haiku input tokens + ~50–100 output tokens per critic call. For a 10-step ticket with 0 retries: ~$0.0002. For 2 retries: ~$0.0006. Negligible against existing Sonnet planner cost.
  - **Latency**: +~0.8–1.5 s per critic invocation (Haiku p50 latency). One invocation per run (not per step). For a 10-step ticket: adds ~1 s total before the browser opens. Within the < 30 s "first browser action" NFR.
  - **Retry latency**: A mismatch triggering one ac_parser re-run adds ~5–10 s (Sonnet Stage 2 re-compile). Total first-action time with one retry: ~15–25 s, still within the 30 s NFR gate.

### Creative Exploration Needed

Architecture Design creative phase is confirmed necessary for:

1. **Verdict schema finalization** — `reason_codes` as a `list[Literal[...]]` vs. a list of `ReasonCode` objects with optional sub-fields (e.g., `{"code": "missing_step", "ac_text": "...", "missing_from": "step_3"}`). The richer schema enables better re-parse guidance but requires a more complex Pydantic model.
2. **Planner-feedback grammar** — How `critic_feedback` is injected into the ac_parser re-prompt. Option A: append a `<critic_feedback>` XML block to the existing BDD normalizer system prompt (simpler, but breaks Bedrock prompt cache). Option B: pass feedback as a new HumanMessage in a 3-turn conversation (preserves cache, matches pattern in `ac_parser.py`). Confidence: LOW.
3. **Retry counter placement** — `critic_result.retry_count` per-run (resets to 0 at run start) vs. a persistent `critic_retries_total` that accumulates across ac_parser re-runs. Per-run is simpler; total enables detecting runaway re-parses across multiple mismatch cycles.
4. **Pipeline placement precision** — Critic planned between `ac_parser` and `setup_role`. Alternative: between `setup_role` and `login` (after role resolution, so `RoleContext.role_name` is available for `persona_mismatch` validation). The earlier placement is cheaper (no login required) but the critic cannot validate persona details without `RoleContext`. Confidence: LOW.

## User Journey Definition

**Feature Type**: NFR/Infrastructure
*Note: this is a new LangGraph engine node — no direct end-user UI.*

**Primary Persona**: QA Lead / Automation Engineer (runs Jira-driven tests via `POST /execute`; benefits from earlier drift detection before browser time is wasted on a drifted plan)

**Observable surface**: `GET /status/{run_id}` JSON response `run_metrics.critic_verdicts` field + HTML audit report "Critic Pass" section

### Pipeline Placement (concrete)

- **Current pipeline** (from `backend/engine/graph.py` line 1449–1450):
  ```
  ac_parser → setup_role → login → (replay_check or playwright_executor) → planner → executor → ...
  ```
- **Post-implementation pipeline**:
  ```
  ac_parser → critic → setup_role → login → ...
                ├── pass → setup_role
                └── mismatch (retry_count < 2) → ac_parser (with critic_feedback)
  ```
- **File**: `backend/engine/graph.py`
- **Edge change**: Remove `graph.add_edge("ac_parser", "setup_role")` (line 1450); add `graph.add_edge("ac_parser", "critic")` + `graph.add_conditional_edges("critic", route_after_critic, {"setup_role": "setup_role", "ac_parser": "ac_parser"})`

## Test Strategy

### Approach

Unit tests only — no browser or live Bedrock required. The critic node takes `VQAState` (dict) as input and returns a partial state update; all behavior is testable with mocked Haiku responses and synthetic `test_plan` dicts. The ac_parser re-parse integration (receiving `critic_feedback`) requires a mocked LLM call returning a modified TestPlan.

Pattern to follow: `tests/test_preflight_check.py` — `unittest.mock.patch` for Bedrock/settings, `AsyncMock` for async node functions, `pytest.mark.asyncio` for async test bodies.

- **Target test count**: 8–10 unit tests in `tests/engine/test_critic_node.py`

### File Organization

- **New**: `tests/engine/test_critic_node.py` — all critic-node unit tests (routing, schema validation, error handling)
- **Unchanged**: `tests/test_preflight_check.py` — no modifications needed
- **Optional extend**: `tests/engine/test_verifier_guardrails.py` — add one graph-topology test asserting `"critic"` is reachable from `"ac_parser"` in the compiled graph

### What NOT to Test

- Haiku model response quality (content) — test that routing logic is correct given a verdict, not that Haiku produces semantically accurate reason codes
- HTML report rendering fidelity — not covered by unit tests; visual output only
- End-to-end browser execution — the critic is purely pre-execution; no Playwright dependency

### Per-Phase Test Guidance

**Phase 1 — Critic node unit tests (`tests/engine/test_critic_node.py`)**:
- Pass verdict with `retry_count=0` → `route_after_critic` returns `"setup_role"`
- Mismatch verdict with `retry_count=0` → `route_after_critic` returns `"ac_parser"` and `state["critic_feedback"]` is non-None
- Mismatch verdict with `retry_count=2` → `route_after_critic` returns `"setup_role"` (exhausted)
- Haiku `ClientError` exception → `critic_result.critic_skipped == True`, routes to `"setup_role"`
- `CriticVerdict` Pydantic validation: valid schema passes, invalid `verdict` value raises `ValidationError`
- `reason_codes` with invalid value raises `ValidationError`

**Phase 2 — Graph wiring tests**:
- `"critic"` node present in compiled graph after `build_graph()`
- Direct edge from `"ac_parser"` to `"setup_role"` no longer exists (replaced by critic)
- Conditional edges from `"critic"` target both `"setup_role"` and `"ac_parser"`

## Implementation Roadmap

### New Source Files (pin path + extension)

- [ ] `backend/engine/critic_node.py` — new critic node + `route_after_critic` conditional-edge function
- [ ] `backend/engine/schemas.py` — **extend**: add `CriticVerdict` Pydantic model
- [ ] `backend/engine/state.py` — **extend**: add `critic_result: dict | None` and `critic_feedback: dict | None` fields to `VQAState` TypedDict
- [ ] `backend/engine/graph.py` — **extend**: register `critic_node`, replace `graph.add_edge("ac_parser", "setup_role")` at line 1450 with `graph.add_edge("ac_parser", "critic")` + conditional edges
- [ ] `backend/engine/ac_parser.py` — **extend**: read `state.get("critic_feedback")` at top of `ac_parser_node`; inject as new `<critic_feedback>` block (or 3-turn conversation — TBD by creative) into BDD normalizer prompt
- [ ] `backend/engine/reporter.py` — **extend**: add `_render_critic_pass_section()` and wire into `reporter_node`; renders one row per verdict (badge, reason codes, retry count)
- [ ] `backend/api/routes.py` — verify only (Spec Writer confirmed `run_metrics.critic_verdicts` flows through existing `_run_states` passthrough; no code change needed unless routing check reveals otherwise)
- [ ] `tests/engine/test_critic_node.py` — new test file (Phase 1)
- [ ] `tests/engine/test_verifier_guardrails.py` — **optional extend**: one graph-topology assertion

### Phases

- [ ] **Phase 0 (Creative)**: Architecture Design — resolve verdict schema shape, feedback grammar, retry-counter placement, and pipeline placement precision (see Creative Phases below). Blocking on `/bmb:creative critic-pass-llm-evaluator`. **Deliverable**: `memory-bank/creative/critic-pass-llm-evaluator-architecture.md` with decisions on all 4 open questions.

- [x] **Phase 1: Verdict schema + critic node core** — implements AC-VERIFY-2, AC-VERIFY-3, AC-VERIFY-5, AC-ERROR-1.
  - Add `CriticVerdict` to `backend/engine/schemas.py` per creative-phase decisions
  - Add `critic_result` and `critic_feedback` fields to `VQAState` in `backend/engine/state.py`
  - Implement `critic_node` async function in `backend/engine/critic_node.py`: Haiku call (via `settings.haiku_model_id` — pattern from `backend/engine/verifier.py`), structured-output extraction (via `instructor` or Bedrock native tool-use — pattern from `backend/engine/ac_parser.py`), try/except for `ClientError` → synthetic pass with `critic_skipped=True`
  - Implement `route_after_critic` conditional-edge function: pass → setup_role; mismatch + retry_count<2 → ac_parser; mismatch + retry_count==2 → setup_role (with WARN log)
  - `tests/engine/test_critic_node.py`: 6 tests — schema validation (valid + invalid), pass routing, mismatch routing with retries remaining, retry-cap routing, Haiku exception → synthetic pass. Pattern: mock Bedrock via `unittest.mock.patch`, use `pytest.mark.asyncio` per `tests/test_preflight_check.py`.
  - Config: `settings.max_critic_retries` (default 2), `settings.critic_enabled` (feature flag, default True) in `backend/config.py`

- [x] **Phase 2: Graph wiring + ac_parser feedback integration** — implements AC-VERIFY-1, AC-VERIFY-4.
  - `backend/engine/graph.py`: `graph.add_node("critic", critic_node)`, remove line 1450 direct edge, add conditional edges. Guard: static Playwright runs (`execution_engine="static"`) bypass — verify existing routing check handles this or add explicit skip
  - `backend/engine/ac_parser.py`: at top of `ac_parser_node`, read `state.get("critic_feedback")`. When non-None, inject `<critic_feedback>` block (or turn-based conversation, per creative decision) into the BDD normalizer prompt. Increment `critic_result.retry_count` when the re-parse occurs (or track separately in state — per creative decision on counter placement)
  - Tests in `tests/engine/test_critic_node.py` (+2 tests): graph topology (`"critic"` in `compiled_graph.nodes`; reachable from `"ac_parser"`; conditional edges target both branches); optional extend to `tests/engine/test_verifier_guardrails.py`

- [x] **Phase 3: Observability + grounded-verdict verification** — implements AC-INTEGRATION-1, AC-ASYNC-1.
  - `backend/engine/reporter.py`: `_render_critic_pass_section()` — HTML rendering (badge, reason codes, retry count, one row per verdict). Handle `critic_skipped` and exhausted-retry cases with distinct visual states
  - Verify `run_metrics.critic_verdicts` flows through `GET /status/{run_id}` (Spec Writer said passthrough; confirm during build)
  - WebSocket event: emit `event_type: "critic_mismatch"` on retry via existing log broadcaster in `backend/engine/critic_node.py`; verify CopilotSidebar renders it (frontend already listens to log stream — no frontend change needed)
  - Manual verification: run 1 well-formed Golden-10 ticket → assert pass verdict; run 1 corrupted TestPlan (delete a step programmatically before critic) → assert mismatch with `missing_step` reason code (AC-INTEGRATION-1)
  - Optional: sample 3–5 reason codes from a real mismatch run and cross-check they map to actual AC-vs-TestPlan discrepancies (manual audit)

### AC → Phase mapping

| AC | Phase |
|---|---|
| AC-VERIFY-1 (graph registration) | Phase 2 |
| AC-VERIFY-2 (verdict schema) | Phase 1 |
| AC-VERIFY-3 (pass routing) | Phase 1 |
| AC-VERIFY-4 (mismatch retry) | Phase 2 |
| AC-VERIFY-5 (retry cap) | Phase 1 |
| AC-ERROR-1 (Haiku failure) | Phase 1 |
| AC-INTEGRATION-1 (grounded reasons) | Phase 3 |
| AC-ASYNC-1 (WebSocket <500ms) | Phase 3 |

### Guiding Principles alignment (systemPatterns.md)

- **Multimodal Grounding**: n/a — critic runs pre-browser, no see-think-act coupling. ✅ No conflict.
- **Config in Environment**: `settings.max_critic_retries`, `settings.critic_enabled`, `settings.haiku_model_id` — all from `.env` via `backend/config.py`. ✅
- **HITL as Learning Signal**: The critic does NOT feed `knowledge/human_guidance.md` (the critic isn't human; its verdicts aren't ratified guidance). ✅ Not a violation — the critic is an automated pre-check, not a human handoff.
- **Failure Diary Pattern**: Retry-cap (2 max) mirrors the failure-diary retry-loop-prevention principle. ✅

No undocumented deviations.

## Creative Phases

- [x] Architecture Design (verdict schema, retry protocol, planner-feedback grammar) → COMPLETE — `memory-bank/creative/critic-pass-llm-evaluator-architecture.md`

### Decisions summary (from architecture doc)

| Q | Decision | Confidence |
|---|---|---|
| Q1 verdict schema | Option A — flat `Literal[...]` `reason_codes` + peer `feedback_summary: str` field (mirrors `VerifierResult.evidence` pattern in `verifier.py:275-295`) | HIGH |
| Q2 feedback grammar | Option B — pass `critic_feedback` as `HumanMessage` in 2-turn conversation; `BDD_NORMALIZER_PROMPT` stays byte-identical. Saves 1.2-1.6s Bedrock cache-hit latency per retry | HIGH |
| Q3 retry counter | Option A — per-run `critic_result.retry_count` (matches every existing retry counter; Failure Diary pattern) | HIGH |
| Q4 pipeline placement | Option A (planned) — `ac_parser → critic → setup_role`. Option B refuted: `role_key`/`role_name` already in initial state via `role_queue[0]` + `ROLE_REGISTRY` lookup, so `persona_mismatch` works in position A with zero login cost | HIGH |

### Effect on Implementation Roadmap

- **Phase 1 `schemas.py`** (~line 350): add `feedback_summary: str` field to `CriticVerdict` alongside `reason_codes`
- **Phase 1 `critic_node.py`**: look up `role_name` from `ROLE_REGISTRY[state["role_queue"][0]]` for the persona-check portion of the Haiku prompt
- **Phase 2 `ac_parser.py`** (~lines 333, 388): change from "append `<critic_feedback>` XML block to system prompt" to "add `critic_feedback: dict | None` param to `_stage_1_normalize`; append a `HumanMessage` when non-None". `BDD_NORMALIZER_PROMPT` remains untouched to preserve Bedrock prompt cache

## Design Critique (advisory)

**Backend**: `creative-critique: codex` (from `projectConfig.md`)
**Outcome**: `CREATIVE CRITIQUE: skipped — unresolved:no-companion (glob=∅)`
**Availability**: `auto` (silent fallback per policy)

Codex companion not installed in this project (`memory-bank/.local/codex-cache.md` absent). Per spec Step 4.5, the recorded outcome is the required evidence; findings are advisory and never gate creative. No inline anthropic self-critique invoked since seam is configured for codex, not anthropic.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO
**Auto-Build Mode**: YES
**Last Completed**: Archive (2026-07-30) — memory-bank/archive/critic-pass-llm-evaluator-archive.md

### Halt State
(none)

### Deviations
<!-- Appended on each PROCEED with a non-empty DEVIATIONS list. Empty until first deviation. -->

### Active Sub-Agents
(none)

### Completed Steps
- Step 0.0: Args resolved (feature `critic-pass-llm-evaluator`)
- Step 0.1: Task auto-provisioned on `feature/critic-pass-llm-evaluator`
- Step 0.2: Phase gate passed
- Step 0.3: Branch setup complete
- Step 3: Spec Writer Agent (Sonnet) — spec drafted, taxonomy CLEAN, human approved
- Step 4-5: Codebase analysis + Implementation Roadmap filled (3 phases + creative)
- Step 6: Validation gate passed — spec is concrete (all NFR checklist items ✅), guiding principles respected
- Creative: Architecture Design agent (Opus) — 4 decisions all HIGH confidence; Q4 hybrid Option C avoided (Option B premise refuted by evidence)
- Creative critique: skipped — unresolved:no-companion (Codex absent)
- Auto-build: Pre-flight plan scan CLEAN. Phase 1 build complete.
- Phase 1 (2026-07-30): CriticVerdict schema (schemas.py), critic_node.py + route_after_critic, VQAState fields (state.py), config settings (config.py), 16 unit tests — all passing
- Phase 2 (2026-07-30): graph.py critic node registration + conditional edges (both graphs), ac_parser.py critic_feedback injection via HumanMessage (Option B), 4 topology tests — 20 total passing
- Phase 3 (2026-07-30): reporter.py _render_critic_pass_section() + run_metrics.critic_verdicts, critic_node.py WebSocket broadcast (_broadcast_critic_mismatch), 7 observability tests — 27 total passing
- Reflection (2026-07-30): Reflection Agent (Sonnet) — memory-bank/reflection/critic-pass-llm-evaluator-reflection.md; 3 minor non-blocking follow-ups documented; extractable learnings captured for /bmb:archive consolidation
- Archive (2026-07-30): memory-bank/archive/critic-pass-llm-evaluator-archive.md; 3 learnings consolidated (testing-patterns append, phase-zero-checkpoint append, reporter-html-coupling created); roadmap feature status → completed; task COMPLETE
