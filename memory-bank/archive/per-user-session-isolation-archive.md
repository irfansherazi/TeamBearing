---
slug: per-user-session-isolation
feature: per-user-session-isolation
complexity: 4
status: COMPLETE
archived: 2026-08-07
---

# Archive: per-user-session-isolation — Per-User Session Isolation for vQA Runs

**Complexity**: Level 4
**Roadmap Feature**: `memory-bank/roadmap/per-user-session-isolation.md`
**Branch**: `feature/per-user-session-isolation`
**Base Ref**: `origin/main`
**Duration**: 2026-08-06 → 2026-08-07 (2 calendar days, 8 phases + closure)
**Commits**: 16 (from `87f4cc9` brainstorm → `ca53afb` reflection status flip)
**Diff Scope**: 53 files changed, +8696 / −186

---

## Summary

vQA's shared-singleton browser architecture is replaced with a first-class, JWT-scoped `Session` model that delivers true per-user isolation across every run path (Record a Demo, replay, AC-driven test execution). All 8 acceptance criterion families (AC-ENTRY, AC-HAPPY, AC-ERROR, AC-ASYNC — 23 individual ACs) are implemented and verified by 12 new test files. The feature ships behind `SESSION_ISOLATION_ENABLED` with a three-stage rollout plan (off → N=1 → N=4→8).

The original scope was fully delivered. Four post-BUILD_COMPLETE integration-wiring gaps were caught, documented in the task file's Deviations section, and closed in a single follow-up commit (`9b14e83`) within the same task cycle — no regressions, no scope creep.

---

## What Was Delivered

### Backend

- **`backend/session/`** — new subsystem, 5 modules with clean boundaries: `models.py` (Session dataclass + state machine), `manager.py` (asyncio-lock-guarded `SessionManager` with `add_active_run_id`/`remove_active_run_id`), `allocator.py` (lazy `DisplayAllocator` for Xvfb + x11vnc + websockify triplets), `lifecycle.py` (7-step `terminate()` sequence), `nginx_map.py` (`/var/run/vqa/sessions.map` projection).
- **`backend/browser/context.py`** — `SessionBrowserManager` refactor delivered as **Phase 0** with `__legacy_singleton__` backward-compat stub. Phase 4 removed the stub and converted every caller to session-scoped lookup.
- **`backend/auth/`** — `SsoValidator.validate_token()` requires `exp`, `jti`, `vc_id` and enforces `MAX_JWT_TTL_SECONDS=3600`; new `revocation.py` `RevokedJtiSet` (in-memory LRU, TTL-scoped); new `cookies.py` centralizes HttpOnly/Secure/SameSite=Lax flag logic.
- **`backend/api/routes.py`** — `POST /session/start`, `/session/rebind` (reissues cookie with `Max-Age = new_jwt.exp - now`), `/session/stop`; `execute_single`, `_execute_run`, `_execute_linear_run`, and `execute_batch` all wire the caller's `Session` via `SessionManager.add_active_run_id()` / `remove_active_run_id()` and enforce the `vqa_session` cookie when `SESSION_ISOLATION_ENABLED` is on.
- **`backend/kb/writer.py`** — `KBWriter.append_with_lock()` (existing) + new `append_jsonl_with_lock()` guard every KB write with `fcntl.flock` (5s deadline, sidecar fallback on timeout, WARN log). Every entry stamped `recorded_by: <session.user_email>` and `recorded_at: <iso8601>`.
- **`backend/engine/human_takeover.py`** — all four KB writers (`_save_to_learned_workflows`, `_append_to_kb_staging`, `_write_to_vsuite_actions_kb`, `_save_combined_hitl_entry`) plus `persist_user_guidance` route through `KBWriter` with `recorded_by` resolved from the run's session.
- **WebSocket topology** — additive: existing `/ws/{run_id}` and `/ws/codegen/{codegen_id}` (renamed from `session_id` to disambiguate) keep contracts, gated by cookie + `Origin` check + `run.session_id == cookie.session_id`. New `/ws/session/{session_id}` is the long-lived session-control channel authenticated by the HttpOnly cookie in the handshake (JWT is NOT carried on the WS). Server-side heartbeat (15s ping / 15s timeout) is the authoritative teardown signal.

### Infrastructure

