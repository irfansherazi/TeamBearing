## Spike Card: Internal / Codebase
**Work slug**: vqa-success-factors   |   **Status**: COMPLETE
**run_id**: 20260716-13383c61b543
**framing_sha**: 13383c61b543
**approved_depth**: deep
**approved_lanes**: Academic/SOTA, OSS/Production, Practitioner Discourse, Official Docs, Internal/Codebase
**MCP used**: n/a (local-only lane)
**mcp_servers_available**: none
**fallback_used**: no
**Sources consulted**: 12 (6 source files read in full, 4 partially, 2 log/benchmark datasets sampled)

---

### Findings

| Source | Type | Evidence Grade | Key Finding | Implications |
|--------|------|----------------|-------------|--------------|
| `backend/engine/ac_quality_gate.py:19-29` | code | A | AC quality gate scores 5 dimensions (0–2 each, max 10). Grades: GOOD 7–10, FAIR 4–6, POOR 0–3. POOR triggers hard reject; FAIR triggers HITL guardrail. | Gate is rule-based (zero LLM cost). Specificity keyword list is vSuite/PrimeNG-specific — may give inflated scores to ACs that name known component strings but are still semantically ambiguous. |
| `backend/engine/ac_parser.py:1117-1145` | code | A | POOR-grade ACs are hard-rejected: `parse_quality="rejected"` returned, run does not proceed to BDD Stage 1. FAIR-grade ACs pause on an `asyncio.Event` awaiting operator guidance before proceeding. | The docstring in `systemPatterns.md` (grade D) said POOR "does not block the run" — this is **outdated**. Actual code hard-blocks. This discrepancy is a TRAP candidate. |
| `backend/engine/ac_enricher.py:696` | code | A | For any AC scoring below GOOD (< 7), `enrich_ac_text()` applies LLM-driven repair before Stage 1 BDD normalization. | LLM repair path adds latency and cost on every FAIR-graded run. Backend log shows one example: score 5→8 after repair for QA-59 (`.logs/backend.log:2026-07-15`). |
| `backend/config.py:973-986` | code | A | `max_planner_iterations` default=500 (env-configurable, max 1000). LangGraph `recursion_limit` is set to 3000 in `routes.py:528` and `routes.py:1986`. Comment explains 6× multiplier: LangGraph counts node visits not iterations. | 3000 node-visits / 14+ nodes per loop cycle ≈ ~215 effective cycles at graph level — inconsistent with the 500-iteration evaluator check. The recursion_limit is a harder backstop than the evaluator guard for short tickets. |
| `backend/config.py:744-753` | code | A | `per_step_budget_max` default=30 (env-configurable, range 5–100). Fair-share formula: `min(30, remaining_iters / remaining_steps)`. When budget exhausted, run terminates with `failure_type="AGENT_STUCK"`. | A 30-step AC on a 20-step ticket gets `min(30, 480/20) = 24` iterations. For complex PrimeNG steps this fires frequently; this is likely a primary contributor to graceful termination. |
| `backend/config.py:759-778` | code | A | HITL failure thresholds (all env-configurable): `hitl_threshold_general=4`, `hitl_threshold_intercepted=2`, `hitl_threshold_strict_mode=3`. | INTERCEPTED threshold of 2 is aggressive — a PrimeNG overlay that fires twice before dismissal will trigger human takeover on step 2 of a complex form. |
| `backend/engine/evaluator.py:507-522` | code | A | Amnesic loop circuit breaker: 3 consecutive actions where URL and element count are both unchanged → routes to `human_takeover`. Resets on any state change or failure. | Detection uses URL + element count only — the documented TRAP in `systemPatterns.md` ("Visual Delta Trust Signal") explicitly warns this is a high false-positive signal. The amnesic breaker may trip on legitimate waits, animated transitions, or toast appearances that don't change element count. |
| `backend/engine/evaluator.py:754-785` | code | A | AC-level total action circuit breaker: default cap=20, configurable per-step via `test_plan.steps[i].max_actions`. Fires on `current_ac_step_action_count >= 20` with exemption for successful `done` actions. | Cap was raised from 15 (FEAT-104). The exemption prevents false trips on the finishing move — previously a BUG (TASK-071) where the agent was forced to HITL on its own successful completion step. |
| `backend/engine/evaluator.py:1015-1053` | code | A | Per-locator circuit breaker: 3 identical `strategy:role:name` failures → routes to `debugger` node (first time) or `human_takeover` (if already debugger-attempted). Sort actions get a separate 5-failure cap. | Two-stage escalation (debugger then HITL) adds a recovery hop before human intervention — but debugger path adds node visits that consume recursion budget. |
| `backend/engine/verifier.py:2057-2118` | code | A | LLM-path verifier NOT_YET caps: satisfiability check at `total_not_yet >= 3`; SKIP if goal absent from ARIA tree; hard FAILED at `total_not_yet >= 6`. Programmatic-path caps are stricter: FAILED at `total_not_yet >= 4`, escalate at `not_yet_count >= 2`. | LLM-path and programmatic-path caps are **asymmetric** (6 vs. 4). A step using programmatic checks escalates faster. The dual-counter system (`verifier_not_yet_count` per-cycle + `verifier_total_not_yet_count` cumulative) is correct in principle but adds state complexity. |
| `backend/engine/graph.py:1216-1422` | code | A | `build_graph()` creates 14 nodes (confirmed in compile log: "14 nodes incl. verifier + human_takeover + debugger + switch_actor_mid_run + persona_switch + ghost_login"). The inner execution loop is planner → executor → evaluator → verifier (4 nodes). | The systemPatterns.md "Compounding Pipeline Depth Anti-Pattern" names ≤2 nodes as the target; the current graph has 4 nodes per execution cycle. The anti-pattern description exists in docs but the implementation has NOT been refactored — this is a confirmed structural mismatch. |
| `.agent-logs/benchmark_report.json` | log | A | Golden 10 benchmark: 10/10 execution_success=false, all quality_score=0, all coverage=0.0. Parser succeeded on all 10. | This benchmark result (0/10 execution) appears to be a stale artifact from before the current execution engine — all `step_results` arrays are empty (`[]`), suggesting this was run without a live browser/Bedrock. Not a current production reliability signal. |
| `.logs/prompts/` directory sample (3368 files, 127 unique runs) | log | B | 60/127 runs (47%) contain at least one circuit-breaker or verifier-hard-cap event in their prompt context window. 203/3368 individual prompt files (6%) carry circuit-breaker/hard-cap evidence. Top 10 affected runs range from 11 to 46 circuit events per run. | Circuit-breaker/verifier-hard-cap is NOT rare — nearly half of all recorded runs hit at least one. The top-firing run (`run-400e73c2`, 134 total prompt iterations) had 46 CIRCUIT_BREAKER_TRIPPED entries — indicating a systematic stuck-agent scenario on that ticket. |
| `.logs/backend.log:2026-07-15` | log | A | One live run of QA-59: initial AC score 5/10 (fair, 14 steps, 43 warnings); after LLM repair 8/10 (good, 6 steps, 9 warnings). Run initiated human_takeover registration but no circuit-breaker fires logged. | Repair compressed 14 raw AC steps into 6 BDD steps — a 57% reduction — and raised the quality score 3 points. This is the only live quality gate log entry available. |
| `backend/engine/verifier.py:1-61` | code | A | Two-tier verification: Tier 1 programmatic (Playwright DOM: `url_check`, `element_visible`, `element_hidden`, `element_state`, `toast_message`) with `wait_for(timeout=2000ms)`; Tier 2 LLM (Claude Haiku) as fallback or when `visual_check` type present or no `selector_hint`. | 2000ms timeout on DOM checks is tight for Angular/PrimeNG animations (documented as 150–400ms typical). Tier 1 NOT_YET at count >= 2 escalates to evaluator (not planner) — this is a routing asymmetry: programmatic failures escalate faster than LLM failures. |

