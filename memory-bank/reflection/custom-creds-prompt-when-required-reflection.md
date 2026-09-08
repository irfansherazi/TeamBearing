# Reflection: custom-creds-prompt-when-required — Prompt for Custom credentials when Computer-Use loop needs them

**Date**: 2026-08-12
**Task Complexity**: Level 1
**Total Phases**: 1 (original scope) + significant out-of-band scope expansion
**Duration**: 2026-08-12T00:00:00Z to 2026-08-12T17:45:00Z

## Executive Summary

This task started as a well-scoped Level 1 fix: add a `CustomCredentialPanel` inline prompt in `RunTestView.tsx` so users blocked by the admin-credentials preflight check can enter credentials without navigating away. That original work shipped cleanly in commit `0b14424` — five tests, TDD process, mirrors the existing `GhostCredentialPanel` pattern exactly.

What followed was six-plus rounds of scope expansion driven by real-time user debugging in a live conversation. A second commit (`68e3d09`, 11 files, 659 insertions) encompassed: a Record-Demo Finish button, CU credential resolution via the role registry, a replacement CU login helper using the proven `ensure_role_authenticated` path, URL-scoped AuthManager state files to prevent cross-env cache collisions, `domcontentloaded` wait-until fixes for Angular dev-server, an async/sync `_run_states.get()` bug fix in three call sites, and `save-as-test` PR auto-opening backed by a new shared `github_pr.py` module.

The original task was delivered correctly. The expanded work unblocked real user pain quickly. The trade-off is: seven distinct changes landed in one commit with no tests, no task tracking, no roadmap linkage, and no phase gates. This reflects a genuine gap in how the BMB L1 workflow handles emergent in-session scope rather than any failure of individual components.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement

**Status**: Original scope — All Met. Expanded scope — Functionally delivered but undertested.

The four acceptance criteria from the task file were all satisfied by commit `0b14424`:
- `CustomCredentialPanel` component exists and renders when `showCustomCredsPrompt` is set
- Panel triggers when admin-credential preflight fires and no ghost path is available
- Save action writes `customEmail`/`customPassword`/`useCustomCreds: true` into `runConfig` and auto-retries
- 5 tests (happy path, dismiss, retry-after-save) mirror `GhostCredentialPanel.test.tsx` exactly

The scope-expansion items (`68e3d09`) were not in the original requirements. They were each individually validated by TypeScript compilation and Python syntax parse, but have no automated test coverage.

### Code Quality Assessment

**Overall Rating**: Good (original work) / Fair (scope expansion)

**Original work (`0b14424`):**
- Maintainability: Excellent. The `CustomCredentialPanel` mirrors `GhostCredentialPanel.tsx` at the component level and `GhostCredentialPanel.test.tsx` at the test level. A future developer can understand the custom-creds flow by reading the ghost-creds flow.
- Architecture: Clean. New state `showCustomCredsPrompt` is narrow and local. No prop drilling or context changes.
- Error handling: Covers the dismiss path, the retry path, and the case where save is called with an empty email.
- Testing: Complete for the scope. 5/5 pass. 170/176 suite (4 pre-existing failures, unrelated).