- **`docker/supervisord.conf`** — becomes a template rendered by `docker/entrypoint.sh` from `MAX_CONCURRENT_SESSIONS`. Pre-declares `[program:xvfb_1..N]`, `[program:x11vnc_1..N]`, `[program:websockify_1..N]` with `autostart=false` so `DisplayAllocator` starts/stops triplets via `supervisorctl` on demand.
- **In-container nginx sidecar** — multiplexes `/vnc/<session_id>/*` (noVNC static) and `/websockify/<session_id>` (WS proxy) to the per-session port.
- **ALB config** — path-prefix routing (`/vnc/*`, `/websockify/*`) in a single `deploy.sh` edit; Fargate memory bumped for the multi-display container.

### Frontend

- **`SessionContext`** (mounted between `AuthProvider` from FEAT-048 and `AppShell`, with runtime guard that throws if mounted outside `AuthProvider`).
- **`useSessionWebSocket`** — long-lived `/ws/session/{id}` client with heartbeat handling.
- **`useRebindTimer`** — schedules `POST /session/rebind` at `next_rebind_by`.
- **`useOptionalSession()`** — fallback hook for legacy/singleton code paths.
- **Capacity-reached full-page state** with 15s auto-retry when `POST /api/session/start` returns 409.
- **`SessionStatusIndicator`** header dot; **`TakeoverPanel`** / **`LiveBrowser`** now prefer `session.novncUrl` when a session is attached, falling back to run-status prop for the singleton/legacy path.

### Tests (12 new files)

`tests/test_session_manager.py`, `test_session_routes.py`, `test_session_isolation.py`, `test_display_allocator.py`, `test_session_browser_manager.py`, `test_kb_writer_concurrency.py`, `test_jwt_hardening.py`, `test_e2e_websocket_cors.py`, `test_rebind.py`, `test_vnc_api.py`, `test_vnc_url_builder.py`, `test_logging_config.py`; plus `SessionContext.test.tsx`, `useRebindTimer.test.tsx`, `useSessionWebSocket.test.tsx` frontend unit tests.

---

## Phase Timeline

| Phase | Commit | Scope |
|---|---|---|
| Brainstorm | `87f4cc9` | Level 4 design approved: 15 ADRs, feature + task + creative docs |
| 0 | `d347810` | `SessionBrowserManager` backward-compat refactor (isolated PR-shaped commit) |
| 1 | `de1f636`, `7c67692` | `SessionManager`, `DisplayAllocator`, auth hardening, infra scaffolding |
| 2 | `cfb2ef0` | Session routes, WS auth, cookie flow, tightened CORS |
| 3 | `023a5df` | `vnc_builder` per-session URLs, ALB path-prefix, Fargate memory bump |
| — | `d7f582f` | Auto-build initialization for Phases 3–7 |
| 4 | `8201e6a` | Remove `__legacy_singleton__`, wire execute endpoints to session |
| 5 | `5d16f53` | `KBWriter.append_with_lock` + `recorded_by` attribution |
| 6 | `1655cdb` | Frontend `SessionContext` + hooks + session isolation tests |
| 7 | `b8c6722`, `81c3110` | JSON logging swap + BUILD_COMPLETE + logging config tests |
| Closure | `49b948f`, `9b14e83` | Deviation report + 4 post-BUILD_COMPLETE gaps closed |
| Reflect | `76a66a0`, `ca53afb` | Reflection + task status flip to REFLECTION_COMPLETE |

Phases 0–2 ran on manual `/bmb:build` rhythm; Phases 3–7 ran under `/bmb:auto-build`. See the reflection for a detailed assessment of the split.

---

## Deviations (all closed within the task cycle)

Four post-BUILD_COMPLETE gaps were surfaced and closed in commit `9b14e83`:

1. **`execute_single` / `_execute_run` / `_execute_linear_run`** — didn't call `SessionManager.add_active_run_id()` / `remove_active_run_id()`, so `session.active_run_ids` was always empty. AC-ENTRY-3 gap. → wired.
2. **`execute_batch`** — didn't enforce the `vqa_session` cookie when `SESSION_ISOLATION_ENABLED=true`, bypassing the isolation layer. → cookie enforcement + `add_active_run_id` added.
3. **`human_takeover.py`** — 4 KB writers wrote directly to files, bypassing `KBWriter.append_with_lock`. AC-HAPPY-2 gap for the human-takeover path. → all four routed through `KBWriter`; `KBWriter.append_jsonl_with_lock` added for the JSONL staging file.
4. **`LiveBrowser` / `TakeoverPanel`** — read `novnc_url` from the run-status prop, not `useSession()`. → both call `useOptionalSession()` and prefer `session.novncUrl` when attached.

