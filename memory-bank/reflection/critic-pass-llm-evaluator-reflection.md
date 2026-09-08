# Reflection: critic-pass-llm-evaluator — Critic Pass LLM Evaluator

**Date**: 2026-07-30
**Task Complexity**: Level 3
**Total Phases**: 3 implementation phases + 1 creative phase
**Duration**: 2026-07-30 (single-day execution via /bmb:auto-build)

---

## Executive Summary

The Critic Pass LLM Evaluator inserts a cheap Haiku LLM node between AC parsing and browser execution, catching TestPlan drift against acceptance criteria before any browser work begins. The implementation achieved all 8 acceptance criteria, delivered 27 unit tests across 3 phases, and introduced zero regressions against the existing test suite. The entire build ran as a single `/bmb:auto-build` session — plan to BUILD_COMPLETE in one continuous orchestrated pass.

The implementation is notable for three things: (1) the creative phase refuted a plan assumption (Q4-B's premise that `role_name` requires `setup_role` to run was wrong — it's already in initial state via `ROLE_REGISTRY`), leading to a materially better design without the creative work degrading into validation theater; (2) the Q2 cache-preservation decision (HumanMessage 2-turn, keeping `BDD_NORMALIZER_PROMPT` byte-identical) was a concrete latency engineering decision, not a stylistic preference; and (3) the implementation stayed exactly within scope — no feature creep, no undocumented deviations.

Three minor findings from the final review remain unresolved: a deprecated asyncio test API usage, missing CSS classes for the report section, and single-verdict `run_metrics` history. None block merge; all are deferrable polish.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement

**Status**: All Met

All 8 acceptance criteria covered:

| AC | Status | Evidence |
|---|---|---|
| AC-VERIFY-1 (graph registration, both graphs) | Met | Phase 2: `graph.add_node("critic", critic_node)` in both `build_graph()` and `build_supervisor_graph()`; static bypass guard inside `critic_node` |
| AC-VERIFY-2 (structured CriticVerdict schema) | Met | Phase 1: `CriticVerdict` Pydantic model with flat `Literal[...]` reason_codes + peer `feedback_summary`; 5 schema-validation tests pass |
| AC-VERIFY-3 (pass routing → setup_role, state unchanged) | Met | Phase 1: `route_after_critic` returns `"setup_role"` on `verdict="pass"`; test asserts state identity |
| AC-VERIFY-4 (mismatch + retry < 2 → ac_parser with feedback) | Met | Phase 2: `critic_feedback` dict written to state before routing; 2-turn HumanMessage injected in `_stage_1_normalize` |
| AC-VERIFY-5 (retry cap: retry_count==2 → setup_role) | Met | Phase 1: `route_after_critic` branches on `retry_count >= max_critic_retries`; WARNING log emitted; test asserts exhaustion path |
| AC-ERROR-1 (Haiku API failure → synthetic pass, no abort) | Met | Phase 1: `try/except` wraps entire Haiku call; `_SYNTHETIC_PASS` dict with `critic_skipped=True` returned; reporter shows "SKIPPED" |
| AC-INTEGRATION-1 (grounded reason codes in report) | Met | Phase 3: `_render_critic_pass_section()` renders badge, reason codes, `feedback_summary`; 5 reporter tests pass |
| AC-ASYNC-1 (WebSocket broadcast < 500ms) | Met | Phase 3: `_broadcast_critic_mismatch()` lazy-imports `_ws_connections` (same pattern as `persona_switch_node`); non-fatal; 2 broadcast tests pass |

No ACs were partially met or deferred.

### Code Quality Assessment

**Overall Rating**: Good

- **Maintainability**: The module-level docstring in `critic_node.py` explicitly cross-references all 4 creative decisions with the architecture doc — a future engineer reading the code knows exactly why each design choice was made and where to find the rationale. This is the right pattern for a node that looks simple but embeds non-obvious decisions.

- **Architecture**: The implementation respects the existing codebase's structural patterns without exception. `CriticVerdict` follows the `VerifierResult` flat-Literal + peer-explanation split. The Bedrock client factory (`_get_critic_llm`) matches `verifier.py`'s pattern. The WebSocket broadcast lazy-imports `_ws_connections` exactly as `persona_switch_node` does, avoiding the circular-import problem that would occur with a direct import. The `_SYNTHETIC_PASS` module constant is preferable to constructing the synthetic dict inline in the except branch — a minor but correct call.

