# Archive: custom-creds-prompt-when-required — Prompt for Custom credentials when Computer-Use loop needs them

## Metadata

- **Task**: custom-creds-prompt-when-required
- **Complexity**: Level 1
- **Completed**: 2026-08-12
- **Branch**: task/custom-creds-prompt-when-required
- **PR Target**: main
- **Reflection**: memory-bank/reflection/custom-creds-prompt-when-required-reflection.md

## Summary

Landed a `CustomCredentialPanel` inline prompt in `RunTestView.tsx` so users blocked by the admin-credentials preflight check can enter credentials without leaving the screen — mirrors the existing `GhostCredentialPanel` pattern (TASK-125 / FEAT-116). That was the declared L1 scope and shipped in commit `0b14424` with TDD-driven test coverage (5 tests, all passing).

Under real-time debugging pressure the scope expanded significantly. A follow-up commit (`68e3d09`, 11 files, 659 insertions) landed a broader set of related fixes to the Start-Test → Record-Demo → Save-as-Test flows so a user can pick a Test-As role, click Start Test, and have the Computer-Use loop just run without ghost/custom credentials required — and after a successful run, have the saved `.spec.ts` auto-open a PR.

## Solution

### Original scope — commit `0b14424`

New `CustomCredentialPanel.tsx` component + wiring in `RunTestView.tsx` + 5 tests in `CustomCredentialPanel.test.tsx`. Mirrors `GhostCredentialPanel` pattern at component and test level.

### Scope expansion — commit `68e3d09`

Seven related changes bundled into one commit:

1. **CU role-driven login.** CU runner now delegates to `ensure_role_authenticated(role, login_url=target_url)` — the same helper `web_surfer` and `switch_actor` use — when only a Test-As role is set. Explicit ghost/custom creds still take precedence and use the manual form-fill path.
2. **Storage-state application pattern (`_apply_role_storage_state`).** Playwright's context `storage_state` restores cookies reliably but races Angular boot for per-origin localStorage — the router evaluates auth guards before localStorage hydrates. Fix mirrors the working pattern in `persona_switch_node._perform_auth_switch`: navigate → inject localStorage via `page.evaluate` → `reload(wait_until="domcontentloaded")` → verify JWT. On verification failure, invalidate cache and retry once.
3. **localhost:4200 as a vProMedia env.** Added to `products.yaml`. AuthManager state files + wrapper cache now URL-scoped (`{role}__{host}_state.json`, cache key `{role}@@{login_url}`) so switching between two-test and localhost doesn't reuse stale cookies for the wrong origin. Legacy fallback preserves existing two-test state files.
4. **Login helpers made Angular-dev-server-friendly.** Switched initial navigation from `wait_until="networkidle"` to `"domcontentloaded"` in three places (`AuthManager._perform_login`, `_login_with_ephemeral_creds`, `_apply_role_storage_state`) because Angular HMR WebSocket keeps `networkidle` from ever firing.
5. **Record-Demo Finish button.** New `POST /codegen/{id}/finish` sends SIGTERM to the playwright codegen subprocess so the recording can be ended from the UI. In production the browser lives inside a noVNC iframe with no reliable close affordance; SIGTERM lets Playwright flush its `--output` cleanly. Frontend adds a "Finish Recording" primary button in `RecordDemoModal.tsx`.
6. **`save-as-test` 500 fix.** `_run_states.get()` is async on the store abstraction; three call sites in `routes.py` were calling it synchronously. Switched to the sync-compatible `get_sync()` helper the store already exposes.
7. **`save-as-test` PR auto-open.** Extracted the GitHub REST-API commit mechanics into a new `backend/engine/github_pr.py` module (`commit_files_and_open_pr(files, branch_prefix, ...)`). `save_run_as_test` now opens a PR after writing the `.spec.ts`, matching record-demo behavior. `SaveAsTestDialog` surfaces the PR link or the error inline.

## Files Changed

### Original scope (commit `0b14424`)
- `frontend/src/components/CustomCredentialPanel.tsx` — new component
- `frontend/src/components/__tests__/CustomCredentialPanel.test.tsx` — 5 tests
- `frontend/src/components/RunTestView.tsx` — showCustomCredsPrompt state + panel rendering

### Scope expansion (commit `68e3d09`)
- `backend/api/routes.py` — `execute_cu` login-path routing, `_run_states.get_sync()` fixes, `save_run_as_test` PR auto-open, `ExecuteCURequest.user_role`, `SaveRunAsTestResponse.pr_url`
- `backend/config/products.yaml` — `local: http://localhost:4200` env
- `backend/engine/auth_manager.py` — URL-scoped state files + wrapper cache key + `domcontentloaded` init nav
- `backend/engine/codegen_session.py` — `finish_session` sends SIGTERM
- `backend/engine/computer_use/runner.py` — role-auth path via `ensure_role_authenticated`, new `_apply_role_storage_state` helper, stale-JWT invalidate-and-retry
- `backend/engine/github_pr.py` — **new** shared PR helper module
- `backend/engine/persona_switch_node.py` — `domcontentloaded` init nav + shortened post-click `networkidle` timeout
- `frontend/src/components/RecordDemoModal.tsx` — Finish Recording button + updated copy
- `frontend/src/components/RunTestView.tsx` — credential priority reworked (ghost → custom → role), sends `user_role`, removed pre-flight error
- `frontend/src/components/SaveAsTestDialog.tsx` — PR link / error surfaces in success state
- `frontend/src/hooks/useExecution.ts` — `ExecuteCURequest.user_role`, `SaveRunAsTestResponse` PR fields

## Test Coverage

- **Original scope**: 5 new tests in `CustomCredentialPanel.test.tsx`, all pass. Full suite 170/176 (4 pre-existing unrelated failures).
- **Scope expansion**: No new automated tests. All changes validated by TypeScript build (`npx tsc -b` clean) and Python syntax parse. This is a known test debt (see reflection §Technical Debt).

## Learnings Consolidated

Two patterns folded into `memory-bank/agent-rules/_learned/browser-patterns.md`:
- **spa-storage-state-inject-then-reload** — Playwright `storage_state` races Angular router auth-guard evaluation; correct sequence is navigate → `page.evaluate("localStorage.setItem(...)")` → `page.reload(wait_until="domcontentloaded")` → verify JWT.
- **angular-dev-server-wait-until** — use `wait_until="domcontentloaded"` not `"networkidle"` when the target URL may be an Angular HMR dev-server.

Both are new patterns (no exact overlap with existing bullets in browser-patterns.md).

## Follow-up Tasks Filed in Reflection

Three items of technical debt were identified but not addressed under this task's scope:

1. **Stale-JWT auto-retry gap** — `run_computer_use`'s `RuntimeError` catch does not re-run `ensure_role_authenticated` with `force_refresh=True` before erroring.
2. **`codegen_session._github_api_commit` refactor** — the record-demo flow should use the new `github_pr.commit_files_and_open_pr` helper instead of its inline duplicate.
3. **`_run_states` access-pattern normalization** — `routes.py` has three coexisting idioms (dict subscript, `.get_sync()`, `isawaitable`-check-and-conditional-await); a codebase audit would eliminate the latent bug class.

Each is a candidate for its own L1 task.

## Notes

The BMB L1 workflow correctly handled the declared scope (task creation, TDD build, guard, reflection). The scope expansion happened entirely in a conversational context — outside any formal `/bmb:build` phase — which meant no phase gates fired, no TDD requirement applied, and no commit guard ran. This is a structural gap in how L1 handles emergent conversational scope, not a failure of any specific component. See reflection §Emergent Scope and L1 Task Limits.