---

### TRAP Candidates

**TC-1 — systemPatterns.md POOR-grade claim is outdated (documentation drift)**
`systemPatterns.md:173` states POOR-graded ACs "log a warning but do not block the run." The actual code (`ac_parser.py:1117-1145`) hard-rejects POOR-grade ACs and returns `parse_quality="rejected"`. Any external recommendation that assumes POOR-grade runs proceed to execution would be designing against a false premise. The docs must be corrected before external research is applied.

**TC-2 — 4-node execution loop is a confirmed anti-pattern that has not been refactored**
`systemPatterns.md:288-294` documents the "Compounding Pipeline Depth Anti-Pattern" naming ≤2 nodes as the target, but `graph.py:1216` compiles 14 nodes with a 4-node inner loop (planner → executor → evaluator → verifier). External research recommendations that assume a 2-node loop, or that propose further node additions, will compound the reliability problem. This is the highest-priority structural TRAP candidate.

**TC-3 — Amnesic loop circuit breaker uses a known-unreliable signal**
`evaluator.py:478-479` checks URL equality AND element_count equality to detect amnesic loops. `systemPatterns.md:259-264` explicitly documents the "Visual Delta Trust Signal Anti-Pattern" warning that DOM element count changes are high false-positive signals. The amnesic breaker may fire legitimately on stuck agents, but may also fire spuriously on PrimeNG animation renders, toast notifications, or spinner appearances — generating unnecessary HITL events.