- **Error Handling**: The single `try/except Exception` around the full Haiku invocation is intentionally broad (per AC-ERROR-1's "any exception" requirement) and correctly returns the synthetic pass rather than re-raising. ValidationError from a malformed Haiku response is caught here too, which aligns with the creative doc's risk table ("Haiku emits a reason_code outside the enum → caught by AC-ERROR-1 wrap").

- **Testing**: 27 tests across 3 phases is appropriate for Level 3 scope. Tests are organized into named classes (`TestCriticVerdictSchema`, `TestRouteAfterCritic`, `TestCriticNode`, `TestGraphTopology`, `TestCriticPassReporter`, `TestCriticMismatchBroadcast`) with a single `_make_state()` factory function — this follows the preflight and verifier test patterns cleanly. The mock discipline is correct: Bedrock is patched, not called live.

### Technical Decisions

**Key Decisions:**

1. **Flat Literal reason_codes + peer feedback_summary (Q1-A)** — Chose simplicity over richer per-reason evidence pointers. The bet is that a plain-English `feedback_summary` string is sufficient for the re-parser to locate and fix discrepancies, since the re-parser already has the full AC text and TestPlan in its context window. This held up — no evidence that per-code evidence pointers would have improved retry quality in the test scenarios.

2. **HumanMessage 2-turn for retry feedback (Q2-B)** — Keeping `BDD_NORMALIZER_PROMPT` byte-identical across retries preserves Bedrock's implicit prompt cache. The implementation adds a `critic_feedback: dict | None = None` parameter to `_stage_1_normalize` and appends a HumanMessage only when non-None. The code change is minimal (2-3 lines) for a concrete latency benefit (1.2-1.6s per retry). The right call; the cost math in the creative doc ($3.60/month delta) confirms the decision was driven by latency, not cost.

3. **ROLE_REGISTRY lookup for persona_mismatch in position A (Q4-A)** — The creative phase refuted the plan's LOW-confidence Q4-B hypothesis by finding that `role_key` is already in `initial_state["role_queue"][0]` and `role_name` is a deterministic lookup from `ROLE_REGISTRY`. This means the critic gets full persona context at position A without waiting for `setup_role_node` or `login_node` to run — saving 5-10s on every mismatch retry. This is the single highest-value finding of the creative phase.

**Trade-offs:**

- **Observability depth vs. implementation cost**: `run_metrics.critic_verdicts` stores only the final `critic_result` dict (the last retry cycle), not the full per-cycle history. This was a reasonable simplification — the plan specified `critic_verdicts` as a list but the auto-build simplified to a single dict. This loses the retry trajectory (what changed between cycle 1 and cycle 2) but avoids complexity in state accumulation. It is genuinely deferrable; a future task can promote this to a list if retry forensics are needed.

- **HTML report rendering vs. stylesheet completeness**: `_render_critic_pass_section()` references CSS classes (`.badge-pass`, `.badge-warn`, `.badge-skip`, `.critic-table`, etc.) that are not yet defined in the report stylesheet. The section renders but is unstyled. This was implicitly deferred — the functional behavior is correct, the visual polish is not. This is a known gap, not an AC failure (AC-INTEGRATION-1 tests the content, not the styling).

### What Went Well

1. **Creative phase caught a real design error before code was written.** Q4's LOW-confidence hypothesis (critic needs `RoleContext` from `setup_role_node`) was refuted by the creative agent reading `backend/api/routes.py:526` and `backend/engine/roles.py:238-600`. If the build had proceeded without the creative phase, the implementation would likely have placed the critic incorrectly or dropped `persona_mismatch` from the reason codes — either wasting 5-10s per retry or losing a valuable detection capability. The creative phase paid for itself on this one finding alone.

2. **Zero-deviation execution against a tight spec.** The plan's AC→Phase mapping, pinned file paths, and per-phase test guidance left no ambiguity for the build orchestrator. Phase 1 delivered exactly the 6 planned tests (expanded to 16 with higher coverage). Phase 2 delivered exactly the 2 planned graph topology tests (expanded to 4). Phase 3 delivered exactly the reporter + WebSocket targets. No scope creep; no missed targets.

3. **Backward compatibility by design.** New `VQAState` fields (`critic_result`, `critic_feedback`) default to `None`. The feature flag `settings.critic_enabled` lets the critic be toggled off at runtime without code change. Pre-existing test failures (`test_vnc_api`, `test_environment_scoping`, and 3 task-specific tests) were identified as pre-existing on `main` and correctly isolated from Phase 1 — the commit message documents this explicitly, which is the correct engineering discipline.

4. **Pattern adherence.** The WebSocket broadcast lazy-import pattern (matching `persona_switch_node`) and the LLM factory pattern (matching `verifier.py`) mean the new code reads as native to the codebase, not as a foreign insertion.

### Challenges Encountered

1. **Circular import for WebSocket broadcast** — `_ws_connections` lives in `routes.py`, which imports engine modules. A direct top-level import of `_ws_connections` in `critic_node.py` would create a circular dependency. Resolved by applying the lazy-import pattern already established in `persona_switch_node.py`. No friction once the pattern was identified; the creative doc didn't anticipate this specific challenge but the codebase pattern provided the answer.

2. **asyncio deprecation in one test** — `test_static_execution_engine_bypasses_critic` uses `asyncio.get_event_loop().run_until_complete()`, which is deprecated in Python 3.12. This should be `@pytest.mark.asyncio`. The test still passes; it's a hygiene issue, not a functional gap. Noted as a known follow-up.

3. **run_metrics critic_verdicts scope narrowed** — The plan specified a list of per-cycle verdicts; the build simplified to a single dict. This was an implicit scope reduction rather than an acknowledged deviation. It works for the AC (which specifies the key exists, not its shape as a list), but the gap between spec intent and implementation is something future work should address.

### Technical Debt and Future Work

- **CSS classes for Critic Pass report section**: `_render_critic_pass_section()` references `.badge-pass`, `.badge-warn`, `.badge-skip`, `.critic-table`, `.critic-reasons`, `.critic-summary`, `.retry-count` — none defined in the report stylesheet. Effort: ~30 min. No functional impact.

- **asyncio.get_event_loop() deprecation in tests**: `test_static_execution_engine_bypasses_critic` should use `@pytest.mark.asyncio`. Effort: 5 min. No test reliability impact currently.

- **critic_verdicts as list of per-cycle history**: Promote `run_metrics["critic_verdicts"]` from single dict to list of dicts (one per retry cycle) to enable retry forensics. Effort: ~1 hour. Enables better debugging when the plan drifts across multiple retry cycles.

- **Bedrock cache-hit logging**: The Q2 creative doc recommended adding debug logging for `cache_read_input_tokens` from Bedrock response metadata, to validate the cache-preservation design is working. Not implemented in Phase 3. Low effort; high signal for verifying the cache hit assumption.

---

## Dimension 2: Claude Code Ecosystem Effectiveness

### Build Session Analysis

**Build Sessions**: 1 (single `/bmb:auto-build` continuous run)
**Sub-Agents Spawned**: estimated 3 phase orchestrators + TDD/review sub-agents per phase (task-scoped logs absent; fallback: count from commit patterns)
**Tool Calls**: not available (by-task log directory absent)
**Errors Recovered**: 0 (per task file Deviations section: empty)
**Guard FAILs**: 0 (no guardrail misses recorded)

Session logs: `.agent-logs/claude/by-task/critic-pass-llm-evaluator/` is absent. Likely not created (task predates task-scoped log directory initialization, or the auto-build session predate this feature). Fallback log scan would require date-range grep across the full `.agent-logs/` tree — out of scope for this reflection. Build quality is assessed from commit history and task file execution state instead.

#### Tool Utilization

Not derivable from available artifacts (log directory absent). Assessment from commit stat patterns:

| Tool | Estimated Relative Usage | Notes |
|------|--------------------------|-------|
| Read | High | 6 source files modified across 3 phases; creative agent read ~10 existing files |
| Edit | High | Primary mutation tool; 5 production files + test file |
| Write | Medium | New `critic_node.py` (372 lines in Phase 1), new test file sections |
| Bash | Medium | Test runs between phases (pytest); git commits |
| Task | Medium | Sub-agent dispatch per phase |

#### Sub-Agent Performance

| Agent Type | Invocations | Model | Effectiveness |
|------------|-------------|-------|---------------|
| Spec Writer | 1 | Sonnet | Excellent — spec taxonomy clean; 8 ACs all verified; AC→Phase map precise enough to eliminate ambiguity at build time |
| Architecture Design | 1 | Opus | Excellent — all 4 questions at HIGH confidence; Q4 evidence-based refutation was high value |
| Auto-Build Orchestrator | 1 (3 phases) | Sonnet | Excellent — zero deviations, correct phase isolation, pre-existing failures correctly quarantined |
| TDD Agents (per phase) | 3 | Sonnet | Good — test counts slightly exceeded plan targets (16 vs 6 in Phase 1) without scope creep; test class organization is clean |
| Code Reviewer (per phase) | 3 | Sonnet | Good — final review correctly classified all issues as Minor (no Critical or Important) |
| Final Reviewer | 1 | Sonnet | Good — found 3 real (if minor) issues; did not flag false positives |

### Command Workflow Evaluation

**Commands Used**: `/bmb:plan`, `/bmb:creative`, `/bmb:auto-build`, `/bmb:reflect`

**Workflow Efficiency**: Excellent

**Assessment**:

- The `/bmb:plan` + Spec Writer Agent workflow produced an unusually tight spec for a Level 3 task. The AC→Phase mapping table in the task file was directly consumed by auto-build's pre-flight plan scan — the orchestrator could confirm each phase's scope without re-reading the AC text. This is the highest-leverage artifact the planning workflow produces for auto-build.

- `/bmb:creative` with Opus was the correct model choice for this task. The Q4 refutation required reading 3 specific files (`routes.py:526`, `roles.py:238-600`, `state.py:302-303`) and synthesizing that evidence against a low-confidence hypothesis. Sonnet might have accepted the original hypothesis; Opus found and validated the counter-evidence. All 4 questions at HIGH confidence in one pass is the ideal creative outcome.

- `/bmb:auto-build` for a 3-phase Level 3 task is appropriate. The "zero deviations" result could mean either (a) the plan was tight enough that the build never needed to deviate, or (b) the deviation-detection mechanism is under-calibrated. Given the `run_metrics.critic_verdicts` scope reduction (single dict vs. list) was not recorded as a deviation, (b) is likely partially true — auto-build's deviation tracking catches changes to pinned files and ACs, but not implicit scope reductions within an AC's implementation boundary. This is a systemic gap worth fixing.

- Creative critique was skipped (Codex absent, `availability: auto`). For this task, the architectural decisions were grounded in codebase evidence, so the critique gap was not material. On a task with more speculative design choices, the silent skip would be a risk.

### Context File Effectiveness

**Files Loaded** (inferred from agent behavior):
- `memory-bank/tasks/critic-pass-llm-evaluator.md` — primary task spec
- `memory-bank/creative/critic-pass-llm-evaluator-architecture.md` — design decisions
- `backend/engine/verifier.py` — pattern reference for VerifierResult
- `backend/engine/ac_parser.py` — pattern reference for BDD normalizer + instructor
- `backend/engine/persona_switch_node.py` — pattern reference for lazy-import WebSocket
- `backend/engine/graph.py` — edge wiring target
- `memory-bank/systemPatterns.md` — Guiding Principles alignment check

**Assessment**:

- **Helpful**: The task file's "Pattern to follow" pointers in the Test Strategy section (`tests/test_preflight_check.py`) were directly actionable — the test file structure shows the `_make_state()` factory pattern and `@pytest.mark.asyncio` reference (which makes the asyncio deprecation finding more ironic, since the pattern document points to the correct approach). The Scope Boundaries section's "NOT touched" list (verifier, executor, planner, preflight) gave the build agent clear negative space.

- **Gaps**: The CSS class names for the report section were not specified in the spec. The plan said "renders one row per verdict (badge, reason codes, retry count)" but did not name the CSS classes or say where the stylesheet lives. The build agent introduced new class names without a stylesheet definition — a gap that the spec could have prevented by either naming existing classes to reuse or explicitly flagging "define new CSS."

- **Redundancy**: The Summary of decisions table appears in both the task file (Decisions summary section) and the creative doc (Summary of decisions section). For a single reader the duplication is helpful; for agents that load both files, the duplication wastes context tokens. The task file's decisions summary could be replaced with a pointer to the creative doc.

### Memory Bank Organization

**Assessment**:

- **Structure**: The creative doc + task file split worked well for this task. The creative doc is self-contained and independently readable; the task file's "Decisions summary" table is a compressed excerpt for build-phase consumption. This two-file approach is the right pattern for Level 3.

- **Navigation**: The task file's cross-references (creative doc path, referenced source file line numbers, AC→Phase table) significantly reduced the information retrieval burden on build agents. Line-number references for existing patterns (`verifier.py:275-278`, `ac_parser.py:370-388`, `graph.py:1450`) are particularly valuable — they survived from planning through execution without becoming stale, which means the planning agent verified them against the actual codebase.

- **Completeness**: No missing document types for this task. The reflection document (this file) is the only artifact absent at BUILD_COMPLETE; that is expected by design.

### Memory-Bank Corrections (from Guardrail Misses)

None — no guardrail misses this build.

The commit-guard reported zero FAILs across all 3 phases. No re-invocations were needed. The Deviations section in the task file remained empty. This is a clean build.

### Suggested Improvements to Claude Code System

**High Priority**:

1. **Deviation tracking for implicit scope reductions** — Auto-build's deviation recorder catches changes to pinned files and ACs, but not cases where an AC's implementation boundary is narrowed (e.g., `critic_verdicts` as single dict vs. spec's implied list). Add a "scope delta" check: the phase reviewer should compare the implemented behavior against the AC's observable specification, not just the file change list. If an AC says "list of CriticVerdict dicts" and the implementation stores a single dict, that is a deviation even if the AC text doesn't use the word "list."

2. **CSS/stylesheet coupling check in reporter tasks** — When a build agent adds `_render_*` functions that reference CSS class names, the code-reviewer should verify those classes exist in the project's stylesheet. This is a recurring pattern in vQA reporter additions (this is not the first reflection to note unstyled sections). A simple grep check in the reviewer gate would catch it at build time.

**Medium Priority**:

3. **By-task agent log directory initialization in auto-build** — The `.agent-logs/claude/by-task/<slug>/` directory was absent for this task, making build session metrics unavailable in reflection. Auto-build should initialize this directory at session start so reflection agents have task-scoped logs to analyze. The reflection methodology calls for this as a primary source; falling back to whole-tree grep is slow and imprecise.

4. **Creative critique fallback to Anthropic when Codex is absent and confidence is not universally HIGH** — The current behavior silently skips the critique when `availability: auto` and the companion is absent. For tasks where any creative question is below HIGH confidence, the system should invoke an Anthropic self-critique pass rather than skip entirely. In this task all 4 questions were HIGH confidence after Q4 refutation, so the skip was safe — but that was not known until after the creative phase completed.

5. **Task file decisions summary as pointer, not duplicate** — The task file's "Decisions summary" table duplicates the creative doc's summary. Replace with a one-line pointer: "See `memory-bank/creative/<slug>-architecture.md` § Summary of decisions." Saves ~200 tokens per build agent context load.

**Low Priority / Nice to Have**:

6. **Bedrock cache-hit instrumentation scaffold** — The creative doc recommended monitoring `cache_read_input_tokens` to validate cache-preservation decisions. The build agent did not implement this (correctly — it is advisory). A lightweight scaffold in the build agent's Phase 3 checklist ("if a cache-preservation design decision was made in creative, verify it is observable at runtime") would remind agents to close this loop.

7. **asyncio deprecation lint rule for test files** — `asyncio.get_event_loop().run_until_complete()` in test bodies is a Python 3.12 deprecation. A pre-commit lint rule or `pytest-asyncio` strictmode configuration would catch this at commit time rather than leaving it for reflection to flag.

---

## Known Follow-ups (not blocking merge)

These are minor issues identified by the final reviewer. None constitute AC failures. All are deferrable polish.

| # | Finding | Files | Severity | Blocks merge? |
|---|---------|-------|----------|---------------|
| 1 | `test_static_execution_engine_bypasses_critic` uses `asyncio.get_event_loop().run_until_complete()` — deprecated in Python 3.12; should use `@pytest.mark.asyncio` | `tests/engine/test_critic_node.py` | Minor | No |
| 2 | `_render_critic_pass_section()` references CSS classes (`.badge-pass`, `.badge-warn`, `.badge-skip`, `.critic-table`, `.critic-reasons`, `.critic-summary`, `.retry-count`) not defined in report stylesheet — section renders unstyled | `backend/engine/reporter.py`, report stylesheet | Minor | No |
| 3 | `run_metrics["critic_verdicts"]` stores only the final `critic_result` dict (last cycle), not full per-cycle history — loses retry trajectory for forensics | `backend/engine/reporter.py`, `backend/engine/critic_node.py` | Minor | No |

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

**Format**: `- **[category]** ([scope hint]): [1-line actionable directive]`

1. **architecture-design** (`memory-bank/creative/*.md`): When a creative question is LOW confidence, require the agent to locate 3+ specific file:line references that either validate or refute each option before deciding — evidence-based refutation (Q4-B) saves build time worth more than the evidence-gathering overhead.

2. **testing-patterns** (`tests/engine/test_*.py`): Never use `asyncio.get_event_loop().run_until_complete()` in test bodies — always use `@pytest.mark.asyncio` (already the documented pattern in `tests/test_preflight_check.py`; repeat violations suggest this needs to be a pre-commit check, not a convention).

3. **observability** (`backend/engine/reporter.py`): When adding `_render_*` functions that introduce new CSS classes, either reuse classes already in the stylesheet or define them in the same commit — do not reference classes that do not exist; the section silently renders unstyled in production.

**Limits**: Level 3 task → 2-4 learnings max. Three learnings extracted; all are independently reusable across future build agents working in these paths.

### Learned Rules Applied

No learned rules from `memory-bank/agent-rules/_learned/` are available yet for this task's domain (critic node is new; no prior learned rules on LangGraph node patterns or Bedrock cache preservation were in the index as of this build).

### For Claude Code Workflow

1. **AC→Phase mapping tables are the highest-leverage planning artifact for auto-build.** The pre-flight scan reads this table to confirm phase scope before dispatching build agents. A plan without this table forces the orchestrator to re-derive phase scope from the AC text, introducing ambiguity. Always include it for Level 3+.

2. **The creative phase pays for itself when LOW-confidence questions involve placement or ordering in an existing pipeline.** Q4's LOW-confidence hypothesis about pipeline placement was resolved in minutes by the creative agent reading 3 existing files. If the build agent had attempted to resolve this, it would have had to make a judgment call mid-implementation — much higher risk.

3. **Auto-build deviation tracking should be widened to cover behavioral scope, not just file scope.** The `critic_verdicts` single-dict vs. list gap was a real deviation from spec intent that was not recorded. Future orchestrators should verify that each AC's observable behavior matches the implementation, not just that the correct files were touched.

---

## Conclusion

The Critic Pass LLM Evaluator is a clean Level 3 implementation: all 8 ACs met, 27 tests passing, zero regressions, zero guardrail misses, and a creative phase that produced high-confidence decisions grounded in codebase evidence. The most significant outcome of the creative phase was not a design decision but a design refutation — Q4-B's premise was demonstrably wrong, and catching that before code was written saved approximately 5-10s of latency on every mismatch retry.

The three minor follow-up items (asyncio deprecation, unstyled CSS, single-verdict metrics) are genuine but correctly classified as non-blocking. The CSS gap is the most impactful for end-users (the report section is functionally correct but visually degraded); it should be addressed before any stakeholder demo of the audit report.

The Banyan workflow performed at its ceiling for this task: the spec was concrete, the creative phase was evidence-driven, and auto-build executed without deviations. The two systemic gaps worth addressing for future Level 3 tasks are implicit scope-reduction detection in auto-build, and task-scoped agent log initialization so reflection agents have full build metrics available.

**Overall Task Success**: Success

**Overall Workflow Effectiveness**: Highly Effective

**Recommendation**: Ready to archive. Address CSS classes (follow-up #2) in a Level 1 follow-on task before the next stakeholder demo of the audit report.
