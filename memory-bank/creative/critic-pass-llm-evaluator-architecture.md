# Architecture Design: Critic Pass LLM Evaluator

**Task**: critic-pass-llm-evaluator
**Complexity**: Level 3
**Date**: 2026-07-30
**Status**: DECIDED

## Context

The Critic Pass LLM Evaluator inserts a new LangGraph node (`critic_node`) between the AC parser and the executor loop. Its job is to have a cheap Haiku model re-read the raw AC text plus the compiled `TestPlan` (produced by the two-stage Sonnet parser in `backend/engine/ac_parser.py`) and emit a verdict: either `pass` (proceed to `setup_role`) or `mismatch` (send back to `ac_parser` with structured feedback for a bounded retry loop, max 2 cycles).

The plan is written and the wiring pattern is clear. This creative phase resolves **four specific design questions** the spec writer flagged at LOW/MEDIUM confidence: (Q1) the shape of `CriticVerdict.reason_codes`, (Q2) how `critic_feedback` is injected into the Sonnet BDD normalizer on retry without breaking Bedrock's implicit prompt cache, (Q3) where the retry counter lives, and (Q4) exactly where in the pipeline the critic fires. Every other decision (verdict enum values, state field types, test placement) is HIGH confidence and out of scope here.

---

## Q1: Verdict schema shape — `reason_codes`

### Options

- **Option A**: `list[Literal["missing_step", "hallucinated_ac", "persona_mismatch", "order_violation", "ambiguous_step"]]` — a flat list of enum strings. Simple to validate, cheap to emit.
- **Option B**: `list[ReasonCode]` where `ReasonCode` is a Pydantic model with sub-fields like `{code: str, ac_text: str, missing_from: str | None, evidence: str | None}`. Richer, enables the re-parser to know *what* went wrong.

### Evidence from codebase

- `backend/engine/verifier.py:275-278` — `VerifierVerdict(str, Enum)` uses a flat enum (`PASS`, `NOT_YET`, `INCONCLUSIVE`); evidence is a separate `evidence: str` field on `VerifierResult` (`verifier.py:294`), not attached to the verdict token.
- `backend/engine/verifier.py:822-855` — `_vision_llm_check` returns `{"verdict": ..., "reason": "<one line>"}` — a single flat reason string per verdict, not structured pointers.
- `backend/engine/schemas.py:84-94` — `Verification.type` is a flat `Literal[...]`; associated data (`selector_hint`, `expected_text`, ...) lives at the parent level, not nested inside the type discriminator.
- `backend/engine/schemas.py:213-227` — `StructuredACStep.step_type` is `Literal[...]` at the parent level; sub-fields (`target_persona`, `input_value`, ...) are peers, not nested per-type discriminated unions.

### Trade-off

- A: 2 lines of schema, one `Literal` validator, ~30 tokens of output per verdict. But the re-parser must infer from the code alone (or a peer `feedback_summary` string) what was wrong.
- B: ~10-15 lines of schema, more complex `instructor` tool-use signature, ~150-300 tokens of output per verdict (Haiku is 5-10x more expensive to emit long structured JSON than short tokens). But re-parser gets pointer-quality guidance.

### Decision

**Chosen**: **Option A** (with a **peer field** `feedback_summary: str` on the `CriticVerdict` model to carry human-readable rationale — mirrors the `verdict + evidence` split in `VerifierResult`).

**Rationale**: The codebase's dominant pattern is flat `Literal[...]` discriminators + peer explanation fields — `Verifier`, `PlannerAction`, `StructuredACStep` all follow this shape. Option B would introduce a novel discriminated-union pattern for one node's benefit, complicate `instructor`'s BEDROCK_TOOLS mode (which handles flat enums cleanly at `ac_parser.py:500`), and double Haiku output tokens without a corresponding retry-quality win — the re-parser prompt already re-reads the raw AC and the full `TestPlan`, so it doesn't need per-code pointers to locate discrepancies; a plain-English `feedback_summary` is sufficient.

**Implementation guidance**:

