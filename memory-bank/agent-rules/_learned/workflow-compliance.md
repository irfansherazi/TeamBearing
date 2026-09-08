---
name: Workflow Compliance Patterns
globs: ["memory-bank/tasks/*.md", "memory-bank/roadmap.md", ".agent/workflows/*.md"]
paths: ["memory-bank/tasks/", "memory-bank/c4/"]
topics: ["workflow", "documentation", "c4-architecture", "mermaid"]
priority: high
auto_generated: true
derived_from: [hitl-portal-aware-click-capture, fix-vsuite-profile-missing-roles, nightly-scheduled-playwright-test-suite-run, vqa-pinned-testplans]
evidence_count: 5
last_validated: 2026-08-18
---


# Learned Rules: workflow-compliance

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **strict-workflow-adherence** (`/vc-*` workflows): When executing any `/vc-*` workflow, follow the workflow steps EXACTLY as written. Never add custom options, alternative paths, or freestyle commentary that deviates from the prescribed output format. If the workflow says to present a specific message and wait for a yes/no, do exactly that — do not invent additional choices (A/B/C), suggest alternatives not in the workflow, or editorialize beyond what the step specifies. The workflow is the contract.
  - _Source_: user-correction (2026-05-13)
  - _Reinforced_: 1x

- **no-improvisation-on-phase-gates** (`/vc-*` workflows): Phase-gate steps (complexity evaluation, review prompts, approval checks) are strict decision points. Present the exact prescribed output, ask the exact prescribed question, and STOP. Do not combine phase-gate questions with additional suggestions or options that could confuse the decision.
  - _Source_: user-correction (2026-05-13)
  - _Reinforced_: 1x

- **no-step-skipping** (`/vc-build`): ZERO TOLERANCE — every numbered step in the `/vc-build` workflow (Steps 0 through 11) MUST be executed. No step may be skipped, abbreviated, or merged regardless of perceived phase simplicity, low risk, or "lightweight" scope. This applies equally to:
  - Step 5 (Test Batching)
  - Step 6 (Batched Test Execution)
  - Step 8 (Code Reviewer Agent)
  - Step 9 (Documentation Agent)
  
  A "trivial" change is not justification for skipping review or documentation. The workflow exists to catch blind spots that the implementer cannot see in their own work.
  - _Source_: user-correction (2026-05-13, TASK-014 Phase 3.3 — Steps 5, 6, 8, 9 were skipped)
  - _Reinforced_: 1x

- **inline-execution-parity** (`/vc-build`): When sub-agent dispatch (Gemini CLI) is unavailable, the orchestrator MUST execute every sub-agent's full methodology inline. "Inline" does not mean "optional" — it means the orchestrator personally performs the work that the sub-agent would have done. Specifically:
  - **Step 8 Code Review**: Read the code reviewer methodology from `.agent/workflows/agents/build-code-reviewer-agent.md`. Review ALL changed files for security, quality, patterns, and correctness. Document blocking/non-blocking issues. Loop with the coding agent (self) until blocking issues are resolved.
  - **Step 9 Documentation**: Read the documentation methodology from `.agent/workflows/agents/build-documentation-agent.md`. Update inline comments, memory bank docs, and diagrams as needed. This is not optional even for "data-only" or "config-only" changes.
  - _Source_: user-correction (2026-05-13, TASK-014 Phase 3.3 — skipped code review and docs because "Gemini CLI unavailable")
  - _Reinforced_: 1x

- **no-scope-based-exemptions** (`/vc-build`): The perceived size or risk of a phase change does NOT grant permission to deviate from the workflow. Common rationalizations that are NEVER valid:
  - "This is a lightweight phase" → Still requires code review + documentation
  - "Only metadata changed" → Still requires code review (metadata errors cause downstream failures)
  - "The tests all pass" → Tests passing validates correctness, NOT code quality or documentation completeness
  - "It's just a config change" → Config changes affect system behavior and must be reviewed
  - _Source_: user-correction (2026-05-13, TASK-014 Phase 3.3 — roadmap update was categorized as "low risk" to justify skipping steps)
  - _Reinforced_: 1x

