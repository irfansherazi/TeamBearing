---
name: Creative-Phase Evidence-Anchoring & Phase Zero Discovery/Pinning
globs: ["memory-bank/tasks/*.md", "memory-bank/creative/*.md", "backend/**/*.py"]
paths: ["memory-bank/tasks/", "memory-bank/creative/", "backend/"]
topics: ["workflow", "planning", "level-2", "level-3", "level-4", "discovery-phase", "creative-validation", "evidence-based-refutation", "singleton-refactor", "backward-compat", "healing-task-patterns"]
priority: medium
auto_generated: true
derived_from: [FEAT-118-vqa-tier3-architectural-hardening, critic-pass-llm-evaluator, per-user-session-isolation, heal-playwright-tests-round4]
evidence_count: 4
last_validated: 2026-08-11
---

# Learned Rules: phase-zero-checkpoint

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **phase-zero-discovery-pinning-checkpoint** (`memory-bank/tasks/*.md`, Level 4 multi-phase builds): For Level 4 tasks with integration targets that reference external artifacts (replay directories, curated ticket samples, live-run baselines), include an explicit **Phase 0 "Discovery/Pinning" phase** (0 tests, no guard requirement) that runs BEFORE Phase 1. Phase 0 responsibilities: (1) verify artifact existence for every path the creative doc declares as "concrete", (2) pin every LOW/MEDIUM confidence CQ value into the task file's "Pinned Values" section, (3) capture baseline metrics needed for later AC-INTEGRATION measurements. This converts LOW-confidence ACs into HIGH-confidence ones before the first line of code is written and prevents mid-phase discovery of missing artifacts (which requires expensive recovery). FEAT-118 Phase 0 evidence: caught the `storage/replay/2026-07-27/` non-existence (declared in creative doc, absent on disk) before Phase 3 started; pivoted to synthetic-trace capture with zero cost to overall timeline. Reflection recommends codifying this as a first-class phase type in the build methodology.
  - _Source_: reflection-FEAT-118-vqa-tier3-architectural-hardening (2026-07-29)
  - _Reinforced_: 0x

- **creative-low-confidence-requires-file-line-evidence** (`memory-bank/creative/*.md`, Level 3-4 architecture-design agent): When a creative question is marked LOW confidence, the agent must locate **3+ specific `file:line` references** in the existing codebase that either validate or refute each candidate option before selecting a decision. Do not accept "seems reasonable" or "matches convention" as the resolution — an evidence-based refutation catches wrong-premise hypotheses before a single line of code is written. critic-pass-llm-evaluator Q4 evidence: the plan's LOW-confidence hypothesis (Option B — critic needs `RoleContext` from `setup_role_node`) was refuted by the creative agent reading `backend/api/routes.py:526`, `backend/engine/roles.py:238-600`, and `backend/engine/state.py:302-303`, revealing that `role_key` is already in `initial_state["role_queue"][0]` and `role_name` is a `ROLE_REGISTRY` lookup — position A works with zero login cost. Result: saved 5-10s per mismatch retry and prevented a wrong placement in the pipeline. The evidence-gathering overhead (~15 min of agent time) is worth substantially more than the build cost of committing to a wrong placement.
  - _Source_: reflection-critic-pass-llm-evaluator (2026-07-30)
  - _Reinforced_: 0x

- **phase-zero-singleton-refactor-with-backcompat-stub** (`backend/**/*.py`, high-coupling singletons in Level 4 features): When a feature's highest-risk change is a module-level singleton refactor with wide call-site coupling (LangGraph-wide, executor-wide, or similarly cross-cutting), always isolate that refactor as **Phase 0** with an explicit backward-compat singleton stub (e.g., `__legacy_singleton__`) — never fold it into the first substantive implementation phase. Phase 0 lands the refactor + stub as its own PR-shaped commit; every subsequent phase builds on a tested foundation; the stub is removed in a later phase once all callers are converted. `per-user-session-isolation` evidence: `backend/browser/context.py` (953 lines, LangGraph-wide) was refactored to `SessionBrowserManager` with `__legacy_singleton__` in Phase 0 (commit `d347810`); Phases 1-3 built on the stub; Phase 4 (`8201e6a`) removed it with full test coverage. Zero mid-phase call-site breakage across 8 phases. This is a **different flavor** of Phase 0 from the discovery/pinning variant above — same first-class-phase discipline, applied to refactor risk instead of artifact risk.
  - _Source_: reflection-per-user-session-isolation (2026-08-07)
  - _Reinforced_: 0x

- **phase-zero-baseline-first-for-healing-tasks** (`playwright/tests/**/*.test.ts`, healing / test-suite reliability tasks): For any healing task, always run a full baseline of the failing test set in a dedicated Phase 0 before writing any code — treat user-supplied failure counts and root-cause classifications as **hypotheses to verify, not facts to implement against**. Session-adjacent signatures (login form timeouts, auth-state errors on retry) require storage-state regeneration as a pre-flight (Phase 0.5) to disambiguate stale session from real regression before classifying failures. `heal-playwright-tests-round4` evidence: user-supplied plan named 11 tests as RC1 (`OrderHelper.selectStatus` PrimeNG overlay race); Phase 0 baseline runs found **0 of the 11 were active** — half were already green, half had unrelated real-red signatures. Phase 0.5 storage-state regen unmasked 3 tests with distinct real-red root causes that would have been miscategorized as RC1. This evidence redirected the entire plan (rescope commit `277bb7c`) and prevented a branch full of phantom fixes. This is a **healing-task flavor** of Phase 0 — same first-class-phase discipline as the discovery/pinning and singleton-refactor variants above, applied to failure-inventory verification.
  - _Source_: reflection-heal-playwright-tests-round4 (2026-08-11)
  - _Reinforced_: 0x
