---
slug: per-user-session-isolation
feature: per-user-session-isolation
status: COMPLETE
---

# per-user-session-isolation: Per-User Session Isolation for vQA Runs

**Complexity**: Level 4
**Status**: COMPLETE
**Roadmap**: per-user-session-isolation
**Branch**: feature/per-user-session-isolation
**Worktree**: N/A (working in primary checkout — worktrees not used for this task)
**Reflection**: memory-bank/reflection/per-user-session-isolation-reflection.md
**Archived**: memory-bank/archive/per-user-session-isolation-archive.md
**Completed**: 2026-08-07

## Task Description

vQA currently runs a single shared Playwright browser exposed over a single noVNC stream (port 6080 in-container, `/vnc.html` + `/websockify` on the ALB). When user A starts a "Record a Demo" and user B logs in from a different machine and clicks "Record a Demo", user B's frontend attaches to the same live browser — B sees A's session, and both users' actions collide in one Playwright instance. This is a session-isolation gap: vQA has no first-class concept of "the browser session belongs to the logged-in user."

The gap is systemic, not confined to Record a Demo — every vQA run path (Record a Demo, replay, AC-driven test execution) sits on top of the same shared singleton `BrowserManager` in `backend/browser/context.py` and the same singleton noVNC pipeline in `docker/supervisord.conf`. This feature eliminates the shared-singleton architecture and introduces a first-class `Session` keyed to the JWT-authenticated user.

**Approved architecture** (see `memory-bank/creative/per-user-session-isolation-design.md` for the full design record with all considered approaches, tradeoffs, and ADRs):

