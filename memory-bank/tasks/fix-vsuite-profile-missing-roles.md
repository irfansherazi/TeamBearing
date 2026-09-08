---
slug: fix-vsuite-profile-missing-roles
legacy_id:
feature:
status: COMPLETE
---

# fix-vsuite-profile-missing-roles: Close the vSuite profile role gap that causes silent credential-fallback for vpromotions_user (+ writer, traffic_manager)

**Complexity**: Level 1
**Status**: COMPLETE
**Roadmap**: N/A
**Branch**: task/fix-vsuite-profile-missing-roles
**Worktree**: N/A (Level 1 uses direct branch, not worktree)
**Reflection**: memory-bank/reflection/fix-vsuite-profile-missing-roles-reflection.md
**Archived**: memory-bank/archive/fix-vsuite-profile-missing-roles-archive.md
**Completed**: 2026-07-30

## Task Description

Preflight auto-login for role `vpromotions_user` fails today because the role is not defined in the active vSuite profile (`backend/profiles/vsuite.py` `_VSUITE_ROLES`). When a profile is active, `backend/engine/roles.py:112-115` builds `env_fallback_map` from `profile.roles` only, so `ROLE_EMAIL_VPROMOTIONS_USER` is silently dropped. Credentials fall through to hardcoded defaults at `roles.py:167` (`josh.schauer@vcreativeinc.com`) and `roles.py:523` (`Ep!cVCteam2026$`), which the server rejects — surfacing as the misleading `'vc2JWT' not found in localStorage after 10 s` error.

The same bug class silently affects `writer` and `traffic_manager` (also missing from `_VSUITE_ROLES`).

Ship Proposal 1 (minimal targeted patch) with three narrow adjustments from Proposal 3:

1. **Add three role entries to `_VSUITE_ROLES` in `backend/profiles/vsuite.py`** (`vpromotions_user`, `writer`, `traffic_manager`), each with `email_env_var` wired so `.env` overrides work uniformly.
2. **Do NOT hardcode `josh.schauer@vcreativeinc.com`** in the new `vpromotions_user` entry — set `email=""` so operators must configure `ROLE_EMAIL_VPROMOTIONS_USER` explicitly (or supply the correct password for the account).
3. **Remove the two stale hardcoded defaults** at `backend/engine/roles.py:167` (personal email in fallback map) and `backend/engine/roles.py:523` (the `"Ep!cVCteam2026$"` password default on the `RoleContext` construction for `vpromotions_user`).
4. **Add regression + invariant tests** in `tests/test_task_012_roles.py`:
   - `test_vsuite_profile_contains_vpromotions_user` — assertion-only regression guard.
   - `test_vpromotions_user_honors_env_override` — proves `ROLE_EMAIL_VPROMOTIONS_USER` is actually read.
   - `test_profile_defines_every_products_yaml_role` — invariant test that iterates every role in `backend/config/products.yaml` and asserts each is a key in `VSUITE_PROFILE.roles`. Locks the gap so CI catches the next dropped role.

**Explicit prerequisite** (documented in the PR body, NOT in code): before this PR merges, set `ROLE_EMAIL_VPROMOTIONS_USER=<shared-password test account>` in `.env` / SSM for every deploy target. Without this, `vpromotions_user` runs still fail after the patch — the fix restores the env-override path but does not itself supply credentials.

## Implementation Notes

**Root-cause investigation report**: full Phase 0-6 investigation ran in the parent conversation on 2026-07-30. Confirmed by an adversarial verifier sub-agent. Key evidence:

- Diagnostic screenshot at `memory/auth_states/vpromotions_user_login_failure.png` shows the login form fully populated and the server-rendered "Invalid credentials" banner — the `vc2JWT` timeout is a symptom, not the cause.
- `backend/profiles/vsuite.py` `_VSUITE_ROLES` (lines 45-283) contains 13 role definitions; grep for `vpromotions_user` / `writer` / `traffic_manager` returns zero matches.
- The dead-code `else` branch at `backend/engine/roles.py:116-135` DOES include `vpromotions_user`, but it only fires when `_profile is None`. Under any real invocation `_profile.roles` is truthy, so the profile-derived map is authoritative and the hardcoded fallback path is unreachable.
- No `.env` override exists for `ROLE_EMAIL_VPROMOTIONS_USER`; the personal-email default at `roles.py:167` was added uncommitted 16 min AFTER the failing run — a first-pass patch attempt that must be reverted.
- The shared test password `Ep!cVCteam2026$` was set globally in commit `70f2328` "feat(auth): update shared test password to Ep!cVCteam2026$ across the test suite and engine config".

**Deferred to follow-up tasks** (explicitly out of scope for this Level 1 fix):

- Full structural rewrite of `_build_registry()` to collapse the 356-line hardcoded block into a data-driven loop.
- Wiring `RoleDefinition.password_env_var` (defined-but-unread at `backend/profiles/base.py:166`) into `_resolve_credentials`.
- Rewriting `backend/engine/kb_client.py` `_PERSONA_FILE_MAP` (lines 99-111) and `fetch_all_role_credentials` (lines 621-630) to derive from the profile.
- The `_enforce_profile_invariant()` module-load hard-fail. Instead, this task adds a CI-level test that catches the same class of bug — same protection, staged rollout.
- Improving the `auth_manager.py` failure message to lead with the server-rendered error banner ("Proposal 2 — defensive guard"). Nice-to-have follow-up.

## Files to Touch

- `backend/profiles/vsuite.py` — add 3 `RoleDefinition` entries (~40-50 lines)
- `backend/engine/roles.py` — remove line 167 fallback map entry; change line 523 default from `"Ep!cVCteam2026$"` to `""`; change line 522 default from `"josh.schauer@vcreativeinc.com"` to `""`
- `tests/test_task_012_roles.py` — add 3 tests (see Task Description)

## Acceptance Criteria

- `VSUITE_PROFILE.roles` contains `vpromotions_user`, `writer`, and `traffic_manager`.
- `test_vsuite_profile_contains_vpromotions_user`, `test_vpromotions_user_honors_env_override`, and `test_profile_defines_every_products_yaml_role` all pass.
- The two hardcoded defaults at `roles.py:167` and `roles.py:522-523` are removed.
- Existing test suite still passes (no regression in the other 13 roles' credential resolution).

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Step 1 Read Task Context: COMPLETE — single-phase Level 1 task
- Step 3 TDD (RED→GREEN): COMPLETE — 3 tests written + passing; 3 files modified
- Step 7 Integration Verification: COMPLETE — 9/9 tests pass; pre-existing unrelated failure in test_environment_scoping.py confirmed by stash test
- Step 11 Git Completion: COMPLETE — committed and pushed to task/fix-vsuite-profile-missing-roles
- Reflection Agent: COMPLETE — Output: memory-bank/reflection/fix-vsuite-profile-missing-roles-reflection.md

### Guard & Recovery Log
Phase 1: guard PASS — prod=3 test=1 (tests/test_task_012_roles.py covers all production changes)