**TC-4 — Verifier programmatic-vs-LLM cap asymmetry**
Programmatic NOT_YET fires FAILED at total >= 4; LLM NOT_YET fires FAILED at total >= 6. This means the same AC step with the same observable outcome gets different retry budgets depending on whether the AC parser emitted a `selector_hint`. Steps without hints use the LLM path (more retries, more cost, more latency); steps with hints use the programmatic path (faster failure, less cost). The asymmetry is not documented as intentional.

**TC-5 — `goal_satisfiable_check` is a keyword heuristic with a known false-negative path**
`verifier.py:1463-1489` implements `goal_satisfiable_check` as an ARIA snapshot keyword search: if no goal keywords are found in the ARIA tree, the step is marked unsatisfiable and SKIPPED. The function defaults to `True` (satisfiable) on any exception and on short keyword lists. For multi-word AC steps with common short words (e.g. "sort by client"), all keywords may be 3 chars or fewer and are filtered — yielding a false `True` (satisfiable) verdict. The step then runs to the hard cap instead of being cleanly skipped.

**TC-6 — Quality gate keyword list is vSuite-specific, not generalizable**
`ac_quality_gate.py:102-136` (`_SPECIFIC_COMPONENT_PATTERNS`) scores specificity=2 for ACs containing "p-select", "p-dropdown", PrimeNG component strings, or vSuite-specific UI terms like "submit all", "compact view". ACs that name valid non-PrimeNG components would score 0 on specificity. Any external research recommending a generalizable quality-gate threshold (e.g. "score >= 7 = safe to execute") is directly applicable here but must account for the vSuite-biased vocabulary when interpreting score distributions.

---

### Open Questions

**OQ-1 — What is the empirical per-run circuit-breaker firing frequency?**
The prompt-log sample (47% of runs contain at least one CB event) conflates all CB types. It is unknown what fraction of runs fire the amnesic breaker vs. the locator breaker vs. the AC-level cap vs. the verifier hard cap. Each requires a different intervention. The backend.log only contains 5 lines of relevant data. No structured CB telemetry table exists.

**OQ-2 — What is the verifier false-positive rate?**
No logged FP rate is available. The `StepTable` "False Positive" button exists (`systemPatterns.md:77`) and writes corrections to the verifier correction loop — but no aggregated FP rate log was found. The FP rate is the most critical unknown for evaluating whether Tier 2 LLM verification is improving or degrading accuracy.

**OQ-3 — Is the FAIR guardrail (asyncio.Event pause) blocking runs in production?**
The FAIR guardrail (`ac_parser.py:992-1034`) suspends execution pending operator input when AC scores 4–6. It is unknown how often this fires, how long operators take to respond, and whether timeout/retry logic exists if the operator never responds. No log evidence was found of the FAIR guardrail event being triggered in the available `.logs/backend.log`.

**OQ-4 — What is the actual distribution of AC quality scores across production tickets?**
Only one data point exists from the backend log (QA-59: initial 5/10, repaired 8/10). The benchmark report has quality_score=0 for all entries but step_results=[] — those zeroes are from a parser-only benchmark run without execution, not from the live quality gate. The actual distribution is unknown.

**OQ-5 — Does the LLM-driven AC repair in ac_enricher.py reliably improve execution success?**
The single observed case (QA-59: 5→8 score, 14→6 steps) shows repair working as intended. No aggregate data exists on repair success rate, nor on whether repaired ACs have meaningfully higher execution success rates than unrepaired FAIR ACs that bypass the guardrail.