```python
# backend/engine/schemas.py — add near line 350 (after MultiActorTestPlan)
class CriticVerdict(BaseModel):
    """Structured verdict from critic_node comparing AC text against compiled TestPlan."""
    verdict: Literal["pass", "mismatch"]
    reason_codes: list[Literal[
        "missing_step",
        "hallucinated_ac",
        "persona_mismatch",
        "order_violation",
        "ambiguous_step",
    ]] = Field(default_factory=list)
    feedback_summary: str = Field(
        default="",
        description=(
            "Plain-English one-paragraph description of the mismatch, "
            "quoting the AC text and the discrepant TestPlan step. "
            "Empty string when verdict='pass'."
        ),
        max_length=1500,
    )
    retry_count: int = Field(default=0, ge=0, le=2)
    critic_skipped: bool = Field(default=False)
```

The `feedback_summary` string is what gets injected into the ac_parser retry prompt as `critic_feedback["guidance"]`. AC-VERIFY-4's requirement that `critic_feedback` contains at minimum `{"reason_codes": [...], "guidance": "..."}` is satisfied by `state["critic_feedback"] = {"reason_codes": verdict.reason_codes, "guidance": verdict.feedback_summary}`.

---

## Q2: Planner-feedback grammar — how `critic_feedback` reaches the ac_parser retry

### Options

- **Option A**: Append a `<critic_feedback>` XML block to the existing `BDD_NORMALIZER_PROMPT` system prompt string, matching the existing `HUMAN CONTEXT` block append pattern at `ac_parser.py:378-386`.
- **Option B**: Pass feedback as a new `HumanMessage` in a multi-turn conversation, keeping the system prompt byte-identical across retries.

### Evidence from codebase

- `backend/engine/ac_parser.py:370-388` — Stage 1 today builds `system_prompt = BDD_NORMALIZER_PROMPT.format(...)` and calls `llm.ainvoke([SystemMessage(content=system_prompt)])` with **only** a SystemMessage, no user turn. It already mutates the system prompt string when `pre_parse_guidance` is present (lines 378-386), appending a delimited block.
- `backend/engine/ac_parser.py:485-533` — Stage 2 uses `instructor` with a **separate** system + user turn (`system=[{"text": system_prompt}]` + `messages=[{"role":"user","content":[{"text":"Compile the BDD scenario ..."}]}]`). This is a 2-turn shape, not the "3-turn" the spec described — Stage 2 already has a user turn where retry feedback could live without touching the system prompt.
- The Stage 1 BDD normalizer is where `critic_feedback` most naturally belongs — that's the LLM that decides which steps exist. Stage 1 today has **no user turn** at all — it is a single-message SystemMessage invocation (`ac_parser.py:388, 401`).
- No `cachePoint` / `cache_control` / `cachePoints` markers exist anywhere in `backend/engine/` (grep confirmed). vQA relies on **implicit** Bedrock/Anthropic prompt caching, which requires an exact prefix match on the prompt to hit.

### Cost math

Assume: 100 runs/day, 15% mismatch rate → ~15 retries/day → ~450/month. Stage 1 BDD normalizer prompt ≈ 3,000 input tokens (raw AC + summary + description + visual context + BDD_NORMALIZER_PROMPT template) and ≈ 800 output tokens. Model = Sonnet at $3/M input, $15/M output; cache-read ≈ $0.30/M (10% of input rate).

Per retry call, cache-miss vs cache-hit cost:
- Cache miss (Option A — system prompt mutates): 3,000 × $3/M + 800 × $15/M = $0.021 per call
- Cache hit (Option B — system prompt static; only user turn changes): (3,000 × $0.30/M) + 800 × $15/M = $0.013 per call
- **Delta per retry**: $0.008/call
- **Monthly delta**: 450 × $0.008 ≈ **$3.60/month** at current scale
- **Latency delta**: Cache-hit typically saves ~30-40% of TTFB on Sonnet (empirical Anthropic docs). At Sonnet Stage 1 p50 ≈ 4s per call, cache-hit saves ≈ 1.2-1.6s per retry. That matters for the 30s "first browser action" NFR gate (`memory-bank/tasks/critic-pass-llm-evaluator.md` NFR line ~340).

The dollar delta is negligible ($3.60/mo). The latency delta is not — a mismatch already adds a Stage 1 + Stage 2 re-compile (~5-10s per spec), and 1-1.5s of that back is meaningful for the p95 first-action NFR.

### Decision

**Chosen**: **Option B** — pass `critic_feedback` as a HumanMessage in a 2-turn conversation.