- **execution-state-completeness** (`/vc-build`): The Execution State in `tasks/[task_id].md` must reflect ALL steps, including sub-agent steps executed inline. If Step 8 (Code Review) was performed inline, the execution state must still log it as COMPLETE with a summary. Missing steps in the execution state is evidence of a skipped step and a workflow violation.
  - _Source_: user-correction (2026-05-13, TASK-014 Phase 3.3 — execution state jumped from Step 7 to Step 10, omitting Steps 8+9)
  - _Reinforced_: 1x

- **architecture-doc-insertion-points** (`memory-bank/creative/TASK-*-architecture.md`): Level 3-4 architecture creative docs must include the **exact Python insertion point** (with variable names from the target file) alongside architecture diagrams. Pseudocode at the code level — not just flow diagrams — eliminates Phase 1 ambiguity and is the single most impactful quality difference between fast and slow Level 4 deliveries. The TASK-028 creative doc specified the exact `_dispatch_action()` insertion block including variable names; all 4 phases were delivered without ambiguity. Additionally, add a `## Runtime Dependencies` section for features invoking external services: list the SDK layer, credential source, and invocation pattern (sync/async).
  - _Source_: reflection-TASK-028 (2026-05-17)
  - _Reinforced_: 0x

- **ac-checkbox-discipline** (`memory-bank/tasks/TASK-*.md`): AC checkboxes (`- [ ] Unit test: ...`) in task files MUST be marked `[x]` at the moment the corresponding test is authored and first passes — never deferred to a later review or reflection phase. Stale `[ ]` checkboxes after a phase is complete create false phase-gate failures in subsequent phases and erode trust in the task file as the source of truth. In multi-phase Level 4 tasks, the coding agent should `grep -n "\[ \]"` in the task file after each test run and mark the passing ACs immediately.
  - _Source_: reflection-TASK-030 (2026-05-18)
  - _Reinforced_: 0x

- **open-questions-before-build** (`memory-bank/tasks/TASK-*.md`, `/vc-build`): When a task file contains `- [ ] Open Questions`, resolve them **before starting Phase 1 of the build** — either by obtaining explicit product owner sign-off, by applying an established project convention, or by documenting the assumption made with a rationale. Silent resolution-by-implementation (choosing an answer while writing code) is untraceability. At minimum, change `- [ ]` to `- [x] (Assumed: ...)` with the chosen answer inline. This prevents reflection-phase surprises where "no one decided this" is the answer to a design question.
  - _Source_: reflection-TASK-049 (2026-05-21)
  - _Reinforced_: 0x

- **c4-entrypoint-pattern** (`memory-bank/c4/c4-index.md`): Use a dedicated `c4-index.md` as the landing page for architecture documentation. It should provide a structured "zoom-in" path from System Context to Container to Component. This prevents the root memory bank files from being cluttered with implementation-level details while ensuring architecture remains discoverable.
  - _Source_: reflection-TASK-050 (2026-05-21)
  - _Reinforced_: 0x

- **mermaid-relationship-table** (`memory-bank/c4/*.md`): To maintain clarity as system complexity grows, always accompany Mermaid diagrams with a "Relationship Table." This table lists every edge (Source, Target, Description) explicitly. This ensures that even if a diagram becomes too dense to read easily, the underlying architectural logic remains documented and searchable.
  - _Source_: reflection-TASK-050 (2026-05-21)
  - _Reinforced_: 0x

