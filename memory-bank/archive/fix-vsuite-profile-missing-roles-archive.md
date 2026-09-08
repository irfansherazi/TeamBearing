---
slug: fix-vsuite-profile-missing-roles
complexity: Level 1
status: COMPLETE
archived: 2026-07-30
---

# Archive: fix-vsuite-profile-missing-roles

**Task**: Close the vSuite profile role gap that causes silent credential-fallback for `vpromotions_user` (+ `writer`, `traffic_manager`)
**Complexity**: Level 1
**Branch**: `task/fix-vsuite-profile-missing-roles`
**PR Target**: `main`
**Completed**: 2026-07-30

---

## Origin

Born from an `/error-investigation` skill run earlier in the same session (2026-07-30). The trace was `AuthManager: login failed — 'vc2JWT' not found in localStorage after 10 s`, which turned out to be a **downstream symptom**. The investigation's Phase 4 adversarial verifier confirmed the real cause was a **silent credential fallback**: `vpromotions_user` was missing from the active `_VSUITE_ROLES` profile, so `roles.py:112-115`'s `env_fallback_map` did not include it, `ROLE_EMAIL_VPROMOTIONS_USER` was silently dropped, and credentials fell through to a hardcoded personal email + shared test password combination that the server rejected. Phase 5 dispatched 3 parallel fix proposers + 1 critic. The critic recommended Proposal 1 (minimal targeted patch) with 3 narrow adjustments from Proposal 3 (structural fix). That recommendation became this task.

## Implementation Summary

**Commits on `task/fix-vsuite-profile-missing-roles`**:
- `57c634b` — task(fix-vsuite-profile-missing-roles): create Level 1 task file
- `e0b9efc` — fix(roles): add vpromotions_user, writer, traffic_manager to VSUITE_PROFILE to restore env-override credential path
- `a564c76` — fix-vsuite-profile-missing-roles: Add task reflection

**Files changed** (build):
- `backend/profiles/vsuite.py` — +54 lines (3 `RoleDefinition` entries: `vpromotions_user`, `writer`, `traffic_manager`, each with `email_env_var` wired)
- `backend/engine/roles.py` — 2 hardcoded defaults removed: `roles.py:167` (personal email fallback map entry) and `roles.py:522-523` (`"josh.schauer@vcreativeinc.com"` / `"Ep!cVCteam2026$"` `.get` defaults → empty strings)
- `tests/test_task_012_roles.py` — +72 lines (3 new tests: `test_vsuite_profile_contains_vpromotions_user` regression guard, `test_vpromotions_user_honors_env_override` env-override proof, `test_profile_defines_every_products_yaml_role` products.yaml invariant)

## Acceptance Criteria — All Met

- `VSUITE_PROFILE.roles` contains `vpromotions_user`, `writer`, and `traffic_manager`. ✓
- `test_vsuite_profile_contains_vpromotions_user`, `test_vpromotions_user_honors_env_override`, and `test_profile_defines_every_products_yaml_role` all pass. ✓
- The two hardcoded defaults at `roles.py:167` and `roles.py:522-523` are removed. ✓
- Existing test suite still passes (no regression in the other 13 roles' credential resolution). ✓ 9/9 pass in `tests/test_task_012_roles.py`.

## Deploy Prerequisite (Do Not Skip)

Before this PR merges: set `ROLE_EMAIL_VPROMOTIONS_USER=<shared-password test account>` in `.env` / SSM for every deploy target. Without this, `vpromotions_user` runs still fail — the fix restores the env-override path but does not itself supply credentials.

## Deferred Follow-Ups (Documented Technical Debt)

Explicitly out of scope for this Level 1 fix (from task file and reflection):

1. **`_build_registry()` structural rewrite** (high priority) — Collapse the 356-line hardcoded block into a data-driven loop over `VSUITE_PROFILE.roles`. Until then, adding a role still requires updating both `vsuite.py` AND `roles.py`.
2. **`password_env_var` wiring** (medium priority) — `RoleDefinition.password_env_var` is defined at `base.py:166` but never read by `_resolve_credentials`. Passwords cannot yet be overridden per-role via env var.
3. **`kb_client.py` derivation from profile** (medium priority) — `_PERSONA_FILE_MAP` (lines 99-111) and `fetch_all_role_credentials` (lines 621-630) maintain their own role lists and will drift.
4. **`auth_manager.py` failure message** — Lead with server-rendered banner text (`p-message`, `p-toast`, `[role="alert"]`) instead of the misleading JWT-timeout symptom. (Investigation Proposal 2 — defensive guard.)
5. **`_enforce_profile_invariant()` module-load hard-fail** — Deferred in favor of the CI-level invariant test added in this task. Same protection, staged rollout.

## Learning Consolidation

Purely additive — 4 new bullets across 4 existing topic files, no merges/retires/pruning. No `REVIEW: mutating change` label needed on PR.

| Rule (new bullet) | Topic file | Existing evidence_count → new |
|---|---|---|
| `auth-error-messaging` | `_learned/error-handling.md` | 2 → 3 |
| `credential-fallback-empty-default` | `_learned/config-validation.md` | 2 → 3 |
| `canonical-source-invariant-test` | `_learned/testing-patterns.md` | 3 → 4 |
| `investigation-to-task-file-spec` | `_learned/workflow-compliance.md` | 2 → 3 |

## Ecosystem Feedback (from Reflection)

- The `/error-investigation` → `/bmb:task` → `/bmb:build` → `/bmb:reflect` → `/bmb:archive` pipeline ran end-to-end in a single session with no rework. The investigation's Phase 5 parallel-proposer + critic pattern produced a spec precise enough that the task file needed zero rewrite before build.
- The build orchestrator's fast-path (single-phase, no sub-agent hop) was the right call for this well-specified Level 1 change. No evidence a fuller pipeline would have caught anything additional.
- **Suggestion**: a structured handoff format between `/error-investigation` output and `/bmb:task` input would eliminate manual copy-paste at the seam.