**Rationale**: The latency saving (~1.2-1.6s per retry) matters for the 30s first-action NFR under one-retry conditions, and Stage 1 is trivially convertible from a 1-message SystemMessage invocation to a 2-message SystemMessage + HumanMessage invocation without touching `BDD_NORMALIZER_PROMPT`. Option A also risks a subtle change in Sonnet behavior (appending mid-prompt structured blocks can shift attention weights); keeping the system prompt frozen isolates the retry signal cleanly into a user turn where the model treats it as retry feedback, not as part of its instructions.

**Implementation guidance**:

Modify `backend/engine/ac_parser.py::_stage_1_normalize` (currently lines 333-433):

- Keep `system_prompt = BDD_NORMALIZER_PROMPT.format(...)` byte-identical across retries.
- The existing `pre_parse_guidance` append at lines 378-386 stays as-is (that path is a first-call human context, not a retry).
- Add a new parameter `critic_feedback: dict | None = None` to `_stage_1_normalize`.
- When `critic_feedback` is non-None, build a HumanMessage:
  ```python
  messages = [SystemMessage(content=system_prompt)]
  if critic_feedback:
      messages.append(HumanMessage(content=(
          f"A previous compilation of this AC was rejected by the critic. "
          f"Regenerate the BDD scenario addressing these issues:\n"
          f"reason_codes: {critic_feedback['reason_codes']}\n"
          f"guidance: {critic_feedback['guidance']}"
      )))
  ```
- `ac_parser_node` (line 855) passes `state.get("critic_feedback")` down to `_stage_1_normalize`.
- Bedrock implicit caching then hits on the frozen system prompt across the initial call + all retries.