**OQ-6 — What is the relationship between ac_step_iteration_budget exhaustion and ticket complexity?**
The fair-share formula distributes remaining iterations equally across remaining steps. For a 10-step ticket at step 7 with 300 iterations remaining and 3 steps left: `min(30, 300/3) = 30`. For a 30-step ticket at step 25 with 50 iterations remaining and 5 steps left: `min(30, 10) = 10`. The budget drops sharply on long runs. It is unknown how often budget exhaustion occurs on long tickets vs. short ones.

---

### Existing Patterns

| Pattern | Location (file:line) | Relevance |
|---------|----------------------|-----------|
| Pydantic `Settings` with `Field(default=..., description=...)` for all circuit-breaker thresholds | `backend/config.py:744,759,973,1104` | All CB thresholds are env-configurable. External research recommending threshold changes can be applied without code changes. |
| `operator.add` reducer on `bug_log`, `execution_log`, `screenshots` in VQAState | `systemPatterns.md:87-88` (Grade D — documented) | Any new CB or verifier output should return a partial list not a replacement to avoid state corruption across nodes. |
| Two-stage AC parsing (Stage 1: BDD normalizer; Stage 2: JSON compiler) | `backend/engine/ac_parser.py` / `systemPatterns.md:89-94` | Research on prompt engineering for AC parsing must fit between these two stages. Stage 1 is the enrichable point; Stage 2 enforces structured output. |
| Failure diary (`ac_step_failure_diary`) limited to 5 entries | `backend/engine/evaluator.py:990-991` | External research recommending larger failure context windows would require increasing this cap — current truncation prevents context bloat at the cost of losing older failure context. |
| Model escalation at `retry_count >= auto_escalate_threshold (default=3)` | `backend/config.py:254-261` | Research on model escalation patterns can be applied to this threshold. Current default escalates from Haiku to Sonnet after 3 consecutive failures. |
| `HITL as Learning Signal` — every human takeover writes to `knowledge/human_guidance.md` | `systemPatterns.md:14` | Reducing HITL frequency trades off against the KB learning signal. Interventions that prevent legitimate HITL events also reduce the self-improvement feedback loop. |
| `Semantic Locators First` principle (`get_by_role`, `get_by_label`, `get_by_text`) | `systemPatterns.md:9` | Research recommending CSS-selector-based locators would contradict this documented principle. |
| Pre-caching `numpy` and `sklearn` in main entrypoints (Python 3.13 bug workaround) | `systemPatterns.md:19` | Any library recommendation that adds import-time dependencies must account for the early-import pre-caching requirement. |

---

### Compatibility Constraints

- **Python 3.12** (techContext.md). Async features (`asyncio.Event`, `async for`) are core to the HITL and FAIR guardrail patterns. Research recommending synchronous verification patterns requires async wrapping.
- **LangGraph 0.2+** with `StateGraph`. Adding or removing nodes changes the recursion budget calculation (`recursion_limit=3000` assumes current node count). A 2-node loop redesign (as recommended by the anti-pattern doc) would require a full graph rebuild, not a parameter change.
- **All state fields use `operator.add` reducers** for list fields. New circuit-breaker state fields must use the established reducer pattern or face state-append duplication across graph nodes.
- **Pydantic 2.7+** `BaseSettings` for config. All new thresholds must be added as `Field(default=..., ge=..., le=..., description=...)` entries — no hardcoded values allowed (12-Factor principle enforced in project rules).
- **vSuite/Angular/PrimeNG specificity** of the AC quality keyword lists (`ac_quality_gate.py:102-340`). Quality score thresholds validated against vSuite ACs may not transfer to other SPA targets without re-calibrating the keyword vocabulary.
- **HITL as Learning Signal** (systemPatterns.md principle). Interventions that reduce HITL frequency must not silently break the KB feedback loop — `human_guidance.md` writes must be preserved even if HITL routing changes.
- **`goal_satisfiable_check` keyword filter strips words ≤ 3 chars** (`verifier.py:1480`). AC steps with short but meaningful verbs ("set", "tab", "row") will produce empty keyword lists and default to `satisfiable=True`, bypassing the skip safety valve.