- **worktree-main-sync** (`memory-bank/tasks/`, `/vc-build`): When a build runs in a git worktree (`.worktrees/X/`), the task file inside the worktree accumulates accurate state, but the main-branch `memory-bank/tasks/TASK-XXX.md` stays stale until archive. The `/vc-build` agent MUST update **both** task files at each phase boundary — not just the worktree copy. Failing to do so causes `/vc-reflect` to read a stale CREATIVE status from main, creating a false "prerequisites not met" appearance that must be manually resolved. Use `git diff --name-only HEAD` in the worktree to detect drift; add a sync step to the build phase-complete checklist.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **manual-visual-ac-closure** (`memory-bank/tasks/TASK-*.md`, Level 1 hotfixes): When an acceptance criterion is purely visual (e.g., "browser window appears"), automated tests cannot gate completion. As soon as the user confirms the visual behavior in chat (e.g., "I can see the browser"), immediately update the corresponding task file AC checkbox from `[ ]` to `[x]` with a note referencing the conversation or confirmation timestamp. Do NOT defer this to `/vc-reflect`. Stale `[ ]` checkboxes on visually-verified ACs at reflect-time signal a workflow gap, not an incomplete AC.
  - _Source_: reflection-TASK-061 (2026-05-27)
  - _Reinforced_: 0x

- **doc-task-logging-discipline** (`memory-bank/progress.md`, documentation/initiative tasks): Documentation-only and initiative-initialization tasks (e.g., TASK-072) must still be logged in `memory-bank/progress.md` to maintain a complete project history and audit trail. Even if no code was changed, the evolution of the roadmap and the addition of strategic features are critical project milestones that must be recorded chronologically.
  - _Source_: reflection-TASK-072 (2026-05-29)
  - _Reinforced_: 0x

- **initiative-initialization-audit** (`knowledge/`, Level 3+ initiatives): All Level 3+ strategic initiatives MUST establish a dedicated technical standard or audit checklist in the `knowledge/` directory during their initialization phase. This provides an objective baseline for future implementation tasks and ensures architectural governance from Day 1.
  - _Source_: reflection-TASK-078 (2026-05-29)
  - _Reinforced_: 0x

- **multi-phase-quickstart-block** (`memory-bank/tasks/TASK-*.md`, Level 4 multi-phase tasks): After each build phase completes, prepend a `## Next Conversation Quickstart` block (max 5 lines) to the task file before committing: completed phases, current phase, immediate next step, and any blockers. For builds spanning 4+ phases across multiple days and conversations, this eliminates the 10-15 minute re-orientation overhead at the start of each new session. Without it, agents must re-read the full task file to discover the current phase state. Template: `Phases complete: P1✅ P2✅ P3✅ | Now: P4 | Next step: [Step N] | Blockers: [none or list]`.
  - _Source_: reflection-TASK-080 (2026-05-31)
  - _Reinforced_: 0x

- **cross-branch-dependency-verification** (`memory-bank/tasks/TASK-*.md`, `/bmb:build` phase start): When a task description references code that "exists on branch X" or "was added in FEAT-Y," read the target file in the current worktree at the start of that phase before writing a single line of implementation. If the referenced code is absent (not yet merged to the feature branch), pivot immediately to regression tests that would catch any future reintroduction rather than spending phase time searching for non-existent code. Annotate the plan with "PRESENT/NOT-PRESENT on this branch" to prevent the same overhead at the next phase.
  - _Source_: reflection-TASK-125 (2026-07-22)
  - _Reinforced_: 0x

- **parallel-creative-contract** (`memory-bank/creative/*.md`, `/bmb:creative`): When two parallel creative sub-agents own adjacent payload surfaces (e.g., JS emits fields that Python consumes), require each doc to include a canonical "Payload Fields" table listing every field by name, type, and empty-value semantics. The orchestrator's design-review pass MUST diff the two tables — producer's outputs against consumer's expected inputs — before marking creative complete. Implicit semantic disagreements (e.g., `trigger_resolution_confidence` granular vs `capture_confidence` rolled-up) are otherwise caught only by luck or by a Phase 1 TDD blocker. Add a "Payload Contract" section to the architecture creative template to make the diff structurally trivial rather than prose-buried.
  - _Source_: reflection-hitl-portal-aware-click-capture (2026-07-29)
  - _Reinforced_: 0x