Note: `feedback_summary` (Q1's peer field) IS the `guidance` string. No new prompt template file needed.

---

## Q3: Retry counter placement

### Options

- **Option A**: `critic_result.retry_count` — scoped per-run (initialized 0, incremented by the critic before writing state). Simpler.
- **Option B**: A separate persistent `critic_retries_total` field on VQAState that accumulates.

### Evidence from codebase

- `systemPatterns.md` line 67: "Fail-Fast Loops: Circuit breakers on `verifier_not_yet_count` and `retry_count` prevent infinite loops" — these are per-run counters, not persistent aggregates.
- The Failure Diary pattern (systemPatterns.md Guiding Principle) is **per-locator per-run** — no cross-run accumulation.
- `backend/engine/state.py:584-608` — every retry-like counter in `VQAState` (`planner_iteration`, `max_planner_iterations`, `ac_step_index`) is per-run and reset when the graph is invoked fresh.
- The spec (`critic-pass-llm-evaluator.md` AC-VERIFY-5) already stipulates `retry_count` is a field on `critic_result` (`"retry_count is an integer in range 0-2"`).
- There is no cross-run persistence layer at the LangGraph state level in this codebase — cross-run analytics live in `backend/engine/metrics.py` / `run_metrics`, not in `VQAState`.

### Trade-off

- A: 1 field on `CriticVerdict`, incremented in `critic_node` before writing state, aligns with every other retry counter in the codebase.
- B: A second field on `VQAState` with unclear semantics (across-what?) — there's only one graph run per API call, so "across multiple mismatch cycles" is exactly what `retry_count` already tracks within a single run. If we need cross-run aggregation later, `backend/engine/metrics.py` is the correct home, not `VQAState`.

### Decision

**Chosen**: **Option A** — `retry_count` lives on `CriticVerdict` (per-run).

**Rationale**: Option B is a solution to a problem that doesn't exist — there is no "runaway across cycles" case beyond what `retry_count ∈ [0, 2]` already caps. Cross-run trend analysis (if ever needed) belongs in the run-metrics telemetry layer, not `VQAState`. Option A matches every existing retry counter in the codebase (`retry_count`, `planner_iteration`, `verifier_not_yet_count`).

**Implementation guidance**:

- Already correct in the schema from Q1: `retry_count: int = Field(default=0, ge=0, le=2)`.
- `critic_node` reads `previous = state.get("critic_result") or {}`, computes `next_retry = previous.get("retry_count", 0) + 1` on a mismatch that will be routed back to `ac_parser`, and writes `retry_count=next_retry` into the returned `critic_result` **only on mismatch** (pass verdicts leave `retry_count` unchanged since they don't cause a retry).
- `route_after_critic` reads `critic_result.get("retry_count", 0)`: on `verdict == "mismatch"` and `retry_count < 2` route to `ac_parser`; on `retry_count >= 2` route to `setup_role` (AC-VERIFY-5).
- Emit `critic_retries_total` as a **run-metrics** field only — computed at reporter-time by counting distinct `critic_verdicts` list entries (see AC-INTEGRATION-1); this does not require a `VQAState` field.

---

## Q4: Pipeline placement precision

### Options

- **Option A** (planned): `ac_parser → critic → setup_role`. Cheapest — no login work before the critic fires.
- **Option B**: `ac_parser → setup_role → login → critic → planner`. More expensive per-run (login runs before critic can reject) but critic gets `RoleContext.role_name` for `persona_mismatch` validation.
- **Option C (hybrid)**: Position A but *drop* `persona_mismatch` from the reason code enum (or push persona checks to the existing verifier).

### Evidence from codebase

- `backend/api/routes.py:526` — `_role = initial_state.get("role_queue", ["account_executive"])[0]` — the intended role_key is populated in initial state **before graph execution starts**. So even in position A, the critic has access to `state["role_queue"][0]`, which is the same role_key that `setup_role_node` will pop.
- `backend/engine/roles.py:238-600` — `ROLE_REGISTRY` maps role_key → `RoleContext` with `role_name` (human string). The critic can look up `role_name` from the initial `role_queue` via `ROLE_REGISTRY[state["role_queue"][0]]["role_name"]` **without** running `setup_role_node` or `login_node`.
- `backend/engine/state.py:302-303` — `RoleContext.role_name` and `role_key` are peer fields; role_name is derivable from role_key at any time via the registry.
- `backend/engine/schemas.py:260-268` — `StructuredACStep.target_persona` is the free-text persona string from the raw AC (e.g., "Demo Prod dir"). This is the field the critic would compare against the initial role.
- `backend/engine/graph.py:1450` — existing `graph.add_edge("ac_parser", "setup_role")` is the precise edge to replace.
- `setup_role_node` (`graph.py:479-628`) pops from `role_queue` and loads credentials; it does NOT run the browser. `login_node` (`graph.py:1451`) is what actually costs 5-10s.

### Trade-off

The concern that motivated Option B (need `RoleContext` for persona validation) is **false as stated**: `role_key` and `role_name` are available in initial state from `role_queue[0]` and `ROLE_REGISTRY` lookup — no login or `setup_role_node` execution needed.

- A: Zero wasted login time on mismatch. Full 5-reason-code coverage including `persona_mismatch`.
- B: 5-10s of wasted login/role setup per mismatch retry, in exchange for **nothing** the critic couldn't get in position A via `ROLE_REGISTRY`.
- C: Would drop a valuable reason code for no gain.

### Decision

**Chosen**: **Option A** (planned pipeline placement, unmodified).

**Rationale**: The premise that Option B is required for `persona_mismatch` doesn't hold — `role_key` and `role_name` are already in initial state via `role_queue[0]` + `ROLE_REGISTRY` lookup at position A. Option B pays 5-10s of login latency per mismatch for information the critic already has. Option C throws away a valuable reason code for no reason.

**Implementation guidance**:

- `backend/engine/graph.py` line 1450: replace `graph.add_edge("ac_parser", "setup_role")` with `graph.add_edge("ac_parser", "critic")` + `graph.add_conditional_edges("critic", route_after_critic, {"setup_role": "setup_role", "ac_parser": "ac_parser"})`. Exactly as the plan specified.
- Keep ALL 5 reason codes in the `CriticVerdict.reason_codes` enum.
- In `critic_node`, derive the expected persona for the prompt:
  ```python
  role_key = (state.get("role_queue") or ["account_executive"])[0]
  role_name = ROLE_REGISTRY.get(role_key, {}).get("role_name", role_key)
  ```
  and pass `role_name` into the Haiku prompt as the "expected persona" for `persona_mismatch` comparison against `TestPlan.steps[*].target_persona` and the raw AC text.
- Static Playwright runs (`execution_engine="static"`) must still bypass the critic — either via a `route_after_ac_parser` conditional check, or by adding the same guard the plan's Phase 2 mentions.

---

## Summary of decisions

| Question | Decision | Impact on plan |
|---|---|---|
| Q1: reason_codes shape | **Option A** (flat `Literal[...]`) + peer `feedback_summary: str` field | Phase 1 schema: `CriticVerdict` gets a `feedback_summary` field alongside `reason_codes`. AC-VERIFY-2 unchanged (still validates 5-value enum). AC-VERIFY-4's `critic_feedback["guidance"]` is populated from `feedback_summary`. |
| Q2: feedback grammar | **Option B** (HumanMessage in a 2-turn conversation) | Phase 2: `_stage_1_normalize` gains a `critic_feedback` parameter (`ac_parser.py:333`); when non-None, append a HumanMessage after the SystemMessage. `BDD_NORMALIZER_PROMPT` template file is **unchanged**. Saves ~1.2-1.6s per retry via Bedrock implicit cache-hit. |
| Q3: retry counter | **Option A** (`critic_result.retry_count`, per-run) | No plan changes. Already reflected in AC-VERIFY-2 / AC-VERIFY-5. No `VQAState.critic_retries_total` field. |
| Q4: pipeline placement | **Option A** (planned: `ac_parser → critic → setup_role`) | No plan changes. Keep all 5 reason codes. `critic_node` looks up `role_name` from `ROLE_REGISTRY[state["role_queue"][0]]` for the persona check — no login needed. |

## Effect on Implementation Roadmap

- **Phase 1 (`backend/engine/schemas.py`)**: Add `feedback_summary: str` field to `CriticVerdict`. Add `retry_count` and `critic_skipped` as already specified.
- **Phase 1 (`backend/engine/critic_node.py`)**: When building the Haiku prompt, include `expected_role_name` derived from `ROLE_REGISTRY[state["role_queue"][0]]["role_name"]` so the model can flag `persona_mismatch` in position A.
- **Phase 2 (`backend/engine/ac_parser.py`)**: The plan's line "inject as new `<critic_feedback>` block ... into BDD normalizer prompt" changes to: add `critic_feedback: dict | None = None` parameter to `_stage_1_normalize` (line 333); when non-None, append a HumanMessage after `SystemMessage(content=system_prompt)` at line 388. Do **not** mutate `BDD_NORMALIZER_PROMPT` or `system_prompt`. Similarly do NOT mutate the Stage 2 system prompt — pass any Stage-1-relevant feedback into Stage 1's HumanMessage only.
- **Phase 3 (reporter)**: `_render_critic_pass_section()` renders `feedback_summary` as the human-readable rationale under the badge + reason codes.
- **Phase 3 (metrics)**: The `run_metrics.critic_retries_total` value (if surfaced anywhere) is derived at report-assembly time by counting distinct entries in `state["run_metrics"]["critic_verdicts"]`. No `VQAState` field.

## Validation Checklist

- [x] Meets all system requirements — 4 decisions ground the plan's 3 phases with concrete diffs
- [x] Respects technical constraints — no new dependencies; uses existing `instructor` / `ChatBedrockConverse` / `ROLE_REGISTRY`
- [x] Addresses non-functional requirements — Q2's cache-preserving decision protects the 30s first-action p95 NFR
- [x] Technically feasible — every referenced file/line exists on `feature/critic-pass-llm-evaluator`
- [x] Risks identified and acceptable (see below)
- [x] Complies with Guiding Principles in systemPatterns.md — Failure Diary (per-run counters), Config in Environment (no new hardcoded values), Programmatic Tier 1 (critic is pre-execution and doesn't compete with verifier)
- [x] Respects established patterns — flat `Literal` + peer explanation field (mirrors `VerifierVerdict` + `VerifierResult.evidence`)

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bedrock implicit cache miss on Q2 (e.g., if any callsite path mutates the system prompt) | Medium | Low ($3.60/mo max) | Add a debug log at Stage 1 recording input token count and `cache_read_input_tokens` from `response.response_metadata`; alert if cache-read ratio drops below 50% on retry runs. |
| `ROLE_REGISTRY` lookup misses on custom role_key (e.g., a fresh role added to `.env` but not the registry) | Low | Low | `ROLE_REGISTRY.get(role_key, {}).get("role_name", role_key)` falls back to the raw key — critic still functions, `persona_mismatch` may false-negative for this run only. |
| Haiku emits a `reason_code` outside the enum | Low | Medium (Pydantic ValidationError → AC-ERROR-1 synthetic-pass path) | Already handled by AC-ERROR-1 wrap; the try/except catches ValidationError alongside Bedrock errors. |