**ADR-documented deviations from stated project standards** (these are intentional trade-offs, not gaps):

- **`CLAUDE.md`'s "OpenTelemetry First"** — the codebase has zero OTel SDK imports; this feature ships structured JSON logs via stdlib `JsonFormatter` + CloudWatch Metric Filters + Alarms. Bootstrap OTel is deferred as follow-up work. Documented in the creative doc.
- **`productBrief.md`'s single `settings.novnc_port`** — superseded by the session-scoped URL schema (`/vnc/<session_id>/vnc.html?path=websockify/<session_id>`). Updated in Phase 3.

---

## Rollout Plan (three-stage kill switch)

Behind `SESSION_ISOLATION_ENABLED` (default: `false` in `.env.example`). All three stages require a container restart to pick up config changes.

| Stage | `SESSION_ISOLATION_ENABLED` | `MAX_CONCURRENT_SESSIONS` | Verify |
|---|---|---|---|
| 1 | `false` | — | Deploy → 24h burn-in on the pre-refactor singleton path (backward-compat). Golden 10 regression benchmark must pass (AC-HAPPY-5). |
| 2 | `true` | `1` | 48h verify: all new machinery runs, single-session semantics. Watch KB `recorded_by` attribution, `fcntl.flock` timeouts, nginx-map projection. |
| 3 | `true` | `4` → `8` | Bump to 4, monitor 1 week; bump to 8 if memory + latency support it. |

**Kill-switch semantics**: with `SESSION_ISOLATION_ENABLED=false`, all `/api/session/*` routes remain wired but the execute endpoints fall through to the `__legacy_singleton__` code path (removed in Phase 4 — this actually means the pre-refactor singleton behavior emulated by `useOptionalSession()` returning `null` on the frontend and the backend routing runs through the singleton `SessionBrowserManager`). Verified by AC-HAPPY-5.

---

## Learning Consolidation

Additive-only — no rule merges/retirements/expiries/prunes.

| Learning | Consolidation Action | File |
|---|---|---|
| architecture-sequencing | APPEND (Phase 0 backward-compat stub pattern; promotes rule from `low` → `medium` on evidence_count 2 → 3) | `_learned/phase-zero-checkpoint.md` |
| kill-switch-rollout | APPEND (three-stage flag pattern + container-restart documentation requirement) | `_learned/feature-flag-rollout.md` |
| integration-wiring | CREATE | `_learned/integration-wiring.md` |
| observability-standards | CREATE | `_learned/observability-standards.md` |

`memory-bank/agent-rules-index.md` may need regeneration via `/bmb:rules-index` before the next `/bmb:plan` or `/bmb:build` run to surface the two new files.

---

## Follow-Up Work

**Explicitly deferred out of scope** (tracked as separate future work):

- **Full OpenTelemetry bootstrap** — structured JSON logs are the current-cycle deliverable; OTel SDK + collector + traces is a separate feature.
- **Prometheus client library + scrape endpoint.**
- **Per-user KB fragmentation** — KB stays shared; multi-user attribution is the current-cycle deliverable.
- **Cross-worker session sync** — uvicorn `--workers 1` is a hard invariant (`supervisord.conf:115`); Playwright is not fork-safe.
- **Persistent session state across container restarts.**
- **Admin impersonation of vQA users at the auth layer** — vQA's "ghost login" is a vSuite-level action inside a run, not a vQA-auth concept.
- **Migration of `deploy.sh` inline secrets to AWS Secrets Manager.**

**Advisory hygiene surfaced during archive**:

- `.gitignore` gap: `storage/chromadb/.last_guidance_mtime__*` and `memory/auth_states/*.png` appear as dirty in `git status` after the test suite runs. Consider adding these paths to `.gitignore` (called out in the reflection).

---

## References

- **Roadmap feature**: `memory-bank/roadmap/per-user-session-isolation.md`
- **Task file**: `memory-bank/tasks/per-user-session-isolation.md`
- **Creative doc (15 ADRs)**: `memory-bank/creative/per-user-session-isolation-design.md`
- **Reflection**: `memory-bank/reflection/per-user-session-isolation-reflection.md`
- **Base ref**: `origin/main` (0 behind, 16 ahead at archive time)
- **First commit**: `87f4cc9` (brainstorm, 2026-08-06)
- **Last commit**: `ca53afb` (reflection status flip, 2026-08-07)