- **investigation-to-task-file-spec** (`memory-bank/tasks/*.md`, `/error-investigation` → `/bmb:task` handoff): For Level 1 tasks born from an `/error-investigation` (or any evidence-first analysis), front-load the specification: the task file MUST list (a) exactly which files to touch with line-level anchors, (b) exactly which lines to change and the "why" per line, (c) a named recommended proposal referencing the investigation output, and (d) an explicit deferred-items list with justification. A well-specified Level 1 task file eliminates build ambiguity more reliably than any TDD sub-agent hop — Sonnet's fast path is enough. The investigation is where the thinking happens; the build is mechanical.
  - _Source_: reflection-fix-vsuite-profile-missing-roles (2026-07-30)
  - _Reinforced_: 0x

- **infra-phase-test-free-declaration** (`/bmb:build`, `scripts/*.sh`, IaC/docs-only phases): When a build phase is pure infra (bash scripts, Terraform/CDK, docs) with zero application code and 0 automated tests per the task spec, declare it test-free in the phase's guard log **BEFORE** the build step runs, not after. The C2 production-vs-test ratio check does not apply to bash/IaC changes; pre-declaring keeps the guard log honest and avoids a confusing post-hoc WARNING that reads like the phase was under-tested when it was intentionally test-free by design. Pattern: in the task file's phase spec, include a line like `Phase N: 0 automated tests (pure infra/docs)`; the guard's C2 check then classifies as inapplicable rather than firing a WARNING.
  - _Source_: reflection-nightly-scheduled-playwright-test-suite-run (2026-08-11)
  - _Reinforced_: 0x

- **external-plan-doc-creative-waive** (`memory-bank/tasks/*.md`, `/bmb:plan` on Level 3-4): When a pre-existing external plan document (e.g., a `docs/todo/*-PR.md` handoff or a source-of-truth design doc) provides verbatim diffs, exact file targets, and concrete test-case names with HIGH spec confidence, the Spec Writer's correct call is to record `Creative Exploration Needed: **No.**` with a one-line reason citing the doc — not to run `/bmb:creative` on top. This is a legitimate Level-3 fast-path; the Spec Writer's codebase-verification pass provides the same drift-catching safety net that creative exploration would have provided. Concrete example: `vqa-pinned-testplans` skipped creative because `docs/todo/pinned-plans-PR.md` had already resolved the single design fork (new primitive vs. re-use content-hash cache) with concrete diffs; the 5-phase build ran clean end-to-end with no re-architecture. Gap in the workflow: there is no structured `creative_waived_reason` field to distinguish "external-plan-doc" from a low-complexity waive — the prose reason currently lives only in the task file body.
  - _Source_: reflection-vqa-pinned-testplans (2026-08-18)
  - _Reinforced_: 0x

- **planning-time-drift-notes** (`memory-bank/tasks/*.md`, `/bmb:plan` Spec Writer codebase-verification pass): When a source document (external plan doc, spec, or Jira ticket) references a file path, function name, or API surface that does not exist as described in the current codebase, the Spec Writer MUST document the correct target in an explicit `DRIFT NOTE:` line in the task file at planning time — do NOT leave it for the build phase to discover. Concrete example: `docs/todo/pinned-plans-PR.md` said "wire startup prune into `backend/api/app.py`"; that file does not exist — the lifespan handler lives in `backend/main.py:139`. The DRIFT NOTE in the task file converted a potential Phase-4 RED-cycle debugging session into a one-line implementation note. Structural drift caught at planning time is free; caught at build time it costs a full RED cycle plus test churn.
  - _Source_: reflection-vqa-pinned-testplans (2026-08-18)
  - _Reinforced_: 0x