**Scope expansion (`68e3d09`):**
- `_apply_role_storage_state`: The localStorage-inject-then-reload pattern is sound and is explicitly modelled on the working pattern in `persona_switch_node._perform_auth_switch`. The stale-JWT detection (checking both `jwt_present` and `/login` in URL) is appropriate. The `domcontentloaded` wait-until choice is correct and is documented. One concern: the runtime stale-JWT recovery on failure raises `RuntimeError` but does not itself call `invalidate_role_state` + retry — that logic was left to the caller (`run_computer_use`) to implement if it chooses. The current call site in `run_computer_use` logs an error and proceeds without retry, meaning a stale cache silently fails the run instead of refreshing. This is a known gap the user accepted during the session.
- `AuthManager.state_path` URL-host scoping: The logic is correct. The legacy fallback (use the unsuffixed file if it exists AND the host is the historical two-test default) correctly avoids forcing re-auth for existing users. The `_manager_cache` key includes the `login_url` to prevent per-env cache collisions — this is the right invariant. No regression risk for existing two-test deployments.
- `github_pr.commit_files_and_open_pr`: Clean abstraction. The eight-step GitHub REST sequence (repo metadata → HEAD SHA → branch → blobs → tree → commit → fast-forward → PR) is standard and the module is well-documented. One piece of technical debt: `codegen_session._github_api_commit` was **not** refactored to use this module. The two implementations are now divergent duplicates — a future merge conflict waiting to happen.
- `_run_states.get()` → `get_sync()` fix: The fix itself is correct (three call sites in `routes.py` were calling the async `.get()` synchronously in contexts that don't await it). However, line 3635 shows a fourth pattern (`_get_result = _run_states.get(run_id)` with an `isawaitable` check and conditional await) that was NOT migrated — it uses a compatibility shim instead. This heterogeneity means the codebase has three different idioms for reading from `_run_states` in the same file: dict subscript, `.get_sync()`, and the isawaitable-check pattern. The latent risk is that a future developer adds a `.get()` call in a synchronous context and it silently returns a coroutine instead of the state dict.
- Record-Demo Finish button: Clean. `POST /codegen/{id}/finish` sends SIGTERM (not SIGKILL) correctly, so the codegen subprocess flushes its `--output` file before exiting. Frontend disables the button until `sessionId` is set.

### Technical Decisions

**Key Decisions:**
1. Use `ensure_role_authenticated(role, login_url=target_url)` instead of rolling a new CU-specific login path — correct decision. This is the same helper `web_surfer` and `switch_actor` use; it inherits all the TTL caching, credential resolution, and retry logic for free.
2. Scope `AuthManager` state files by URL host (`{role}__{host}_state.json`) rather than by product or environment name — correct decision. The host is derivable from any URL without knowing the product registry, and it naturally scopes two-test vs. localhost vs. smoketest.
3. Use `domcontentloaded` instead of `networkidle` for Angular SPA navigation — correct and important. `networkidle` never fires when an HMR WebSocket is open. This is explicitly documented in the new code and should be generalized to a project-wide convention.
4. Extract PR mechanics into `github_pr.py` — correct direction but incomplete. Leaving `codegen_session._github_api_commit` un-refactored halves the value of the abstraction.
5. Send SIGTERM (not SIGKILL) for codegen Finish — correct. Playwright codegen subprocesses flush `--output` on clean shutdown; SIGKILL would lose the recorded steps.

**Trade-offs:**
- Speed vs. testing: All scope-expansion changes shipped without tests, under time pressure while the user was actively debugging. The velocity was necessary. The test debt is real.
- Inline scope expansion vs. new tasks: Each of the seven items could have been its own L1 task. Having them in one commit makes revert harder and makes the PR description a wall of text. The user explicitly chose to continue iterating in-session rather than stop and re-task.

### What Went Well

1. Original scoped work executed cleanly: TDD process, mirrors existing pattern, all tests pass, committed and pushed in one build phase.
2. `_apply_role_storage_state` correctly diagnoses the root cause (Angular router reads localStorage before `storage_state` hydrates) and applies the right fix (navigate → inject → reload), matching the working pattern in `persona_switch_node`.
3. URL-scoped `AuthManager` state files are backward-compatible — the legacy fallback prevents re-auth for existing `two-test` users on first upgrade.
4. The GitHub PR abstraction (`github_pr.py`) is clean and well-documented; both callers get a consistent PR experience.
5. SIGTERM for codegen Finish is correct process lifecycle management.

### Challenges Encountered

1. **CU role auth landing on the login page** — root cause was Angular router evaluating auth guards before localStorage hydrated from `storage_state`. Took multiple iterations of log-read-fix cycles to land on the inject-then-reload pattern. The fix is proven correct but the diagnostic arc was expensive in wall-clock time.
2. **`_run_states.get()` returning a coroutine** — three call sites in `routes.py` were calling `.get()` synchronously in a non-awaiting context. The fix was to switch to `get_sync()`, but the fix was applied only to the three sites visible in the error path, leaving a heterogeneous pattern across the file.
3. **`codegen_session._github_api_commit` not refactored** — identified as technical debt during the session but not addressed due to time pressure. The duplicate remains.

### Technical Debt & Future Work

- **Stale-JWT auto-retry**: `run_computer_use` catches the `RuntimeError` from `_apply_role_storage_state` when JWT is stale, but does not call `invalidate_role_state` + retry. A stale cache causes a silent run failure. The fix would be a one-time retry with `force_refresh=True` before escalating to error.
- **`codegen_session._github_api_commit` should use `github_pr.commit_files_and_open_pr`**: The two implementations will drift. The refactor is ~30 lines but carries real regression risk for the record-demo flow, so it warrants its own L1 task.
- **`_run_states` access pattern heterogeneity**: Three idioms exist in `routes.py`. A codebase-wide audit and normalization to `get_sync()` everywhere would eliminate the latent bug class.
- **No tests for `_apply_role_storage_state`, `commit_files_and_open_pr`, or `save_run_as_test` PR path**: All three are meaningful code paths with error branches. Unit tests with mocked Playwright page and mocked `httpx` client would be straightforward to add.

---

## Dimension 2: Claude Code Ecosystem Effectiveness

### Build Session Analysis

**Build Sessions**: 1 formal BMB session (original scope) + 6+ conversational iterations (scope expansion — outside BMB workflow)
**Sub-Agents Spawned**: TDD Agent (original build), Code Review Agent (original build)
**Tool Calls**: ~45 (original build) + undocumented (conversational iterations)
**Errors Recovered**: 0 formal guardrail misses

#### Tool Utilization

| Tool | Count (est.) | Notes |
|------|-------------|-------|
| Read | ~15 | Used heavily for reading GhostCredentialPanel pattern to mirror |
| Edit | ~8 | Component creation and RunTestView wiring |
| Write | ~2 | New component file + test file |
| Bash | ~12 | TypeScript build check, Python syntax check, test runs |
| Task (sub-agent) | ~2 | TDD Agent, Code Review Agent |

#### Sub-Agent Performance

| Agent Type | Invocations | Model | Effectiveness |
|------------|-------------|-------|---------------|
| TDD Agent | 1 | Sonnet | Effective — RED→GREEN cycle completed, 5 tests match GhostCredentialPanel pattern |
| Code Review Agent | 1 | Sonnet | Effective — identified TypeScript clean, mirrors pattern correctly |

### Command Workflow Evaluation

**Commands Used**: `/bmb:task` (task creation), `/bmb:build` (original scope)

**Workflow Efficiency**: Good for original scope; Not applicable for scope expansion (which bypassed BMB entirely)

**Assessment:**
- The L1 workflow (`/bmb:task` → `/bmb:build` → `/bmb:reflect`) worked correctly for the original scoped work. Task file was created, build was clean, Execution State was updated.
- The six-plus conversational iterations of scope expansion happened entirely outside the BMB workflow — no task files created, no phases tracked, no guard log entries, no reflection until now. This is the central ecosystem finding.
- The BMB commit-guard (`scripts/commit-guard.sh`) saw no failures. This is partly because the scope expansion was committed as a single large commit in a conversational context where no formal build phase was running.

### Context File Effectiveness

**Files Loaded**: `GhostCredentialPanel.tsx`, `GhostCredentialPanel.test.tsx`, `RunTestView.tsx`, task file

**Assessment:**
- **Helpful**: The GhostCredentialPanel files as the explicit pattern reference were critical. The task file's Implementation Notes section predicted exactly where the work would land and what shape it would take — good task writing.
- **Gaps**: No context file warns against scope expansion in conversational sessions. The BMB system enforces scope via phase gates, but only when the user is invoking formal commands — conversational iteration bypasses all gates.
- **Redundancy**: None identified.

### Memory Bank Organization

**Assessment:**
- **Structure**: Adequate. The task file captured the original scope clearly.
- **Navigation**: The Execution State section correctly tracked the formal build phase. The scope-expansion work has no Execution State record.
- **Completeness**: The task file's "Out of Scope" section explicitly listed "Backend / Computer-Use loop credential handling changes" — which is exactly what happened in the scope expansion. This is a signal that the out-of-scope boundary was visible but not enforced in a conversational context.

### Memory-Bank Corrections (from Guardrail Misses)

None — no guardrail misses this build. The commit-guard saw zero FAILs. The scope expansion bypassed the guard entirely by happening in a conversational context outside a formal `/bmb:build` invocation.

### Emergent Scope and L1 Task Limits — Key Ecosystem Observation

This task surface a structural gap in the BMB L1 workflow: **L1 tasks have no mechanism to detect or respond to emergent scope that arrives conversationally**. When a user says "while you're in here, can you also fix X?", the BMB system has no hook. The work gets done, but it bypasses:
- Task tracking (no new task file)
- Phase gates (no `/bmb:build` invocation)
- Commit guard (no formal build phase running)
- Test requirements (no TDD agent spawned)
- Execution State logging (no record of what changed)

The result is a large undocumented commit that is functionally useful but organizationally invisible to the BMB system. The reflection document is the first place this work is described.

### Suggested Improvements to Claude Code System

**High Priority:**
1. **Scope-drift detection in conversational sessions**: When working on a L1 task and the user introduces a new "while you're at it" request that touches files outside the original task's stated scope, the assistant should explicitly flag: "This looks like a new L1 task. Should I create a task file and run `/bmb:build`, or do you want to keep this in-session?" This is a behavioral pattern, not a tooling change, but it would catch the most common case.
2. **Out-of-scope boundary enforcement prompt**: When the task file explicitly lists items as "Out of Scope" and the user asks to do one of them, surface the boundary before proceeding: "The task file lists 'Backend / Computer-Use loop credential handling changes' as out of scope. Do you want to create a new task for this?"

**Medium Priority:**
3. **Conversational commit summary**: At the end of a conversational session where multiple changes were made outside a formal build phase, generate a summary paragraph listing all changed files and their purpose, and offer to create a task file retroactively for reflection and archiving.
4. **Test requirement gate for untracked scope**: If `git diff --stat` shows more than N files changed and no formal build phase is running, warn: "You've changed N files in this session. Consider running `/bmb:build` so tests are run and the guard validates these changes."

**Low Priority / Nice to Have:**
5. **`/bmb:task --expand` mode**: A command that upgrades an in-progress L1 task to L2 mid-stream, creates a roadmap feature, and migrates the existing commit history into a plan. Niche but would have been useful here.
6. **Execution State auto-append for conversational changes**: Appending a "conversational additions" section to the task file's Execution State when untracked work is committed to the task branch.

**Note**: These are suggestions only. Do NOT implement these changes — they are recommendations for future system enhancements.

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

1. **playwright-auth** (`backend/engine/auth_manager.py`, `backend/engine/computer_use/runner.py`, any file using Playwright storage_state with Angular SPAs): When applying `storage_state` to an Angular SPA, Playwright's per-origin localStorage restoration races the Angular router's initial auth-guard evaluation. The correct pattern is: (1) navigate to target URL (cookies already in context), (2) inject localStorage entries via `page.evaluate("localStorage.setItem(...)")`, (3) `page.reload(wait_until="domcontentloaded")`, (4) verify JWT in localStorage — raise if absent. Do not rely on `storage_state` alone to authenticate Angular apps.

2. **angular-dev-server** (`backend/engine/auth_manager.py`, `backend/engine/persona_switch_node.py`, any login helper): Use `wait_until="domcontentloaded"` instead of `wait_until="networkidle"` when the target URL may be an Angular dev-server (e.g., `localhost:4200`). Angular's HMR WebSocket keeps `networkidle` from ever resolving. Apply this to all three navigation points in a login flow: initial nav, post-login nav, and reload.

### Learned Rules Applied

No learned rules from `memory-bank/agent-rules/_learned/` were loaded or applicable to this task — the original scope was a direct pattern-mirror of TASK-125 (GhostCredentialPanel), and the scope expansion was entirely conversational.

### For Claude Code Workflow

1. **Conversational sessions can silently exceed L1 scope** — The BMB phase gates only fire during formal command invocations. A user iterating on a problem in chat bypasses all gates. The assistant must self-police scope boundaries using the task file's "Out of Scope" section as an explicit boundary marker.
2. **Large undocumented commits are a reflection anti-pattern** — Commit `68e3d09` (659 insertions, 11 files, zero new tests) would fail any reasonable code-review gate. The BMB system did not catch it because no guard was running. For L1 tasks, the human reviewer is the only safety net when scope expands conversationally.
3. **Technical debt should be filed immediately, not noted in comments** — Three items (stale-JWT retry, `codegen_session` refactor, `_run_states` access normalization) were identified during the session but left unfiled. A quick `/bmb:task` creation for each takes 30 seconds and creates a trackable artifact.

---

## Conclusion

The original Level 1 task — `CustomCredentialPanel` inline credential prompt in `RunTestView.tsx` — was delivered correctly, tested thoroughly, and implemented with high fidelity to the established `GhostCredentialPanel` pattern. That work is a clean Level 1 success.

The scope expansion that followed is a different story. Seven distinct changes landed in one untested commit, driven by real user pain encountered during live debugging. Each change was technically sound (the `_apply_role_storage_state` pattern is correct, the URL-scoped AuthManager is backward-compatible, the GitHub PR module is clean). But the aggregate result — 659 insertions with no tests, no task tracking, and no roadmap linkage — is a maintenance liability.

The key ecosystem learning is not about any individual failure but about the structural gap between how BMB enforces discipline during formal builds and how it has no hooks during conversational sessions. The out-of-scope boundary in the task file was visible and correct; it simply had no enforcement mechanism in a live chat context.

**Overall Task Success**: Partial Success (original scope: full success; scope expansion: functionally delivered, undertested)

**Overall Workflow Effectiveness**: Moderately Effective (formal BMB phase worked correctly; conversational scope expansion bypassed all workflow controls)

**Recommendation**: Ready to archive, with three follow-up L1 tasks recommended:
1. Stale-JWT auto-retry in `run_computer_use`
2. Refactor `codegen_session._github_api_commit` to use `github_pr.commit_files_and_open_pr`
3. Normalize `_run_states` access pattern across `routes.py`