1. **New backend subsystem** at `backend/session/` — `SessionManager` (state machine + asyncio-lock-guarded transitions), `DisplayAllocator` (lazy, capacity-bounded pool of `:1..:N` displays and ports `60{80+N}` under a supervisord-static-config / supervisorctl-dynamic-lifecycle pattern), `Session` dataclass, `lifecycle.terminate()` 7-step teardown sequence, `nginx_map.py` projection to `/var/run/vqa/sessions.map`.
2. **Multi-display container** — `docker/supervisord.conf` becomes a template rendered by `docker/entrypoint.sh` from `MAX_CONCURRENT_SESSIONS`; pre-declares `[program:xvfb_1..N]`, `[program:x11vnc_1..N]`, `[program:websockify_1..N]` with `autostart=false` so `DisplayAllocator` starts/stops triplets via `supervisorctl` on demand.
3. **In-container nginx sidecar** — multiplexes `/vnc/<session_id>/*` (noVNC static) and `/websockify/<session_id>` (WebSocket proxy) to the right per-session port. ALB config changes to path-prefix routing (`/vnc/*`, `/websockify/*`) in one `deploy.sh` edit.
4. **Session-scoped `SessionBrowserManager`** — refactor of the module-level singleton `BrowserManager` in `backend/browser/context.py` (953 lines, LangGraph-wide coupling). Landed as **Phase 0** (its own PR) with a backward-compat `__legacy_singleton__` stub so all existing call sites keep working; Phase 4 removes the stub and converts every caller to session-scoped lookup.
5. **Auth hardening** — `SsoValidator.validate_token()` requires `exp`, `jti`, `vc_id` and enforces `MAX_JWT_TTL_SECONDS=3600` at the vQA boundary; new `backend/auth/revocation.py` `RevokedJtiSet` (in-memory LRU, TTL-scoped by JWT `exp`); new `backend/auth/cookies.py` centralizes HttpOnly/Secure/SameSite=Lax flag logic. `POST /session/rebind` re-issues the cookie with `Max-Age = new_jwt.exp - now` (not the original JWT's expiry) and updates `session.jwt_valid_until`; periodic tick (every `SESSION_TICK_INTERVAL_SECONDS=30`) terminates sessions where `jwt_valid_until + REBIND_GRACE_SECONDS(60) <= now` — worst-case ~90s past JWT expiry.
6. **WebSocket topology** — additive, not replacement. Existing `/ws/{run_id}` (log stream) and `/ws/codegen/{session_id}` (codegen scratch — path variable renamed to `codegen_id` to disambiguate) keep their contracts, gated by cookie + `Origin` check + `run.session_id == cookie.session_id`. New `/ws/session/{session_id}` is a long-lived session-control channel authenticated by the HttpOnly cookie in the handshake (JWT is **not** carried on the WS — the previously proposed first-frame JWT pattern was withdrawn during security review). Server-side heartbeat (15s ping / 15s timeout) is the authoritative teardown signal; `beforeunload` is a best-effort optimization.
7. **KB write attribution** — every autorecord "Done" write to `knowledge/blueprints/learned_workflows.json`, `knowledge/vSuite-actions.md`, `knowledge/human_guidance.md` goes through `KBWriter.append_with_lock()` using `fcntl.flock` (5s deadline, sidecar fallback on timeout, WARN log). Every entry stamped `recorded_by: <session.user_email>` and `recorded_at: <iso8601>`. Last-write-wins under lock; no per-user KB fragmentation (KB stays a shared team asset — the "reusable artifacts" value prop).
8. **Frontend** — new `SessionContext` (mounted between existing `AuthProvider` from FEAT-048 and `AppShell`, with a runtime guard that throws if mounted outside `AuthProvider`), `useSessionWebSocket` (long-lived `/ws/session/{id}` client + heartbeat handling), `useRebindTimer` (schedules `POST /session/rebind` at `next_rebind_by`), capacity-reached full-page state with auto-retry, `SessionStatusIndicator` header dot, refactored `TakeoverPanel` / `LiveBrowser` to read `novnc_url` from session context (not per-run status).
9. **Rollout** — behind `SESSION_ISOLATION_ENABLED` kill switch. Stage 1: deploy with flag off (fallback to pre-refactor singleton path, 24h verify). Stage 2: flag on, `MAX_CONCURRENT_SESSIONS=1` (all new machinery runs, single-session semantics, 48h verify). Stage 3: bump to 4, monitor 1 week, bump to 8 if memory + latency support it.

**Non-goals (explicitly deferred):**
- Full OpenTelemetry bootstrap (ADR: this feature ships structured JSON logs + CloudWatch Metric Filters + Alarms; OTel is a follow-up).
- Prometheus client library / scrape endpoint.
- Distributed traces across LLM providers.
- Per-user KB fragmentation (KB stays shared; multi-user attribution only).
- Cross-worker session sync (uvicorn `--workers 1` is enforced by `supervisord.conf:115` because Playwright is not fork-safe; single-worker is a hard invariant we rely on).
- Persistent session state across container restarts (browsers die with the container; nothing to recover).
- Admin impersonation of vQA users (`Session.ghosted_by` was speculatively proposed and withdrawn — vQA's "ghost login" is a vSuite-level action inside a run, not a vQA-auth-level concept).
- Migration of `deploy.sh` inline secrets to AWS Secrets Manager (out of scope; tracked as a follow-up task).

**Deviation flags carried by this task:**
- `productBrief.md`'s "single `settings.novnc_port`" description is superseded by the session-scoped URL schema (`/vnc/<session_id>/vnc.html?path=websockify/<session_id>`). Update landed as part of Phase 3.
- `CLAUDE.md`'s "OpenTelemetry First" observability standard is aspirational — the current codebase runs plain-text `basicConfig` logging (`backend/main.py:80`) with zero OTel/Prometheus deps. This feature ships structured JSON logs as an explicit ADR-documented deviation; full OTel bootstrap is future work.

## User Journey Definition

**Feature Type**: End-User Feature
**Creative Phase Required**: Yes — Architecture (completed during /bmb:brainstorm, recorded in `memory-bank/creative/per-user-session-isolation-design.md`)

### Invocation Method (End-User Features)
- **Location**: The vQA dashboard root (post-authentication). Session bootstrap fires implicitly on dashboard mount; there is no user-facing "Start Session" button. The user-visible entry points that this feature isolates are:
  - **"Record a Demo" button** in the TakeoverPanel (`frontend/src/components/TakeoverPanel.tsx`) — the concrete case from the originating bug report.
  - **"Run" button** on any Playwright test row in the Playwright Test Library (`frontend/src/pages/PlaywrightTests.tsx` — from FEAT-051).
  - **"Execute" button** in the AC-driven run flow (Jira ticket → run).
- **Element**: See above — three distinct existing UI entry points, all of which now bind to the caller's session automatically.
- **Visibility**: Always visible post-authentication. Session bootstrap runs on mount; if capacity is reached, the entire dashboard is replaced by the capacity-reached full-page state until a slot frees up.
- **Navigation**: From login (FEAT-048) → dashboard root → `SessionProvider` mounts → `POST /api/session/start` → on 200, dashboard renders normally with `useSession()` context available; on 409 capacity, capacity-reached page with auto-retry every 15s.

### Success Criteria (End-User Features)
- **User sees**:
  - When two users are logged into vQA from different machines and both click "Record a Demo", each user's noVNC iframe shows **only their own** browser session — the other user's actions are invisible.
  - When capacity is reached, the requesting user sees a full-page "vQA is at capacity. N users active. Estimated wait: ~M minutes." with a live-updating countdown and a "Retry now" button.
  - On JWT-refresh failure inside the grace window, a small banner "Session refresh failed — you'll be logged out in Xs" counting down.
  - On session termination (JWT expired, admin delete, container drain, failure), a toast with the reason and a redirect to `/login` (except container drain, which stays on page with a "please refresh in 30s" message).
- **User can verify at**:
  - The green/yellow/red `SessionStatusIndicator` dot in the header shows the current session state at all times.
  - The `Set-Cookie: vqa_session=...` response header on `POST /api/session/start` (and its re-issue on every successful `POST /api/session/rebind`) can be verified in browser DevTools → Network.
  - The `X-Request-Id` response header on every API call gives a `trace_id` grep-able in CloudWatch Logs Insights.
  - The autorecord entry produced by hitting "Done" carries the recording user's email in `recorded_by` (visible when inspecting `knowledge/blueprints/learned_workflows.json` in the container).
- **Data persisted**:
  - `Session` state: in-memory in the single uvicorn worker (no persistence — matches the "browsers die with the container" invariant).
  - Nginx session-to-port map: `/var/run/vqa/sessions.map` (derived projection, not truth source, auto-reloaded via inotify or manual `nginx -s reload`).
  - KB writes: same files as today (`knowledge/blueprints/learned_workflows.json`, `knowledge/vSuite-actions.md`, `knowledge/human_guidance.md`), now with `recorded_by` + `recorded_at` on every entry, guarded by `fcntl.flock` on `<file>.lock` sidecars.
  - CloudWatch Logs: structured JSON log lines for every session lifecycle event (`session.started`, `session.terminated`, `session.rebound`, `session.capacity_reached`, `session.allocator_leak`, `session.ws_heartbeat_timeout`, `session.jwt_expired`, `session.rebind_failed`, `session.origin_rejected`, `session.jti_revoked_hit`, `kb.write_lock_timeout`, `browser.launched`).
  - `RevokedJtiSet`: in-memory only (container restart wipes it — acceptable because container restart also kills every session).
- **Observable within**:
  - Session bootstrap: `POST /api/session/start` returns within 5s (supervisorctl-start p95 target).
  - Capacity retry: 15s ± jitter.
  - Rebind: within 60s grace window past `jwt_valid_until`.
  - Tab-close teardown: sub-second when `beforeunload` fires; otherwise 15s (heartbeat timeout) — heartbeat is the authoritative teardown contract.
  - Metric filter aggregation lag in CloudWatch: ~5 min (accepted tradeoff for the JSON-logs approach).

### NFR Verification (Infrastructure Features)
Not the primary feature type, but the following NFR-flavored checks are part of the acceptance surface (details in the Test Strategy section):
- **Test method**: Two-authenticated-clients Playwright E2E test (`tests/test_session_isolation.py`) + concurrent-writer pytest (`tests/test_kb_writer_concurrency.py`) + auth-boundary fuzz suite (`tests/test_jwt_hardening.py`, `tests/test_rebind.py`).
- **Success metrics**: `MAX_CONCURRENT_SESSIONS × ~700MB` peak memory + backend baseline under the target Fargate task memory; no `session.allocator_leak` events in a 24h staging load run; p95 `session.started → session_ready` latency < 5s.
- **Observable at**: CloudWatch Logs Insights queries on the `event` field; CloudWatch Metric Filter dashboards for `vqa_sessions_active`, `vqa_allocator_slots_in_use`, `vqa_capacity_rejections_total`.

### Acceptance Criteria
_The `## Specification` section below (authored by the Spec Writer Agent) contains the authoritative, prefixed acceptance criteria (`AC-ENTRY-*`, `AC-HAPPY-*`, `AC-ERROR-*`, `AC-ASYNC-*`). Summary preview:_
- AC-ENTRY-1: A logged-in user hitting the vQA dashboard root bootstraps a Session (or sees the capacity-reached page).
- AC-HAPPY-1: Two users concurrently running Record a Demo from different machines each see only their own browser session.
- AC-ERROR-1: Attempting to attach to another user's `/ws/{run_id}` with a valid-but-mismatched cookie is rejected with `close(4401)`.
- AC-ASYNC-1: `POST /session/rebind` re-issues the cookie with `Max-Age = new_jwt.exp - now`; sessions terminate at `jwt_valid_until + 60s` if rebind fails.

## Test Strategy

### Approach
- **Emphasis**: Balanced (unit for state machine + allocator, integration for auth boundary + WS handshake + KB writes, E2E for the concurrent-users acceptance scenario). Weighted toward integration/E2E because the *value* being delivered is cross-component isolation — pure unit tests of a `Session` dataclass wouldn't catch the singleton-refactor regressions this task is designed to eliminate.
- **Target test count**: ~35 total across all phases. Justification: 8 phases × ~4 tests/phase, weighted heavier on Phase 0 (`SessionBrowserManager` refactor — needs to prove backward-compat) and Phase 4 (final legacy-singleton removal — needs regression coverage for every LangGraph node that touches the browser manager).

### File Organization
- **New test files**:
  - `tests/test_session_browser_manager.py` — Phase 0 backward-compat + isolation (`id`-keyed instances, `DISPLAY=:N` env plumbing, per-instance cleanup).
  - `tests/test_session_manager.py` — Phase 1 state-machine transitions (all edges from Section 2 of the design), asyncio-lock atomicity.
  - `tests/test_display_allocator.py` — Phase 1 acquire/release under contention, cap-reached path, leak-on-supervisorctl-fail, reconciliation loop.
  - `tests/test_session_routes.py` — Phase 2 `POST /session/start`, `POST /session/rebind`, `DELETE /session/{id}`, `GET /session/{id}/status` (happy + CSRF/cookie/JWT edges).
  - `tests/test_jwt_hardening.py` — Phase 1 reject missing-`exp` JWTs, reject `>1h` TTL, reject revoked `jti`.
  - `tests/test_rebind.py` — Phase 2 rebind extends cookie Max-Age (verified via `Set-Cookie` header inspection), rebind past grace fails, rebind cross-user rejected.
  - `tests/test_session_isolation.py` — Phase 6 E2E acceptance: two authenticated clients start sessions, each gets a distinct `novnc_url`, neither can attach to the other's `/ws/{run_id}`; concurrent Record-a-Demo produces two KB entries with distinct `recorded_by`.
  - `tests/test_kb_writer_concurrency.py` — Phase 5 two writers racing on `learned_workflows.json` produce two valid entries under `fcntl.flock`; timeout-fallback creates a sidecar and emits `kb.write_lock_timeout`.
  - `tests/test_nginx_multiplex.py` — Phase 3 integration test that spins the container, allocates 2 sessions, and verifies `/vnc/<sid>/vnc.html` + `/websockify/<sid>` route to the right ports.
  - Frontend: `frontend/src/context/__tests__/SessionContext.test.tsx`, `useRebindTimer.test.ts`, `useSessionWebSocket.test.ts` — Phase 6.
- **Extend existing**:
  - `tests/test_vnc_url_builder.py` — Phase 3 update fixtures + assertions to new session-scoped URL format.
  - `tests/test_vnc_api.py` — Phase 3 add session-start fixture; assert URL contains `session_id` path.
  - `tests/test_e2e_websocket_cors.py` — Phase 2 add cookie/`Origin` fixtures; add negative tests for missing/mismatched `Origin`.

### What NOT to Test
- **Playwright browser fork-safety** — enforced by `supervisord.conf:123` (`--workers 1`); asserting it in a unit test would be a tautology.
- **PyJWT decode internals** — covered by upstream test suite; we test our `SsoValidator` wrapper's `require` / `MAX_JWT_TTL_SECONDS` enforcement, not RS256 signature math.
- **fcntl.flock kernel semantics** — stdlib guarantee; we test our `KBWriter.append_with_lock` wrapper's timeout + sidecar-fallback behavior.
- **Nginx internals** — we test that requests routed *through* nginx reach the right upstream port, not nginx's own request parsing.
- **CloudWatch Metric Filter regex matching** — verified out-of-band by AWS; we test that the JSON log lines emitted contain the fields the filters key on.
- **vcAPI RS256 signing behavior** — covered by FEAT-047; we assume validly-signed tokens from vcAPI and only test our validator's post-decode assertions.
- **Frontend Auth flow (login, MFA, JWT refresh with vcAPI)** — owned by FEAT-048; we test `SessionProvider`'s consumption of `useAuth().token`, not FEAT-048's implementation.
- **The specific `MAX_CONCURRENT_SESSIONS` value** — it's memory-bounded and env-configurable; we test cap-reached behavior parametrically, not the number.

### Per-Phase Test Guidance
- **Phase 0** (`SessionBrowserManager` refactor with backward-compat singleton): ~6 tests. Existing `BrowserManager` tests pass unchanged. New tests verify: (a) two `SessionBrowserManager(id=...)` instances with different ids are fully isolated (no shared state, no cross-contamination), (b) `DISPLAY=:N` env passed to Playwright, (c) per-instance `close()` releases only that instance's resources, (d) the `__legacy_singleton__` compat stub returns the same instance across calls (proves back-compat).
- **Phase 1** (SessionManager + DisplayAllocator + auth hardening + templated supervisord + nginx sidecar): ~10 tests. State-machine transitions (7 states from the design × happy + error paths, sampled), allocator acquire under contention, cap-reached returns `capacity_reached` structured result, JWT hardening (missing `exp`, `>1h` TTL, revoked `jti`), reconciliation loop catches leaks.
- **Phase 2** (session routes + WS auth + cookie flow): ~6 tests. `POST /session/start` sets cookie with correct flags (production vs. dev), `POST /session/rebind` re-issues cookie with new `Max-Age` verified via `Set-Cookie` header, `Origin` rejection on WS handshake, cookie mismatch rejection on `/ws/{run_id}`, cross-user rebind rejected.
- **Phase 3** (per-session VNC URLs + ALB path change + Fargate memory bump): ~4 tests. `build_url(session_id=...)` produces the new format, existing tests updated. `test_nginx_multiplex.py` proves the in-container routing works end-to-end for 2 concurrent sessions.
- **Phase 4** (remove `__legacy_singleton__`, wire every run/execute path through session): ~3 tests. Every `POST /execute*` endpoint requires a valid session cookie; runs launched with `DISPLAY=:{session.display_num}`; orphan-run guard fires if a run's `session_id` no longer exists.
- **Phase 5** (KB write attribution + `fcntl.flock`): ~3 tests. Two writers race, both entries land with distinct `recorded_by`; timeout produces sidecar + WARN log; markdown appends carry `<!-- recorded_by: ... -->` prefix.
- **Phase 6** (frontend integration): ~5 tests (frontend `SessionContext.test.tsx`, `useRebindTimer.test.ts`, `useSessionWebSocket.test.ts` + E2E `test_session_isolation.py` covering the concurrent-users acceptance).
- **Phase 7** (observability + load test + rollout): no unit tests — this phase is a load-test run and rollout dry-run against staging, not code. Deliverable is the 24h load-test log analysis + the CloudWatch Alarms wired up.

## Implementation Roadmap

### New Source Files (pin path + extension)
Backend (new):
- [ ] `backend/session/__init__.py` — public API (`SessionManager`, `get_session_manager()`, `Session`, `SessionState`)
- [ ] `backend/session/manager.py` — `SessionManager` singleton, state-machine engine, sessions dict, asyncio lock, periodic tick task
- [ ] `backend/session/models.py` — `Session` dataclass + `SessionState` enum
- [ ] `backend/session/allocator.py` — `DisplayAllocator` (pool, supervisorctl subprocess invocations)
- [ ] `backend/session/nginx_map.py` — atomic `/var/run/vqa/sessions.map` writer
- [ ] `backend/session/lifecycle.py` — `terminate()` 7-step sequence
- [ ] `backend/auth/revocation.py` — `RevokedJtiSet` (bounded, TTL-scoped)
- [ ] `backend/auth/cookies.py` — `issue_session_cookie`, `read_session_cookie`, flag logic
- [ ] `backend/api/session_routes.py` — `POST /session/start`, `POST /session/rebind`, `DELETE /session/{id}`, `GET /session/{id}/status`, `WS /ws/session/{id}`
- [ ] `backend/logging_config.py` — `JsonFormatter`, `trace_id` `ContextVar`, `LOG_FORMAT=json|text` selector
- [ ] `backend/kb/writer.py` — `KBWriter.append_with_lock` with `fcntl.flock`

Backend (extend):
- [ ] `backend/browser/context.py` — refactor `BrowserManager` → `SessionBrowserManager(id=...)` with `__legacy_singleton__` compat (Phase 0)
- [ ] `backend/browser/vnc_builder.py` — `build_url(session_id, ...)` gains required arg; production URL format changes
- [ ] `backend/auth/sso.py` — `SsoValidator.validate_token()` gets `options={"require": ["exp", "jti", "vc_id"]}`, `MAX_JWT_TTL_SECONDS` post-decode check, revocation set check
- [ ] `backend/api/routes.py` — WS handlers add cookie + `Origin` check + `run.session_id` match; all `POST /execute*` handlers stamp `run.session_id`; rename `/ws/codegen/{session_id}` path variable to `codegen_id`
- [ ] `backend/api/auth_middleware.py` — populate `request.state.session` from cookie
- [ ] `backend/engine/human_takeover.py` — read `session.user_email` for KB attribution; pass `session.display_num` to autorecord bridge
- [ ] `backend/kb/*.py` — all writers route through `KBWriter.append_with_lock`
- [ ] `backend/main.py` — swap `basicConfig` to `JsonFormatter` (conditional on `LOG_FORMAT`); tighten CORS `allow_headers` / `allow_methods`; add `SessionManager.startup()` / `drain_all()` to lifespan
- [ ] `backend/config/__init__.py` — add 8 env vars: `MAX_CONCURRENT_SESSIONS`, `MAX_JWT_TTL_SECONDS`, `SESSION_COOKIE_NAME`, `REBIND_GRACE_SECONDS`, `SESSION_TICK_INTERVAL_SECONDS`, `SESSION_RECONNECT_GRACE_SECONDS`, `WS_HEARTBEAT_INTERVAL_SECONDS`, `WS_HEARTBEAT_TIMEOUT_SECONDS`, `SESSION_ISOLATION_ENABLED`, `LOG_FORMAT`

Infra (new):
- [ ] `docker/nginx.conf` — session-multiplexing config reading `sessions.map`, serving `/vnc/<sid>/*` + proxying `/websockify/<sid>`
- [ ] `docker/entrypoint.sh` — renders `supervisord.conf` from `MAX_CONCURRENT_SESSIONS`, then `exec supervisord`
- [ ] `docker/supervisord.conf.template` — templated version of the current file with `xvfb_N`, `x11vnc_N`, `websockify_N` slots + nginx entry

Infra (extend):
- [ ] `Dockerfile` — add `nginx` package + copy `nginx.conf` and `entrypoint.sh`
- [ ] `deploy.sh` — ALB rule change (`/vnc/*`, `/websockify/*`), Fargate task memory bump (target `6144` MB; final value depends on `MAX_CONCURRENT_SESSIONS × ~700MB` sizing)

Frontend (new):
- [ ] `frontend/src/context/SessionContext.tsx` — `SessionProvider` + `useSession()` hook; runtime guard for `AuthProvider` nesting
- [ ] `frontend/src/hooks/useSessionWebSocket.ts` — long-lived session-control WS client
- [ ] `frontend/src/hooks/useRebindTimer.ts` — rebind scheduler at `next_rebind_by`
- [ ] `frontend/src/api/session.ts` — typed clients: `startSession`, `rebindSession`, `deleteSession`
- [ ] `frontend/src/components/SessionStatusIndicator.tsx` — header status dot
- [ ] `frontend/src/pages/CapacityReached.tsx` — full-page capacity state

Frontend (extend):
- [ ] `frontend/src/main.tsx` (or root shell) — mount `SessionProvider` between `AuthProvider` and `AppShell`
- [ ] `frontend/src/components/TakeoverPanel.tsx` — read `novnc_url` from `useSession()` not run status
- [ ] `frontend/src/components/LiveBrowser.tsx` — same
- [ ] `frontend/src/context/AuthContext.tsx` — expose `token`, `refresh()`, `logout()` hooks in the shape `SessionProvider` consumes (verify existing FEAT-048 exports match; extend if needed)

### Phases
- [x] Phase 0: `SessionBrowserManager` refactor with `__legacy_singleton__` backward-compat stub (its own PR — merges before any other phase touches main)
- [x] Phase 1: `SessionManager` + `DisplayAllocator` + templated `supervisord.conf` + nginx sidecar + auth hardening (`SsoValidator` `require`/TTL, `RevokedJtiSet`, cookies module)
- [x] Phase 2: Session-scoped WS auth + `POST /session/start` / `rebind` / `delete` + cookie flow + tightened CORS + WS `Origin` validation
- [x] Phase 3: `vnc_builder` per-session URLs + ALB path-prefix change + Fargate memory bump (safe secret-handling protocol for `deploy.sh` edits)
- [x] Phase 4: Remove `__legacy_singleton__`; wire every run/execute path through session (`DISPLAY=:{session.display_num}` plumbing); orphan-run guards
- [x] Phase 5: KB write attribution + `fcntl.flock` + concurrency tests
- [x] Phase 6: Frontend integration (SessionContext, hooks, capacity-reached UX, session status indicator, refactor TakeoverPanel/LiveBrowser)
- [x] Phase 7: Observability (JSON logging swap, CloudWatch Metric Filters + Alarms), load test (5 stages from Section 5 of the design), staged rollout behind `SESSION_ISOLATION_ENABLED`

## Creative Phases

- [x] Architecture design → complete (see `memory-bank/creative/per-user-session-isolation-design.md`)

---

## Specification

**Feature Type**: End-User Feature
*Note: This feature is a cross-cutting user-visible isolation refactor with heavy infrastructure content (multi-display container, nginx sidecar, auth hardening, KB attribution). Classified as End-User because the visible outcome — "two concurrent users see only their own browser session" — is the acceptance surface. Boundary/lifecycle checks (state-machine transitions, heartbeat teardown, drain, allocator reconciliation, rebind cookie re-issue) are folded into `AC-ASYNC-*` prefixes; kill-switch and legacy-path behavioral toggles are folded into `AC-HAPPY-*`; the taxonomy-forbidden `AC-EDGE-*` prefix is deliberately avoided (canonical mapping per `taxonomy://AC_PREFIX`).*

**Primary Persona**: QA Lead / Automation Engineer, Product Manager, Human-in-the-Loop Operator (any concurrently logged-in vQA user running Record a Demo, Playwright Test Library "Run", or AC-driven "Execute").
**Creative Exploration Needed**: No — architecture design is complete (see `memory-bank/creative/per-user-session-isolation-design.md`, 15 ADRs approved section-by-section during `/bmb:brainstorm`). This spec is the authoritative acceptance surface.

### Invocation Method

- **Location**: The vQA dashboard root, post-authentication (FEAT-048 `AuthProvider` has already resolved a valid JWT). Session bootstrap fires implicitly on `SessionProvider` mount — there is no user-facing "Start Session" button. The user-visible entry points that this feature isolates:
  - **"Record a Demo"** button in `frontend/src/components/TakeoverPanel.tsx` (the originating bug: two users clicking this concurrently attached to the same live browser).
  - **"Run"** button on any Playwright test row in `frontend/src/pages/PlaywrightTests.tsx` (FEAT-051).
  - **"Execute"** button in the AC-driven run flow (Jira ticket → run, invoked from the dashboard's ticket entry field).
- **Element**: Three distinct existing UI entry points listed above. This feature adds no new user-facing button; instead, every existing entry point silently binds to the caller's session cookie.
- **Visibility**: Always visible post-authentication. If `MAX_CONCURRENT_SESSIONS` capacity is reached at bootstrap time, the entire dashboard is replaced by the full-page `CapacityReached` state (`frontend/src/pages/CapacityReached.tsx`) until a slot frees up.
- **Navigation**: Login (FEAT-048) → dashboard root → `<AuthProvider>` resolves JWT → `<SessionProvider>` mounts → `POST /api/session/start` (JWT in `Authorization: Bearer`) → on 200, `Set-Cookie: vqa_session=...` and dashboard renders with `useSession()` context; on 409 capacity, `CapacityReached` full-page state with auto-retry every 15s ± jitter.
- **Confidence**: HIGH — mount order (`<AuthProvider><SessionProvider><AppShell/></SessionProvider></AuthProvider>`), transport (JWT at 3 HTTPS boundaries, cookie everywhere else), and per-entry-point behavior were all approved during design.

### Success Criteria

- **User sees**:
  - When two users are logged into vQA from different machines and both click "Record a Demo" concurrently, each user's noVNC iframe (`frontend/src/components/LiveBrowser.tsx`) renders **only their own** Playwright browser session; the other user's mouse movements, page loads, and Playwright actions are invisible to them.
  - When capacity is reached, the requesting user sees the `CapacityReached` full-page state with the copy `vQA is at capacity. {N} users active. Estimated wait: ~{M} minutes.`, a live-updating countdown, and a "Retry now" button.
  - On JWT rebind failure inside the grace window, a small banner reading `Session refresh failed — you'll be logged out in {X}s` with a live countdown.
  - On session termination for any reason (JWT expired, admin `DELETE /session/{id}`, container drain, heartbeat timeout, allocator failure), a toast with the reason and a redirect to `/login` — except container drain, which stays on the current page with the copy `Server is restarting. Please refresh in ~30s.`.
  - Every autorecord "Done" write to `knowledge/blueprints/learned_workflows.json`, `knowledge/vSuite-actions.md`, and `knowledge/human_guidance.md` visibly carries the recording user's email in the `recorded_by` field.
- **Verifiable at**:
  - **`SessionStatusIndicator`** header dot (`frontend/src/components/SessionStatusIndicator.tsx`) shows green (ATTACHED), yellow (rebinding / DETACHED_GRACE), or red (TERMINATING / TERMINATED) at all times.
  - **DevTools → Network → `POST /api/session/start`** response: `Set-Cookie: vqa_session=...; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<jwt.exp - now>`.
  - **DevTools → Network → `POST /api/session/rebind`** response: `Set-Cookie` re-issued with fresh `Max-Age = new_jwt.exp - now`.
  - **Every API response**: `X-Request-Id: <trace_id>` header, greppable in CloudWatch Logs Insights.
  - **The noVNC iframe** rendered on each machine streams only the caller's browser (verified by two concurrent users navigating to distinct URLs and observing only their own page).
  - **`knowledge/blueprints/learned_workflows.json`** inside the container: every entry has `recorded_by: <email>` + `recorded_at: <iso8601>`.
- **Data persisted**:
  - **`Session` state** — in-memory in the single uvicorn worker (`--workers 1` enforced by `docker/supervisord.conf:115`). No persistence; matches the "browsers die with the container" invariant.
  - **Nginx session-to-port map** — `/var/run/vqa/sessions.map` (derived projection, not truth). Auto-reloaded via inotify or manual `nginx -s reload`.
  - **KB writes** — same files as today (`knowledge/blueprints/learned_workflows.json`, `knowledge/vSuite-actions.md`, `knowledge/human_guidance.md`), now with `recorded_by` + `recorded_at` on every entry, guarded by `fcntl.flock` on `<file>.lock` sidecars.
  - **CloudWatch Logs** — structured JSON log lines (one per event) for: `session.started`, `session.ready`, `session.attached`, `session.terminated`, `session.rebound`, `session.capacity_reached`, `session.allocator_leak`, `session.ws_heartbeat_timeout`, `session.jwt_expired`, `session.rebind_failed`, `session.origin_rejected`, `session.jti_revoked_hit`, `kb.write_lock_timeout`, `browser.launched`.
  - **`RevokedJtiSet`** — in-memory only. Container restart wipes it; acceptable because container restart also kills every session (ADR-7).
- **Observable within**:
  - Session bootstrap: `POST /api/session/start` returns within 5s (supervisorctl-start p95 target).
  - Capacity retry cadence: 15s ± jitter.
  - Rebind window: within 60s grace past `jwt_valid_until`.
  - Tab-close teardown: sub-second when `beforeunload` fires; otherwise `WS_HEARTBEAT_TIMEOUT_SECONDS=15` (heartbeat is the authoritative teardown signal per ADR-10).
  - Metric filter aggregation lag in CloudWatch: ~5 min (accepted tradeoff per ADR-8).
- **Confidence**: HIGH — every observable listed above traces to a concrete backend file, structured log event, or DevTools-visible header approved in design.

### Data Persistence

Files, directories, and stores this feature touches:

| Location | Type | Written by | Truth source? |
|---|---|---|---|
| `SessionManager.sessions: dict[str, Session]` (in-memory, single uvicorn worker) | Runtime state | `backend/session/manager.py` | YES — session state authority |
| `/var/run/vqa/sessions.map` | File | `backend/session/nginx_map.py` (atomic write on ATTACHED / TERMINATED) | NO — projection of `SessionManager.sessions` for nginx |
| `RevokedJtiSet` (in-memory LRU, TTL-scoped by JWT `exp`) | Runtime state | `backend/auth/revocation.py` | YES until container restart |
| `knowledge/blueprints/learned_workflows.json` | File | `backend/kb/writer.py:KBWriter.append_with_lock` | YES — shared KB, per-entry `recorded_by` + `recorded_at` |
| `knowledge/vSuite-actions.md` | File | `KBWriter.append_with_lock` (markdown append with `<!-- recorded_by: ... -->` prefix) | YES — shared KB |
| `knowledge/human_guidance.md` | File | `KBWriter.append_with_lock` (markdown append with `<!-- recorded_by: ... -->` prefix) | YES — shared KB |
| `<kb-file>.lock` sidecar files | Ephemeral | `fcntl.flock` (advisory) | N/A — lock coordination only |
| `<kb-file>.sidecar-<timestamp>.jsonl` | File | `KBWriter` timeout-fallback path | YES — orphaned writes, requires human reconciliation |
| CloudWatch Logs group `/vqa/backend` | Managed | `backend/logging_config.py:JsonFormatter` to stdout, awslogs driver captures | YES — audit + metric-filter source |
| `Session` cookie `vqa_session=<session_id>` on client | Cookie (HttpOnly, Secure, SameSite=Lax, Path=/) | `backend/auth/cookies.py:issue_session_cookie` at `/session/start` and `/session/rebind` | YES — authorization token for all non-JWT endpoints |
| Response header `X-Request-Id: <trace_id>` on every API call | Header | `backend/logging_config.py` middleware | YES — request correlation |

**Explicitly NOT persisted:**
- Session state across container restarts (ADR: browsers die with the container).
- Per-user KB fragmentation (KB stays shared — the "reusable artifacts" value prop per productBrief.md).
- JWTs themselves (only used at 3 HTTPS boundaries, never stored server-side beyond the request-scoped `RevokedJtiSet` check).

### Environment Variables Introduced

All 10 new env vars are read at startup by `backend/config/__init__.py`. Defaults are chosen so a fresh container with no `.env` overrides runs safely in Stage 1 rollout (kill switch off).

| Variable | Default | Notes |
|---|---|---|
| `MAX_CONCURRENT_SESSIONS` | `4` | Upper bound on simultaneous active sessions. Sized by container memory (`N × ~700MB` browser+display + backend baseline). Bump to `8` in Stage 3 rollout if memory + latency support it. Also templates `docker/supervisord.conf.template` at container start. |
| `MAX_JWT_TTL_SECONDS` | `3600` | Post-decode enforcement of `(exp - now) <= this value` in `SsoValidator`. Rejects forever-tokens if vcAPI ever omits `exp` (defense-in-depth per ADR-6). Coordinate with vcAPI SSO owner before increasing. |
| `SESSION_COOKIE_NAME` | `vqa_session` | HttpOnly cookie name issued at `/session/start` and re-issued at `/session/rebind`. |
| `REBIND_GRACE_SECONDS` | `60` | Additional grace past `jwt_valid_until` before periodic tick terminates the session. Worst-case linger = grace + tick interval ≈ 90s. |
| `SESSION_TICK_INTERVAL_SECONDS` | `30` | Cadence of the `SessionManager` background tick task. Enforces JWT expiry + grace, sweeps allocator leaks, evicts DETACHED_GRACE sessions. |
| `SESSION_RECONNECT_GRACE_SECONDS` | `0` | Time between last WS disconnect and TERMINATING transition. Default 0 = strict tab-close-terminates (per user Decision 2). Non-zero values are a runtime knob for future operational tuning; the state machine SKIPS the DETACHED_GRACE state entirely when this is 0. |
| `WS_HEARTBEAT_INTERVAL_SECONDS` | `15` | Server-side ping interval on `/ws/session/{session_id}`. |
| `WS_HEARTBEAT_TIMEOUT_SECONDS` | `15` | Max time without a pong before authoritative teardown (ADR-10). |
| `SESSION_ISOLATION_ENABLED` | `false` | Kill switch. When `false`, the code path falls back to pre-refactor singleton behavior (Stage 1 rollout). When `true`, all session isolation machinery runs (Stages 2-3). |
| `LOG_FORMAT` | `json` | Selects `JsonFormatter` (production) vs. plain-text `basicConfig` (`text`, developer-local convenience). Explicit ADR-8-tracked deviation from `CLAUDE.md`'s "OpenTelemetry First" aspiration. |

### Acceptance Criteria

#### AC-ENTRY-1: A logged-in user reaching the dashboard bootstraps a Session

**Priority**: MUST

**Given** a user with a valid vcAPI RS256 JWT resolved by `<AuthProvider>` (FEAT-048)
**When** they navigate to the vQA dashboard root and `<SessionProvider>` mounts
**Then**:
- The frontend issues `POST /api/session/start` with `Authorization: Bearer <jwt>`.
- The response is `200 OK` with body `{ session_id, novnc_url, jwt_valid_until, next_rebind_by, state: "READY" }`.
- The response carries `Set-Cookie: vqa_session=<session_id>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<jwt.exp - now>` (with `Secure` conditional on the request scheme in dev).
- `SessionStatusIndicator` renders green.
- `useSession()` context becomes non-null throughout the dashboard.
- A `session.started` structured JSON log line is emitted with `session_id`, `user_id`, `user_email`, `trace_id`.

**Verification**:
- [ ] Integration test in `tests/test_session_routes.py`: bootstrap returns 200, cookie flags correct in prod vs. dev.
- [ ] E2E test in `tests/test_session_isolation.py`: single-client bootstrap yields a usable `session_id` and cookie.
- [ ] Frontend unit test in `frontend/src/context/__tests__/SessionContext.test.tsx`: `useSession()` is non-null after mount.
- [ ] Manual browser check: DevTools → Network → `Set-Cookie` header visible on `/api/session/start`.

#### AC-ENTRY-2: `<SessionProvider>` mounted outside `<AuthProvider>` throws a loud runtime error

**Priority**: MUST

**Given** a developer refactoring `frontend/src/main.tsx`
**When** `<SessionProvider>` is mounted without a `<AuthProvider>` ancestor (or before `useAuth().status === "authenticated"`)
**Then**:
- `SessionProvider` throws `Error("SessionProvider must be mounted inside AuthProvider")` at mount time.
- The error is loud (not a console warning) so nesting-order regressions fail fast in dev.
- Before `useAuth().status === "authenticated"`, `SessionProvider` MUST NOT call `POST /api/session/start`.

**Verification**:
- [ ] Frontend unit test in `frontend/src/context/__tests__/SessionContext.test.tsx`: rendering without `<AuthProvider>` throws the expected error.
- [ ] Frontend unit test: `POST /api/session/start` is not fired before `useAuth().status === "authenticated"` (assert via mocked fetch call count).

#### AC-ENTRY-3: The three isolated entry points bind to the caller's session automatically

**Priority**: MUST

**Given** a user with an active Session (state = ATTACHED)
**When** they click any of:
  1. "Record a Demo" in `TakeoverPanel`
  2. "Run" on a Playwright test row in `PlaywrightTests`
  3. "Execute" in the AC-driven run flow
**Then**:
- The corresponding `POST /execute*` endpoint stamps `run.session_id = cookie.session_id`.
- The Playwright browser is launched with `DISPLAY=:{session.display_num}`.
- The `run_id` is appended to `session.active_run_ids`.
- The noVNC iframe rendered in `LiveBrowser` reads `novnc_url` from `useSession()`, NOT from the run's status object.

**Verification**:
- [ ] Integration test in `tests/test_session_routes.py`: every `POST /execute*` requires a valid session cookie, returns 401 without.
- [ ] Unit test in `tests/test_session_browser_manager.py`: launched Playwright carries `env["DISPLAY"] == f":{session.display_num}"`.
- [ ] Frontend unit test in `frontend/src/components/__tests__/LiveBrowser.test.tsx`: iframe `src` derives from `useSession().novnc_url`, not from `run.status.novnc_url`.

---

#### AC-HAPPY-1: Two concurrent users on different machines see only their own browser session

**Priority**: MUST

**Given** two authenticated users, `alice@vcreative.com` and `bob@vcreative.com`, logged into vQA from separate browsers on separate machines
**When** they each click "Record a Demo" within 2 seconds of each other
**Then**:
- Both `POST /api/session/start` calls succeed with `200 OK`.
- Alice's session gets a distinct `session_id` and `novnc_url` (e.g., `/vnc/<alice-sid>/vnc.html?path=websockify/<alice-sid>`) from Bob's.
- Alice's session is allocated `DISPLAY=:1` and websockify port `6081`; Bob's is `:2` / `6082` (or the next free slot).
- Alice's noVNC iframe renders only Alice's Playwright browser (her navigations, her scroll position, her mouse).
- Bob's noVNC iframe renders only Bob's Playwright browser.
- Neither user's actions appear in the other's iframe under any circumstance.
- The KB entries produced by "Done" carry `recorded_by: alice@vcreative.com` and `recorded_by: bob@vcreative.com` respectively — two distinct entries, both persisted to `knowledge/blueprints/learned_workflows.json`.

**Verification**:
- [ ] E2E test in `tests/test_session_isolation.py`: two authenticated Playwright test clients start sessions, each gets a distinct `novnc_url`; assert content of the iframes diverges after each client navigates to different URLs.
- [ ] Integration test: `nginx_map.write()` produces two distinct entries in `/var/run/vqa/sessions.map`; nginx routes `/vnc/<alice-sid>/*` → port 6081 and `/vnc/<bob-sid>/*` → port 6082 (verified in `tests/test_nginx_multiplex.py`).
- [ ] Integration test in `tests/test_kb_writer_concurrency.py`: two concurrent `KBWriter.append_with_lock` calls produce two entries in `learned_workflows.json`, both under `fcntl.flock`, both with distinct `recorded_by`.
- [ ] Manual browser check (two-machine): Alice and Bob open vQA on separate laptops, both click "Record a Demo", both see only their own browser session.

#### AC-HAPPY-2: KB writes are attributed to the recording user

**Priority**: MUST

**Given** a user with an active Session recording a demo
**When** they click "Done" and the autorecord bridge appends to `knowledge/blueprints/learned_workflows.json`
**Then**:
- The written entry contains `recorded_by: <session.user_email>` (exact match to the JWT-authenticated email).
- The written entry contains `recorded_at: <iso8601>` (UTC timestamp of the write).
- The write path is `KBWriter.append_with_lock(...)`; the lock is acquired via `fcntl.flock` on `<file>.lock`; the lock is released on close.
- Markdown appends to `vSuite-actions.md` and `human_guidance.md` carry the same attribution as an HTML comment prefix: `<!-- recorded_by: alice@vcreative.com; recorded_at: 2026-08-06T12:34:56Z -->`.
- A `browser.launched` and terminal `kb.write` structured JSON log line is emitted (with `session_id`, `run_id`, `trace_id`).

**Verification**:
- [ ] Integration test in `tests/test_kb_writer_concurrency.py`: single writer produces one entry with correct `recorded_by` + `recorded_at`.
- [ ] Unit test in `tests/test_kb_writer.py`: markdown-append variant produces the `<!-- recorded_by: ... -->` prefix.
- [ ] E2E test (`tests/test_session_isolation.py`): "Done" click by user with a session results in an entry in `learned_workflows.json` with the user's email; test asserts equality against the JWT-authenticated email.

#### AC-HAPPY-3: JWT rebind extends the session without user-visible disruption

**Priority**: MUST

**Given** an active session with `jwt_valid_until` approaching (frontend's `useRebindTimer` triggers at `next_rebind_by`)
**When** the frontend calls `POST /api/session/rebind` with a freshly-refreshed JWT (obtained from vcAPI via `useAuth().refresh()`)
**Then**:
- The response is `200 OK` with body `{ session_id, jwt_valid_until: <new_exp>, next_rebind_by: <new_exp - 90s> }`.
- `Set-Cookie: vqa_session=<same session_id>; ...; Max-Age=<new_jwt.exp - now>` — cookie re-issued with fresh Max-Age (ADR-11).
- `session.jwt_valid_until` is updated to `new_jwt.exp`.
- No user-visible disruption — the noVNC iframe keeps streaming, in-flight runs continue.
- A `session.rebound` structured JSON log line is emitted.

**Verification**:
- [ ] Integration test in `tests/test_rebind.py`: `POST /session/rebind` returns 200, `Set-Cookie` `Max-Age` reflects `new_jwt.exp - now`.
- [ ] Integration test in `tests/test_rebind.py`: `session.jwt_valid_until` updated post-rebind (assert via `GET /session/{id}/status`).
- [ ] Frontend unit test in `frontend/src/hooks/__tests__/useRebindTimer.test.ts`: timer schedules exactly at `next_rebind_by`; fires once per rebind.

#### AC-HAPPY-4: The `SessionStatusIndicator` reflects live session state

**Priority**: SHOULD

**Given** an active session with `<SessionStatusIndicator>` rendered in the app header
**When** the session transitions through its states (READY → ATTACHED → ... → TERMINATING → TERMINATED)
**Then**:
- READY / ATTACHED renders a green dot.
- DETACHED_GRACE (only when `SESSION_RECONNECT_GRACE_SECONDS > 0`) or rebinding renders a yellow dot.
- TERMINATING / TERMINATED / FAILED renders a red dot.
- The state is derived from `/ws/session/{session_id}` lifecycle events (NOT from polling).

**Verification**:
- [ ] Frontend unit test in `frontend/src/components/__tests__/SessionStatusIndicator.test.tsx`: renders green for ATTACHED, yellow for rebinding, red for TERMINATED.
- [ ] Frontend unit test in `frontend/src/hooks/__tests__/useSessionWebSocket.test.ts`: WS lifecycle messages update context state without polling.

---

#### AC-ERROR-1: `POST /api/session/start` without a valid JWT returns 401

**Priority**: MUST

**Given** an unauthenticated user (no `Authorization` header, or expired/malformed JWT, or missing required claim: `exp`, `jti`, `vc_id`, or JWT TTL > `MAX_JWT_TTL_SECONDS`)
**When** they call `POST /api/session/start`
**Then**:
- The response is `401 Unauthorized` with body `{ error: "invalid_token", detail: "<reason>" }`.
- No session is created.
- No cookie is set.
- A structured JSON log line is emitted: `session.jwt_expired` OR `session.jti_revoked_hit` OR a generic `auth.rejected` with the reason (missing claim / TTL exceeded / signature invalid).

**Verification**:
- [ ] Integration test in `tests/test_jwt_hardening.py`: JWT with no `exp` → 401.
- [ ] Integration test in `tests/test_jwt_hardening.py`: JWT with `(exp - now) > MAX_JWT_TTL_SECONDS` → 401.
- [ ] Integration test in `tests/test_jwt_hardening.py`: JWT with `jti` in `RevokedJtiSet` → 401 with `session.jti_revoked_hit` log.
- [ ] Integration test: missing `Authorization` header → 401.

#### AC-ERROR-2: Capacity cap returns 409 with retry hint; frontend shows the capacity page

**Priority**: MUST

**Given** `MAX_CONCURRENT_SESSIONS` sessions are already active
**When** a new user calls `POST /api/session/start`
**Then**:
- The response is `409 Conflict` with body `{ error: "capacity_reached", retry_after_s: <int>, active_sessions: <int> }`.
- No session is created; no cookie is set.
- A `session.capacity_reached` structured JSON log line is emitted (with `user_id`, `user_email`, `trace_id`).
- The frontend renders the `CapacityReached` full-page state (`frontend/src/pages/CapacityReached.tsx`) with copy `vQA is at capacity. {active_sessions} users active. Estimated wait: ~{M} minutes.` and auto-retries `POST /api/session/start` every `15s ± jitter`.
- On successful retry (a slot has freed), the dashboard renders normally.

**Verification**:
- [ ] Integration test in `tests/test_session_routes.py`: `POST /session/start` at cap → 409 with `retry_after_s`.
- [ ] Frontend unit test in `frontend/src/pages/__tests__/CapacityReached.test.tsx`: renders copy correctly; auto-retry timer fires every 15s (with jitter).
- [ ] E2E test: bootstrap N+1 clients; the Nth+1 sees the capacity page; releasing a slot lets the Nth+1 succeed on the next retry tick.

#### AC-ERROR-3: Cross-user WS attach is rejected with close code 4401

**Priority**: MUST

**Given** user Alice with `session_a`, user Bob with `session_b`, and a run `run_x` created by Alice (`run_x.session_id == session_a`)
**When** Bob's browser (carrying `vqa_session=session_b` cookie) attempts to open `WS /ws/{run_x}`
**Then**:
- The WebSocket handshake is accepted momentarily then closed with `close(code=4401, reason="cross_user_attach_rejected")`.
- No log stream is delivered to Bob's WS.
- A `session.origin_rejected` OR a dedicated `ws.cross_user_rejected` structured JSON log line is emitted with `attempted_run_id`, `attempted_by_session`, `owning_session`.
- Existing Alice's WS on `run_x` is unaffected.

**Verification**:
- [ ] Integration test in `tests/test_e2e_websocket_cors.py`: cross-user cookie on `/ws/{run_id}` → close(4401).
- [ ] Integration test: matching-session cookie on `/ws/{run_id}` → normal message flow.
- [ ] Integration test: missing cookie on `/ws/{run_id}` → close(4401) or close(4403) (specify in implementation; MUST NOT accept anonymous WS).

#### AC-ERROR-4: WS handshake with mismatched or missing `Origin` header is rejected

**Priority**: MUST

**Given** a WebSocket handshake request to `/ws/session/{session_id}`, `/ws/{run_id}`, or `/ws/codegen/{codegen_id}`
**When** the request's `Origin` header is missing OR does not match the configured `CORS_ALLOWED_ORIGINS` list
**Then**:
- The handshake is rejected with `close(code=4403, reason="origin_rejected")` (or an HTTP-level 403 before upgrade — implementation choice).
- A `session.origin_rejected` structured JSON log line is emitted with the received `Origin` value and `trace_id`.
- No WS traffic flows.

**Verification**:
- [ ] Integration test in `tests/test_e2e_websocket_cors.py`: WS with `Origin: https://evil.example.com` → close(4403).
- [ ] Integration test: WS with no `Origin` header → close(4403).
- [ ] Integration test: WS with allowed `Origin` → normal handshake succeeds.

#### AC-ERROR-5: Session terminates within grace when JWT expires and rebind fails

**Priority**: MUST

**Given** an active session whose `session.jwt_valid_until` has passed and whose frontend rebind attempt failed (vcAPI unavailable, refresh token expired, etc.)
**When** the `SessionManager` periodic tick fires (every `SESSION_TICK_INTERVAL_SECONDS=30`) and detects `now >= session.jwt_valid_until + REBIND_GRACE_SECONDS(60)`
**Then**:
- The session transitions REQUESTED-lineage → TERMINATING → TERMINATED via `lifecycle.terminate()`.
- All `active_run_ids` are killed (Playwright contexts closed, runs marked FAILED with `termination_reason: session_jwt_expired`).
- `DisplayAllocator.release()` runs `supervisorctl stop xvfb_N x11vnc_N websockify_N` for this session's display.
- `nginx_map.remove(session_id)` clears the map entry; nginx is signaled to reload (inotify or `nginx -s reload`).
- The frontend `/ws/session/{session_id}` receives a `session_terminated { reason: "jwt_expired" }` event and disconnects.
- Frontend toast: `Session expired. Redirecting to login...`, then redirect to `/login`.
- Structured JSON log lines: `session.jwt_expired`, `session.terminated`.
- Worst-case lag from JWT expiry to teardown ≤ `REBIND_GRACE_SECONDS + SESSION_TICK_INTERVAL_SECONDS` = 90s.

**Verification**:
- [ ] Integration test in `tests/test_session_manager.py`: fast-forward clock past `jwt_valid_until + grace`; assert tick terminates the session.
- [ ] Integration test: post-termination, `GET /session/{id}/status` returns 404 or `state: TERMINATED`.
- [ ] Frontend unit test in `frontend/src/context/__tests__/SessionContext.test.tsx`: `session_terminated` WS event triggers the toast + redirect.

#### AC-ERROR-6: Session terminates on WS heartbeat timeout regardless of `beforeunload`

**Priority**: MUST

**Given** an active session with a live `/ws/session/{session_id}` connection
**When** the client stops responding to server pings for `WS_HEARTBEAT_TIMEOUT_SECONDS=15` (tab closed without `beforeunload` firing, network drop, laptop-lid-close, Safari iOS backgrounding)
**Then**:
- Server declares the connection dead and initiates `lifecycle.terminate()`.
- All `active_run_ids` are killed; Playwright contexts closed.
- Display + port released via `supervisorctl stop`; `nginx_map.remove()` called.
- A `session.ws_heartbeat_timeout` and `session.terminated` structured JSON log line is emitted.
- Teardown completes within `WS_HEARTBEAT_TIMEOUT_SECONDS` after the last successful pong (ADR-10: heartbeat is authoritative, `beforeunload` is best-effort).

**Verification**:
- [ ] Integration test in `tests/test_session_manager.py`: simulate WS disconnect without close frame; assert termination within 15s.
- [ ] Integration test: assert `beforeunload` NOT required for correctness — a test that closes the socket abruptly still results in a clean teardown.
- [ ] Manual browser check: force-quit browser tab (SIGKILL simulation via DevTools "close without close event"); observe teardown in server logs within 15s.

#### AC-ERROR-7: Rebind past the grace window is rejected

**Priority**: MUST

**Given** an active session where the tick has already terminated it because `now >= jwt_valid_until + REBIND_GRACE_SECONDS`
**When** the frontend belatedly calls `POST /api/session/rebind` with a freshly-refreshed JWT
**Then**:
- The response is `404 Not Found` with body `{ error: "session_not_found", detail: "session has been terminated" }` (OR `410 Gone` — implementation may choose; MUST NOT be 200).
- No new session is created via rebind — rebind is not a fallback bootstrap path.
- No cookie is set.
- The frontend falls through to `POST /api/session/start` (a fresh bootstrap), which succeeds if capacity allows.
- A `session.rebind_failed` structured JSON log line is emitted with reason `session_terminated`.

**Verification**:
- [ ] Integration test in `tests/test_rebind.py`: terminate session, then `POST /session/rebind` → 404/410.
- [ ] Integration test: rebind with a valid cookie whose `session_id` was never in `SessionManager.sessions` → 404/410 (defensive).
- [ ] Frontend unit test: on 404 rebind response, `SessionProvider` falls through to `POST /session/start`.

#### AC-ERROR-8: Cross-user rebind is rejected

**Priority**: MUST

**Given** Alice's session `session_a` and Bob's freshly-refreshed JWT
**When** a request calls `POST /api/session/rebind` with cookie `vqa_session=session_a` and `Authorization: Bearer <bob's JWT>` (i.e., the cookie's session belongs to Alice but the JWT's `vc_id` is Bob's)
**Then**:
- The response is `403 Forbidden` with body `{ error: "session_user_mismatch" }`.
- `session_a` is unaffected.
- A structured JSON log line is emitted with `session_id`, `cookie_user`, `jwt_user`, `trace_id`.

**Verification**:
- [ ] Integration test in `tests/test_rebind.py`: cross-user rebind → 403; `session_a` state unchanged.

#### AC-ERROR-9: KB write lock timeout produces a sidecar file and warns

**Priority**: SHOULD

**Given** a `KBWriter.append_with_lock` call that cannot acquire `fcntl.flock` on `<file>.lock` within its 5s deadline (pathological contention or a stuck holder)
**When** the timeout elapses
**Then**:
- The intended entry is written to a sidecar file at `<file>.sidecar-<iso8601-timestamp>.jsonl` (single-entry JSON Lines format for reconciliation).
- A `kb.write_lock_timeout` structured JSON log line is emitted at WARN level with `file`, `session_id`, `user_email`, `sidecar_path`.
- The user-facing "Done" flow does NOT surface an error — the write is best-effort with a manual reconciliation path.
- The sidecar file is discoverable via a filesystem glob and can be manually merged into the main KB.

**Verification**:
- [ ] Integration test in `tests/test_kb_writer_concurrency.py`: hold `<file>.lock` externally, call `append_with_lock`; assert 5s timeout, sidecar file created with correct entry.
- [ ] Integration test: assert WARN log line with the correct event name and fields.

---

#### AC-ASYNC-1: Cookie is re-issued on every successful rebind with fresh Max-Age

**Priority**: MUST

**Given** an active session whose original cookie was set with `Max-Age = <original_jwt.exp - t0>`
**When** the frontend calls `POST /api/session/rebind` at time `t1` with a new JWT whose `exp = <new_jwt.exp>`
**Then**:
- The response `Set-Cookie` header carries `Max-Age = <new_jwt.exp - t1>`, NOT `<original_jwt.exp - t0>`.
- The cookie's `session_id` value is unchanged (same session).
- All other flags (HttpOnly, Secure conditional on prod scheme, SameSite=Lax, Path=/) match `/session/start`.
- Without this, per ADR-11, the cookie would expire at the original JWT's exp and the browser would drop it — defeating rebind entirely.

**Verification**:
- [ ] Integration test in `tests/test_rebind.py`: capture `Set-Cookie` on `/session/start` and `/session/rebind`; assert `Max-Age` values differ and the second equals `new_jwt.exp - now(±1s)`.
- [ ] Integration test: `Secure` flag present in prod schema, absent in dev HTTP.

#### AC-ASYNC-2: `beforeunload` is NOT required for correctness

**Priority**: MUST

**Given** an active session on a browser where `beforeunload` never fires (Safari iOS backgrounding, force-quit, network partition, laptop-lid-close)
**When** the tab is closed / the WS is severed without any client-side signal
**Then**:
- Session teardown STILL occurs within `WS_HEARTBEAT_TIMEOUT_SECONDS=15` of the last successful pong.
- No test in this feature MAY be written such that its correctness depends on `beforeunload` firing. `beforeunload` is a best-effort accelerant only (ADR-10).
- Documentation (per-file comment near the frontend WS teardown handler) explicitly notes that `beforeunload` is best-effort.

**Verification**:
- [ ] Integration test in `tests/test_session_manager.py`: assert termination on heartbeat timeout with NO `close(1000)` frame received.
- [ ] Manual code review: `frontend/src/hooks/useSessionWebSocket.ts` contains a comment noting `beforeunload` is best-effort; no test file asserts a beforeunload-only path.

#### AC-ASYNC-3: Container drain terminates all sessions gracefully

**Priority**: MUST

**Given** an in-flight `docker stop <container>` OR an ECS task shutdown signal (SIGTERM to PID 1 / supervisord)
**When** the FastAPI lifespan shutdown fires
**Then**:
- `SessionManager.drain_all()` iterates every active session and calls `lifecycle.terminate(reason="container_drain")` on each.
- Every `/ws/session/{session_id}` emits `session_terminated { reason: "container_drain" }` before closing.
- Frontend renders the "Server is restarting. Please refresh in ~30s." message — does NOT redirect to `/login`.
- All Playwright browsers are closed cleanly (no orphaned Chromium processes).
- All display slots are released via `supervisorctl stop` (or become moot as supervisord tears down).
- The lifespan shutdown returns within the container's grace window (default 30s for Docker; longer for Fargate).
- Structured JSON log lines: `session.terminated` for each session with `reason: container_drain`.

**Verification**:
- [ ] Integration test in `tests/test_session_manager.py`: fire lifespan shutdown with N active sessions; assert all N receive `session_terminated`, all Playwright processes exit.
- [ ] Manual test: `docker stop vqa-backend` mid-session; observe frontend receives the drain message, not the login redirect.

#### AC-ASYNC-4: Allocator leak reconciliation catches supervisorctl failures

**Priority**: MUST

**Given** a `DisplayAllocator.acquire()` that called `supervisorctl start xvfb_N x11vnc_N websockify_N` but where one of the three programs failed to reach RUNNING state (or transitioned to FATAL / EXITED shortly after)
**When** the `SessionManager` periodic tick fires (every `SESSION_TICK_INTERVAL_SECONDS=30`)
**Then**:
- Reconciliation cross-checks `supervisorctl status xvfb_<N>` (and x11vnc/websockify) against `SessionManager.sessions[session_id].display_num` for every active session.
- Slots that are believed-in-use by SessionManager but are actually STOPPED / FATAL in supervisord trigger `session.allocator_leak` WARN log with `session_id`, `display_num`, `program`, `supervisorctl_state`.
- The affected session is transitioned to FAILED → TERMINATING (fast-path) so the user is notified rather than left with a broken session.
- The display slot is released back to the allocator pool.

**Verification**:
- [ ] Integration test in `tests/test_display_allocator.py`: mock `supervisorctl start` to return success but `supervisorctl status` to return FATAL; assert reconciliation catches the leak within one tick interval.
- [ ] Integration test: `session.allocator_leak` log line emitted with correct fields.

#### AC-ASYNC-5: `SESSION_RECONNECT_GRACE_SECONDS=0` skips the DETACHED_GRACE state entirely

**Priority**: MUST

**Given** the environment variable `SESSION_RECONNECT_GRACE_SECONDS=0` (default)
**When** the last WS connection for a session disconnects
**Then**:
- The state machine transitions directly ATTACHED → TERMINATING (skipping DETACHED_GRACE entirely).
- No timer is scheduled to wait for reconnect.
- `lifecycle.terminate()` fires immediately.

**Given** the same environment variable is set to a positive value (e.g., `SESSION_RECONNECT_GRACE_SECONDS=30`)
**When** the last WS disconnects
**Then**:
- The state machine transitions ATTACHED → DETACHED_GRACE.
- A timer is scheduled for `SESSION_RECONNECT_GRACE_SECONDS`.
- If a new WS attaches before the timer fires, the state returns to ATTACHED (grace was a save).
- If the timer fires without a new WS, the state proceeds to TERMINATING.

**Verification**:
- [ ] Unit test in `tests/test_session_manager.py`: with `SESSION_RECONNECT_GRACE_SECONDS=0`, WS close triggers immediate TERMINATING transition.
- [ ] Unit test: with `SESSION_RECONNECT_GRACE_SECONDS=30`, WS close triggers DETACHED_GRACE; reconnect within 30s returns to ATTACHED; no reconnect leads to TERMINATING at 30s.

#### AC-HAPPY-5: `SESSION_ISOLATION_ENABLED=false` kill switch preserves pre-refactor behavior

**Priority**: MUST

**Given** the environment variable `SESSION_ISOLATION_ENABLED=false` (Stage 1 rollout)
**When** any code path reaches a session-scoped fork (bootstrap, run launch, KB write, WS auth)
**Then**:
- The code falls through to the pre-refactor singleton path via the `__legacy_singleton__` stub (Phase 0 backward-compat).
- All existing FEAT-051 (Playwright Test Library) and Record-a-Demo flows continue to work with pre-existing shared-singleton semantics.
- No `/api/session/*` endpoint is required for these legacy paths (kill switch off = they don't exist as a hard requirement).
- Setting the flag to `true` and restarting the container flips to the fully-isolated code path with no code deploy.

**Verification**:
- [ ] Integration test in `tests/test_session_browser_manager.py`: with `SESSION_ISOLATION_ENABLED=false`, existing `BrowserManager` tests pass unchanged (Phase 0 requirement).
- [ ] Integration test: with the flag on, `POST /api/session/start` succeeds; with it off, requests to `/api/session/*` may 404 (or the flag gates the mount).
- [ ] Manual verification: Stage 1 rollout dry-run — deploy with flag off, run the Golden 10 regression benchmark, assert no regression.

#### AC-HAPPY-6: KB writes carry attribution even when triggered from a legacy `__legacy_singleton__` path

**Priority**: SHOULD

**Given** `SESSION_ISOLATION_ENABLED=false` (Stage 1) with `__legacy_singleton__` in effect
**When** a KB write is triggered by "Done"
**Then**:
- The write STILL routes through `KBWriter.append_with_lock` (`fcntl.flock`).
- `recorded_by` is set to the caller's email if a JWT-authenticated context is available; otherwise `recorded_by: "legacy_singleton"` and `recorded_at: <iso8601>`.
- A `kb.write` log line is emitted with the resolved `recorded_by`.
- No entry is silently written without attribution (blocked-state surfacing per AC-ERROR-9 pattern).

**Verification**:
- [ ] Integration test in `tests/test_kb_writer.py`: legacy path with no session → entry has `recorded_by: "legacy_singleton"`.
- [ ] Integration test: legacy path with an authenticated request context (JWT resolvable) → entry has the real email.

---

### Scope Boundaries

**In scope:**
- New backend subsystem at `backend/session/` (SessionManager, DisplayAllocator, Session dataclass, lifecycle, nginx_map).
- Multi-display container: templated `docker/supervisord.conf` with `autostart=false` slots, `docker/entrypoint.sh` renderer.
- In-container nginx sidecar (`docker/nginx.conf`) for `/vnc/<sid>/*` and `/websockify/<sid>` multiplexing.
- ALB config change to path-prefix routing (`/vnc/*`, `/websockify/*`) — a one-line edit in `deploy.sh`.
- Fargate task memory bump (target `6144` MB; final value depends on `MAX_CONCURRENT_SESSIONS × ~700MB` sizing).
- Session-scoped `SessionBrowserManager` refactor of `backend/browser/context.py` — Phase 0 (its own PR) with `__legacy_singleton__` backward-compat, Phase 4 removes the stub.
- Auth hardening in `backend/auth/sso.py`: `SsoValidator` require + TTL; new `backend/auth/revocation.py` `RevokedJtiSet`; new `backend/auth/cookies.py`.
- Session cookie flow with re-issue on rebind (ADR-11).
- New session-control WebSocket `/ws/session/{session_id}` (additive, not replacement).
- WebSocket authentication via HttpOnly cookie in handshake; existing `/ws/{run_id}` and `/ws/codegen/{codegen_id}` (renamed) gated by cookie + Origin + `run.session_id` match.
- KB write attribution via `KBWriter.append_with_lock` + `fcntl.flock` + `recorded_by`/`recorded_at`; sidecar fallback on lock timeout.
- Structured JSON logging (stdlib `JsonFormatter`) as the observability transport; CloudWatch Metric Filters + Alarms for aggregation.
- Homebrew request-scoped `trace_id` via `X-Request-Id` header + `ContextVar`.
- Frontend: `SessionProvider`, `useSession`, `useSessionWebSocket`, `useRebindTimer`, `SessionStatusIndicator`, `CapacityReached` page, refactored `TakeoverPanel` / `LiveBrowser`.
- Rollout behind `SESSION_ISOLATION_ENABLED` kill switch; three-stage plan (off → N=1 → N=4→8).
- Reconciliation loop for allocator leak detection (`session.allocator_leak`).
- Updated productBrief.md to reflect the session-scoped VNC URL schema (Phase 3 deliverable).

**Out of scope (explicitly deferred):**
- Full OpenTelemetry SDK bootstrap (ADR-8; deferred as its own multi-phase project).
- Prometheus client library or scrape endpoint.
- Distributed traces across LLM providers (Bedrock / Anthropic).
- Per-user KB fragmentation (KB stays shared — the "reusable artifacts" value prop per productBrief.md; multi-user attribution only).
- Cross-worker session sync — uvicorn `--workers 1` is a hard invariant per `docker/supervisord.conf:115` (Playwright is not fork-safe).
- Persistent session state across container restarts (browsers die with the container; nothing to recover).
- Admin impersonation of vQA users (`Session.ghosted_by` speculatively proposed and withdrawn during design; vQA "ghost login" is a vSuite-level in-run action).
- Migration of `deploy.sh` inline secrets to AWS Secrets Manager (tracked as a follow-up task).
- Per-session Docker containers (Approach A, ADR-1 upgrade path; reserved for post-beta scale).
- Playwright cloud / browser-as-a-service (Approach C).
- Blue/green deployment for rollout — Fargate task is single-instance; rollout is staged via kill switch instead.
- Persistent revocation store — `RevokedJtiSet` is in-memory only (ADR-7); container restart wipes it (and also kills every session).

**Dependencies:**
- FEAT-047 (vcAPI RS256 SSO) — `SsoValidator` in `backend/auth/sso.py` is the base auth this feature hardens.
- FEAT-048 (Independent React Auth System) — `<AuthProvider>` and `useAuth()` are the JWT lifecycle owner; `SessionProvider` consumes them.
- FEAT-051 (Static Playwright Test Library) — Playwright "Run" button in the Playwright Test Library is one of the three isolated entry points; already exists.
- vcAPI SSO issuance policy — this feature enforces `MAX_JWT_TTL_SECONDS=3600` at the vQA edge; a coordination note is documented in ADR-6.

**NFR implications (from productBrief.md):**
- **Performance**: p95 `session.started → session_ready` latency < 5s (supervisorctl-start bound). Container memory budget: `MAX_CONCURRENT_SESSIONS × ~700MB` (browser + display) + backend baseline; final Fargate task memory targeted at 6144 MB.
- **Security**: Every JWT-facing endpoint enforces `exp` + `jti` + `vc_id` claims and `MAX_JWT_TTL_SECONDS=3600` post-decode. `RevokedJtiSet` supports admin revocation within the JWT's TTL window. Cross-user WS attach is rejected with `close(4401)`. `Origin` validation on every WS handshake.
- **Availability**: Kill switch (`SESSION_ISOLATION_ENABLED`) enables instant rollback via env-var flip + restart (no code deploy). Reconciliation loop catches allocator leaks within one tick interval (30s).
- **Auditability**: Every KB entry carries `recorded_by` + `recorded_at`; every session lifecycle event is structured-JSON-logged with `session_id`, `user_id`, `user_email`, `trace_id` for CloudWatch Logs Insights querying.
- **Multi-user concurrency**: The signature acceptance behavior — two users on separate machines see only their own browser session — is a direct product-brief NFR (currently violated; this feature fixes it).

### Creative Exploration Needed

No. The architecture design phase is complete. `memory-bank/creative/per-user-session-isolation-design.md` records 15 approved ADRs, each traced back to a user decision or security review during `/bmb:brainstorm`. Every technical detail in this spec traces to an ADR or an explicit user-approved decision:

- ADR-1 through ADR-15 cover: multi-display topology, lazy display allocation, nginx multiplexer, HttpOnly cookie WS auth, `fcntl.flock`, JWT hardening claims + TTL, in-memory revocation set, JSON logs vs. OTel, Phase 0 refactor sequencing, heartbeat authority, rebind cookie re-issue, rebind grace, reconnect grace default, deploy.sh scoped edits, templated supervisord.
- User decisions during brainstorm: shared KB with attribution (Decision 1), tab-close = terminate (Decision 2), true multi-user parallelism (scope), multi-display Option B (infra shape).
- Security review outcomes: JWT-in-first-frame withdrawn (cookie-in-handshake chosen), `Session.ghosted_by` withdrawn (out of scope).

If any AC below turns out to need creative refinement during `/bmb:build` (e.g., the exact `close()` code for cross-user WS attach is disputed — this spec chose `4401`, but `4403` is defensible), that is a **narrow implementation-choice** question surfaced during build, not a creative re-exploration. Proceed to `/bmb:build` phase-by-phase; do not re-run `/bmb:creative`.

### Implementation Guide Required

No. Every AC above is auto-verifiable via the tests catalogued in the task file's `## Test Strategy` section plus the manual browser checks flagged in the `Verification` blocks. The rollout stages (`SESSION_ISOLATION_ENABLED=false → true; N=1 → 4 → 8`) are documented in the task's Implementation Roadmap Phase 7 and do not require a separate implementation guide.

---

## Build Execution State

**Build Status**: RUNNING
**Build Status**: COMPLETE
**Current Phase**: ALL PHASES COMPLETE (8/8)
**Auto-Build Mode**: YES

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A — all phases complete
**Notes**: Auto-build initiated 2026-08-06; all Phases 0–7 complete.

### Halt State
*(none)*

### Deviations
*(all four post-BUILD_COMPLETE deviations closed 2026-08-07 — see commit for details)*

**Closed deviations:**
- ~~Phase 4 | execute_single | active_run_ids not populated~~ → `SessionManager.add_active_run_id()` / `remove_active_run_id()` added; execute_single and _execute_run/_execute_linear_run finally-blocks wire it.
- ~~Phase 5 | human_takeover.py | KB writes not through KBWriter~~ → all four writers (_save_to_learned_workflows, _append_to_kb_staging, _write_to_vsuite_actions_kb, _save_combined_hitl_entry, persist_user_guidance) now route through KBWriter with recorded_by resolved from the run's session. Added KBWriter.append_jsonl_with_lock for the JSONL staging file.
- ~~Phase 6 | LiveBrowser/TakeoverPanel | novnc_url from run prop~~ → both components now call useOptionalSession() and prefer session.novncUrl when the session is attached, falling back to the prop for legacy/singleton path.
- ~~Phase 4 | execute_batch | missing session cookie~~ → execute_batch now enforces the vqa_session cookie when SESSION_ISOLATION_ENABLED is on and adds each batch run to the caller's active_run_ids.

---

## Execution State (Legacy Build Log)

**Build Status**: RUNNING (Auto-Build)
**Current Build**: Phase 4 (per-user-session-isolation)
**Build Started**: 2026-08-06T03:00:00Z
**Phase Number**: 4 of 8 — IN PROGRESS
**Is Multi-Phase**: YES
**Can Resume**: YES

### Current Build Step
**Step**: Phase 3 — COMPLETE
**Status**: COMPLETE
**Completed**: 2026-08-07T00:00:00Z
**Output**: 21 tests (5 new in test_nginx_multiplex.py, 4 updated in test_vnc_url_builder.py, 1 new + 4 fixed in test_vnc_api.py); vnc_builder.py session_id kwarg; nginx_map.py write_sessions_map(); deploy.sh memory=6144 + /vnc/* + /websockify/* path-prefix ALB rules; productBrief.md updated

### Completed Steps
- Phase 0 COMPLETE (2026-08-06): SessionBrowserManager refactor, 17 tests, committed+pushed
- Phase 1 Step 0.5: Worktree confirmed inline — project root = feature branch checkout
- Phase 1 Step 0.6: Phase gate PASS
- Phase 1 Step 1: Phase 1 identified (first unchecked after Phase 0)
- Phase 1 Step 2: Level 4 context noted
- Phase 1 Step 3: TDD — 45 tests RED→GREEN across 3 test files; 9 new source files + 3 extended
- Phase 1 Step 6: Integration: 62 Phase 0+1 tests passing; 76 pre-existing failures unrelated
- Phase 1 Step 7: Integration verification PASS — no new failures introduced
- Phase 1 Step 8: Code Review APPROVED — security, state machine, config all clean
- Phase 1 Step 9: Documentation — all new modules have full docstrings
- Phase 1 Step 10: Memory bank updated; Phase 1 checkbox marked [x]
- Phase 1 Step 11: Committed and pushed to feature/per-user-session-isolation
- Phase 2 Step 0.5: Worktree confirmed inline — project root = feature branch checkout
- Phase 2 Step 0.6: Phase gate PASS — Phase 2 unchecked, creative complete
- Phase 2 Step 1: Phase 2 identified — session routes + WS auth + cookie flow + CORS
- Phase 2 Step 2: Level 4 context loaded
- Phase 2 Step 3: TDD — 26 tests RED→GREEN (test_session_routes.py×14, test_rebind.py×6, test_e2e_websocket_cors.py×6 new tests); 1 new source file + 4 extended
- Phase 2 Step 7: Integration verification PASS — 72 Phase 0+1+2 tests passing; 81 pre-existing failures unchanged
- Phase 2 Step 8: Code Review APPROVED — security clean (JWT, cookie, Origin, cross-user), CORS tightened
- Phase 2 Step 9: Documentation — session_routes.py has full module+function docstrings with ADR refs
- Phase 2 Step 10: Memory bank updated; Phase 2 checkbox marked [x]
- Phase 2 Step 11: Committed and pushed to feature/per-user-session-isolation

### Sub-Agents
- Phase 1 TDD Agent (inline): COMPLETE — 45 tests (RED: import errors; GREEN: 45/45 passing)
- Phase 1 Verifier (inline): COMPLETE — 62/62 Phase 0+1 tests; 76 pre-existing unrelated failures
- Phase 1 Code Reviewer (inline): PASS — security clean, design correct, no blocking issues
- Phase 2 TDD Agent (inline): COMPLETE — 26 tests (RED: ModuleNotFoundError; GREEN: 26/26 passing)
- Phase 2 Verifier (inline): COMPLETE — 72/72 Phase 0+1+2 tests; 81 pre-existing failures unchanged
- Phase 2 Code Reviewer (inline): PASS — no blocking issues

### Guard & Recovery Log
Phase 0: PASS — prod=1 test=1
Phase 1: C1 fail (test-runtime artifacts in worktree — storage/chromadb, memory/auth_states) → restored via git checkout; re-run: PASS prod=11 test=3
Phase 2: guard pending (pre-commit)

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A — Phase 2 complete, start Phase 3 on next /bmb:build invocation
**Notes**: Phase 2 committed as "Phase 2: session routes + WS auth + cookie flow + tightened CORS". Next: Phase 3 (vnc_builder per-session URLs + ALB path-prefix change + Fargate memory bump)
