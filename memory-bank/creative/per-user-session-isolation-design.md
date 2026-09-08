# Creative: Per-User Session Isolation — Architecture Design

**Task**: `per-user-session-isolation`
**Feature**: `per-user-session-isolation`
**Type**: Architecture
**Authored by**: /bmb:brainstorm (conversational design)
**Date**: 2026-08-06
**Status**: Complete — approved section-by-section by the user

---

## Problem Statement

vQA runs a single shared Playwright browser exposed over a single noVNC stream (port 6080 in-container, `/vnc.html` + `/websockify` on the ALB). When user A starts a "Record a Demo" and user B logs into vQA from a different machine and clicks "Record a Demo", user B's frontend attaches to the same live browser — B sees A's session, and both users' actions collide in one Playwright instance.

The gap is systemic, not confined to Record a Demo: every vQA run path (Record a Demo, replay, AC-driven test execution) sits on top of the same shared singleton `BrowserManager` (`backend/browser/context.py`, 953 lines, LangGraph-wide coupling) and the same singleton noVNC pipeline (`docker/supervisord.conf`).

## Scope Decision

Scope confirmed by user during brainstorm:
- **Isolation surface**: All vQA runs (record, replay, AC-driven), not just Record a Demo. Design a session model that ages well.
- **Concurrency model**: True multi-user parallelism — user A and user B run concurrent isolated sessions in separate browsers.
- **KB writes**: Shared KB (single source of truth for reusable artifacts — the vQA value prop). Attribute every entry with `recorded_by` + `recorded_at`, last-write-wins under `fcntl.flock`.
- **Session lifecycle**: Bound to the frontend session-control WebSocket. Tab close → session terminates → browser torn down → display + port released. Server-side heartbeat is the authoritative teardown signal; `beforeunload` is best-effort.

## Approaches Considered

### Infrastructure — parallel isolated browsers

| Option | Description | Decision |
|---|---|---|
| **A: Per-session Docker containers** | Every run spins up a fresh container (Playwright + Xvfb + noVNC + its own port). Cleanest isolation, easy teardown. | **Rejected for now**: needs a container orchestrator (Docker Compose scale, K8s, ECS service). Highest ops lift. Reserved as the natural upgrade path once beta usage justifies it. |
| **B: Single container, multi-display** | One long-lived container runs multiple Xvfb displays (`:1`, `:2`, …) with a separate `x11vnc` + `websockify` per display. Backend allocates a free display+port per run. | **Selected**. Matches the current single-container deploy. Real visual isolation. Cap at `MAX_CONCURRENT_SESSIONS` governed by container memory. |
| **C: Playwright cloud / browser-as-a-service** | Offload to Browserbase, Steel.dev, or similar. | **Rejected**: adds per-session cost, external dependency, and unfamiliar failure modes for a beta-stage internal tool. |
| **D: Playwright browser contexts** | Multiple `BrowserContext` in one Chromium instance sharing an Xvfb display. | **Rejected**: no visual isolation — all contexts render to the same X display. Fails the acceptance criterion. |

### Display allocation — pre-boot vs. lazy

| Option | Description | Decision |
|---|---|---|
| Pre-boot N triplets at container start | Simple, no runtime supervisorctl orchestration. | **Rejected**: each Xvfb + x11vnc + websockify triplet is ~50–70MB resident; 8 triplets = ~500MB baseline before any browser launches. Wastes memory when only 1 user is active. |
| **Lazy allocation on demand** | `DisplayAllocator.acquire()` calls `supervisorctl start xvfb_N x11vnc_N websockify_N` on demand; `release()` calls `supervisorctl stop`. Pre-declared as `[program:xvfb_N]` … with `autostart=false`. | **Selected**. Static supervisord config, dynamic lifecycle. No config reload, no XML-RPC config manipulation. |

### Supervisord dynamic process management

| Option | Description | Decision |
|---|---|---|
| Runtime config reload via supervisord XML-RPC | Add/remove `[program:x]` sections at runtime. | **Rejected**: supervisord `[program]` sections are compile-time; runtime add/remove is not clean. |
| **Pre-declared programs with `autostart=false`, controlled via `supervisorctl start/stop`** | Static config declares slots 1..N; runtime uses `supervisorctl` to start/stop them. | **Selected**. Keeps supervisord's existing pattern; no new components. Config is templated by `docker/entrypoint.sh` from `MAX_CONCURRENT_SESSIONS`. |
| Thin Python process manager (subprocess-based) | Replace supervisord's role for the multi-display programs. | **Rejected**: more flexible but abandons the existing supervisord pattern. Option 2 wins on simplicity. |

### ALB / reverse-proxy for session multiplexing

| Option | Description | Decision |
|---|---|---|
| N separate ALB path prefixes (`/session/1/vnc.html` → port 6081, …) | Explicit ALB rules per port. | **Rejected**: doesn't scale; ALB rule limits, ops burden per capacity bump. |
| **In-container nginx sidecar** | Nginx routes `/vnc/<sid>/*` (noVNC static) and `/websockify/<sid>` (WebSocket proxy) to the per-session port. ALB config stays dumb (path-prefix `/vnc/*`, `/websockify/*`). Nginx reads a map from `/var/run/vqa/sessions.map` written by `SessionManager` on ATTACHED/TERMINATED. | **Selected**. One new in-container component; one-line ALB rule change. |
| Single websockify with a custom token plugin | Websockify's `--token-plugin=TokenFile` maps tokens to backend hosts. | **Rejected**: elegant but requires a custom plugin and is less standard than nginx path routing. |

### WebSocket topology

| Option | Description | Decision |
|---|---|---|
| Replace `/ws/{run_id}` with `/ws/session/{session_id}` | Single WS per session, multiplexes run events. | **Rejected**: breaks existing per-run WS contract; complicates run-vs-session event routing on the frontend. |
| **Additive: keep `/ws/{run_id}`, add `/ws/session/{session_id}`** | Per-run channel unchanged (log/screenshot stream). New session-level control channel for lifecycle events + heartbeat. | **Selected**. Matches the existing codebase pattern (which already has `/ws/{run_id}` and `/ws/codegen/{session_id}`). |
| Rename ambiguity | Existing `/ws/codegen/{session_id}` uses "session_id" for a codegen-local scratch ID unrelated to the new auth-scoped session. | **Fix**: rename existing path variable to `codegen_id` to disambiguate. Small mechanical cleanup. |

### WebSocket authentication

| Option | Description | Decision |
|---|---|---|
| JWT in the WS first frame | Frontend sends `{"jwt": "..."}` as first message; server validates. Workaround for FastAPI's `Depends()` incompatibility with WebSockets (`backend/api/routes.py:129-132` documents the "silent TypeError" issue). | **Rejected** during security review: exposes the JWT on the WS lifetime, contradicting the goal of minimizing JWT surface. |
| **HttpOnly session cookie in the WS handshake** | Cookie sent by the browser automatically on the WS upgrade request; server reads `websocket.cookies["vqa_session"]`. JWT is only used at HTTPS boundaries (`/session/start`, `/session/rebind`, admin `DELETE /session/{id}`). | **Selected**. Minimizes JWT surface. Cleaner separation between authentication (JWT at three POST/DELETE boundaries) and authorization (cookie-scoped session ID everywhere else). |

### KB write concurrency

| Option | Description | Decision |
|---|---|---|
| Per-user staging area (`knowledge/staging/<user>/…`) with review/promote step | Each user's recording lands in staging first; admin promotes to shared KB. | **Rejected**: fragments the KB, breaks the "reusable artifacts" value prop. Slows down learning-loop iterations. |
| Shared KB with attribution + review gate for high-risk writes (JSON blueprints), auto-merge for low-risk (markdown append) | Hybrid. | **Rejected**: over-engineered for beta scale. If two users record contradictory workflows, that's a human coordination problem, not a system-design problem. |
| **Shared KB, last-write-wins under `fcntl.flock`, `recorded_by` + `recorded_at` attribution on every entry** | Simple, matches today's "KB is a shared team asset" mental model, adds attribution for accountability. | **Selected**. |

### KB lock library

| Option | Description | Decision |
|---|---|---|
| `filelock` PyPI package | Cross-platform, higher-level API. | **Rejected**: adds a new dependency for zero incremental value. |
| **`fcntl.flock` (stdlib)** | Alpine Linux in production, macOS locally both support it. Advisory, per-fd, releases on close. | **Selected**. Zero new deps. |

### Reconnect grace window

| Option | Decision |
|---|---|
| **`SESSION_RECONNECT_GRACE_SECONDS=0` (strict tab-close = kill)** | **Selected default** per user Decision 2 in brainstorm. |
| Non-zero grace (e.g., 30s to survive network hiccups) | Kept as a runtime knob, disabled by default. Bump if operational data justifies it. |

### JWT TTL enforcement at the vQA boundary

The vcAPI `SsoToken` has `exp: Optional[int]` (`backend/auth/sso.py:36`). If vcAPI issues a JWT without `exp`, PyJWT's `verify_exp` silently skips the check. vQA must not accept a forever-token.

**Selected**: `SsoValidator.validate_token()` uses `options={"verify_exp": True, "require": ["exp", "jti", "vc_id"]}`, plus a post-decode check that `(exp - now) <= MAX_JWT_TTL_SECONDS=3600`. Documented ADR: coordinate with vcAPI SSO owner before bumping. Defense-in-depth at the vQA edge is independent of vcAPI's issuance policy.

### Rebind cookie re-issue

Initial proposal issued the cookie only on `POST /session/start`. User security review flagged: without re-issuing on rebind, the cookie expires at the *original* JWT's `exp` and the session becomes unreachable from the browser — defeating the rebind flow entirely.

**Selected**: `POST /session/rebind` responds with `Set-Cookie` where `Max-Age = new_jwt.exp - now`, same flags as `/session/start`. Response body includes `next_rebind_by = jwt_valid_until - 90s` so the frontend schedules its own refresh timer.

### Observability transport

Codebase reality check: zero OpenTelemetry SDK imports, zero OTel packages installed, no OTLP exporter, plain-text `basicConfig` logging (`backend/main.py:80`). `CLAUDE.md`'s "OpenTelemetry First" is aspirational.

| Option | Description | Decision |
|---|---|---|
| Full OTel bootstrap | Install `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, instrumentation, stand up ADOT or otel-collector sidecar in Fargate. | **Deferred**: 5+ new packages, infra work (managed OTel service pricing + dashboards + collector deployment). Its own multi-phase project. Not blocking this feature. |
| **Structured JSON logs to stdout, CloudWatch captures via awslogs, Metric Filters + Alarms for aggregation** | Swap `basicConfig` for a stdlib-only `JsonFormatter`. Every metric from the original design becomes a CloudWatch Metric Filter on the JSON stream. Same log-event catalog, same alerts. Zero new dependencies. Accepted tradeoff: ~5 min metric aggregation latency (CloudWatch filter delay). | **Selected**. Documented as an explicit ADR-tracked deviation from `CLAUDE.md`. |

### `BrowserManager → SessionBrowserManager` sequencing

Blast radius on `backend/browser/context.py` (953 lines, LangGraph-wide coupling) is the highest-risk change in the feature. User pushback: land this as its own PR before anything else builds on it.

**Selected**: **Phase 0** introduces `SessionBrowserManager(id=...)` with an `__legacy_singleton__` backward-compat stub. All existing call sites keep working. Phase 4 removes the stub and converts every caller to session-scoped lookup. Two PRs, no half-migrated state in main.

### Frontend provider ordering

User callout: `AuthContext` (FEAT-048) owns the JWT; `SessionContext` depends on it. Silent nesting-order bugs would waste debug cycles in Phase 6.

**Selected**: Canonical mount order — `<AuthProvider><SessionProvider><AppShell/></SessionProvider></AuthProvider>`. `SessionProvider` throws a loud error if mounted outside `AuthProvider` (via `useAuth() === undefined` check). `SessionProvider` only calls `POST /session/start` after `useAuth().status === "authenticated"`.

### Teardown contract

User callout: `beforeunload` is unreliable (Safari iOS, various Chromium tightening). Cannot be the correctness path.

**Selected**: Session teardown contract is authoritative on **server-side heartbeat timeout**. Explicit close messages, `beforeunload` handlers, and `close(1000)` frames are best-effort optimizations that MAY accelerate detection but MUST NOT be required for correctness. Worst-case teardown latency = `WS_HEARTBEAT_TIMEOUT_SECONDS=15`.

---

## Selected Architecture (Summary)

- **Backend session subsystem** at `backend/session/` — `SessionManager`, `Session` dataclass, `SessionState` enum, `DisplayAllocator` (lazy, capacity-bounded), `lifecycle.terminate()` (7-step teardown), `nginx_map.py` (atomic map file writer).
- **Container multi-display topology** — templated `docker/supervisord.conf` with `xvfb_1..N`, `x11vnc_1..N`, `websockify_1..N` slots (`autostart=false`), rendered by `docker/entrypoint.sh` from `MAX_CONCURRENT_SESSIONS`. `DisplayAllocator` starts/stops via `supervisorctl`.
- **In-container nginx sidecar** — session multiplexer at `docker/nginx.conf`, reads `/var/run/vqa/sessions.map`, serves `/vnc/<sid>/*` (noVNC static) and proxies `/websockify/<sid>` to the per-session port. ALB config becomes path-prefix (`/vnc/*`, `/websockify/*`).
- **Session-scoped `SessionBrowserManager`** — Phase 0 refactor of `backend/browser/context.py`, backward-compat singleton stub, Phase 4 removes the stub.
- **Auth hardening** — `SsoValidator.validate_token()` requires `exp`, `jti`, `vc_id`, enforces `MAX_JWT_TTL_SECONDS=3600`; `backend/auth/revocation.py` `RevokedJtiSet` (in-memory LRU, TTL-scoped); `backend/auth/cookies.py` centralizes HttpOnly/Secure/SameSite=Lax logic; tightened CORS (`allow_headers` and `allow_methods` explicit lists); WS `Origin` validation on handshake.
- **WebSocket topology** — additive: existing `/ws/{run_id}` and `/ws/codegen/{codegen_id}` (renamed) unchanged, new `/ws/session/{session_id}` for lifecycle events + heartbeat. All auth via HttpOnly session cookie in handshake.
- **Session cookie** — HttpOnly, `Secure` (conditional on prod HTTPS scheme), `SameSite=Lax`, `Path=/`, `Max-Age = jwt.exp - now`. Re-issued on `POST /session/rebind` with fresh Max-Age.
- **JWT rebind flow** — `Session.jwt_valid_until` from `new_jwt.exp` at last rebind; periodic tick (`SESSION_TICK_INTERVAL_SECONDS=30`) terminates sessions where `jwt_valid_until + REBIND_GRACE_SECONDS(60) <= now`. Worst-case linger ~90s past JWT expiry.
- **KB write attribution** — every autorecord "Done" write via `KBWriter.append_with_lock` (`fcntl.flock`, 5s deadline, sidecar fallback on timeout). Every entry stamped `recorded_by: <session.user_email>` + `recorded_at: <iso8601>`.
- **Frontend** — `<AuthProvider><SessionProvider><AppShell/></SessionProvider></AuthProvider>`, capacity-reached full-page state, `useRebindTimer`, `useSessionWebSocket` (heartbeat), `SessionStatusIndicator`.
- **Observability** — structured JSON logs + CloudWatch Metric Filters + Alarms; homebrew request-scoped `trace_id` in `X-Request-Id` header; `LOG_FORMAT=json|text` env selector.
- **Rollout** — `SESSION_ISOLATION_ENABLED` kill switch; three stages (flag off compat → flag on `N=1` → flag on `N=4→8`).
- **Reconciliation loop** — every 30s tick, cross-check `supervisorctl status xvfb_<N>` against manager state; leaked slots trigger `session.allocator_leak` WARN and cleanup.

## Data Flow (illustrative)

```
Frontend (React)                     Backend (FastAPI, uvicorn --workers=1)                Nginx        Supervisord
     │                                       │                                              │             │
     │─ POST /api/session/start ────────────►│  SsoValidator.validate_token                 │             │
     │  Authorization: Bearer <jwt>          │  DisplayAllocator.acquire()                  │             │
     │                                       │  ───────────────────────────────────────────►│─ start N ──►│ Xvfb :N + x11vnc + websockify
     │                                       │  SessionManager.create(user_id, N)           │  60{80+N}   │
     │                                       │  nginx_map.write({sid: N})───────────────────►│(inotify)    │
     │◄─── 200 { session_id, novnc_url,      │                                              │             │
     │      jwt_valid_until, next_rebind_by }│                                              │             │
     │     Set-Cookie: vqa_session=...       │                                              │             │
     │                                       │                                              │             │
     │─ WS /ws/session/<sid> ───────────────►│  read cookie, validate Origin                │             │
     │  (cookie sent automatically)          │  attach to session                           │             │
     │◄─── session_ready { novnc_url }       │                                              │             │
     │                                       │                                              │             │
     │─ iframe src=novnc_url ───────────────────────────────────────────────────────────────►│             │
     │  /vnc/<sid>/vnc.html?path=            │                                              │───────────►│ (Xvfb :N)
     │       websockify/<sid>                │                                              │             │
     │                                       │                                              │             │
     │─ POST /api/execute ───────────────────►│  bind run to session, launch Playwright     │             │
     │  (session cookie sent)                │    with DISPLAY=:N                           │             │
     │                                       │  add run_id to session.active_run_ids        │             │
     │◄─── { run_id }                        │                                              │             │
     │                                       │                                              │             │
     │─ [work happens]                       │  [heartbeat ping every 15s]                  │             │
     │─◄─ [heartbeat pong every 15s]         │                                              │             │
     │                                       │                                              │             │
     │─ [tab close / network drop]           │                                              │             │
     │                                       │  heartbeat timeout → TERMINATING             │             │
     │                                       │  kill runs, close Playwright                 │             │
     │                                       │  supervisorctl stop xvfb_N ... ──────────────►│─ stop N ──►│ (processes exit)
     │                                       │  nginx_map.remove(sid) ──────────────────────►│             │
     │                                       │  release slot back to pool                   │             │
     │                                       │  emit session.terminated JSON log            │             │
     │                                       │                                              │             │
```

## Key ADRs (Architecture Decision Records)

| # | Decision | Alternatives | Consequence |
|---|---|---|---|
| ADR-1 | Multi-display in a single container (Option B) | Per-session containers (A); browser-as-a-service (C); browser contexts (D) | Matches existing single-container deploy; capped by container memory; upgrade path to A exists. |
| ADR-2 | Lazy display allocation via `supervisorctl start/stop` | Pre-boot N triplets | Baseline memory ≈ 0 for display infra; per-session ~700MB when active. |
| ADR-3 | In-container nginx multiplexer with atomic map file | N ALB rules; websockify token plugin | One new component (nginx); one-line ALB path-prefix change; static ALB config. |
| ADR-4 | HttpOnly session cookie for WS auth | JWT in first frame | Minimizes JWT surface; cleaner authn/authz split; consistent with browser cookie handling. |
| ADR-5 | `fcntl.flock` for KB writes | `filelock` package | Zero new dependencies; stdlib guarantee on Alpine + macOS. |
| ADR-6 | JWT `exp` + `jti` + `vc_id` required; `MAX_JWT_TTL_SECONDS=3600` enforced | Trust vcAPI's issuance policy | Defense-in-depth at the vQA edge; rejects forever-tokens if vcAPI ever omits `exp`. |
| ADR-7 | `RevokedJtiSet` in-memory only | Persistent revocation store | Container restart wipes it, but restart also kills every session; JWT `exp` provides the ultimate bound. |
| ADR-8 | Structured JSON logs + CloudWatch Metric Filters | Full OTel bootstrap | Zero new deps and infra; accepted ~5 min metric aggregation latency. Full OTel is future work. |
| ADR-9 | Phase 0 = `SessionBrowserManager` refactor with backward-compat singleton, its own PR | Big-bang refactor in Phase 1 | Isolates the highest-risk change; keeps main deployable at every phase boundary. |
| ADR-10 | `beforeunload` is best-effort; heartbeat is authoritative | Rely on client-initiated close | Correctness under browser quirks (Safari iOS), network drops, laptop-lid-close. |
| ADR-11 | `POST /session/rebind` re-issues Set-Cookie with new Max-Age | Cookie set only at `/session/start` | Without this, cookie expires at original JWT exp and rebind is unreachable. |
| ADR-12 | 60s rebind grace + 30s tick interval | 0s grace (strict expiry) | Frontend has time to complete vcAPI refresh + `/session/rebind` round-trip; worst-case linger ~90s past JWT expiry. |
| ADR-13 | `SESSION_RECONNECT_GRACE_SECONDS=0` default | Non-zero default | Strict tab-close semantics per user decision; knob available for operational tuning. |
| ADR-14 | `deploy.sh` edits use `Edit` tool with line-level scoping and pre-commit `grep` for secrets | `sed -i` full-file edits | The file has inline secrets (JIRA token, API key, shared password); scoped patches prevent accidental exfiltration to logs/artifacts. |
| ADR-15 | Templated `supervisord.conf` rendered by `docker/entrypoint.sh` | Hand-maintained 24-block static file | Ergonomic scaling of `MAX_CONCURRENT_SESSIONS`; single source of truth for slot count. |

## Non-Goals (Explicitly Deferred)

- Full OpenTelemetry bootstrap (ADR-8).
- Prometheus client library / scrape endpoint.
- Distributed traces across LLM providers.
- Per-user KB fragmentation.
- Cross-worker session sync (single-worker uvicorn is a hard invariant per `supervisord.conf:115`).
- Persistent session state across container restarts.
- Admin impersonation of vQA users (`Session.ghosted_by` withdrawn; vQA "ghost login" is a vSuite-level in-run action).
- Migration of `deploy.sh` inline secrets to AWS Secrets Manager.
- Blue/green deployment for the rollout (Fargate task is single-instance; rollout is staged via `SESSION_ISOLATION_ENABLED` kill switch instead).

## Deviation Flags

- **`productBrief.md`** — "single `settings.novnc_port`" description is superseded by the session-scoped URL schema. Update lands in Phase 3.
- **`CLAUDE.md`** — "OpenTelemetry First" observability standard is aspirational vs. the current plain-text `basicConfig` implementation. This feature ships structured JSON logs as an explicit ADR-8-tracked deviation.

## Open Questions Resolved During Brainstorm

- **Concurrency model** → true parallelism (user Decision).
- **Infra shape** → multi-display in one container (user selected Option B).
- **KB attribution** → shared with `recorded_by` + `recorded_at`, last-write-wins under lock (user Decision 1).
- **Session lifecycle** → tab close = terminate; server heartbeat is authoritative (user Decision 2 + security callout).
- **Nesting order** → `AuthProvider > SessionProvider > AppShell` with runtime guard (user callout).
- **Observability** → JSON logs, not OTel (user reality-check pushback).
- **Refactor sequencing** → `SessionBrowserManager` gets its own Phase 0 PR (user pushback on blast radius).
- **Lock library** → `fcntl.flock`, not `filelock` package (user callout: decide now, not defer).

## Handoff to `/bmb:build`

Phase 0 is the entry point. It refactors `backend/browser/context.py` and lands with `__legacy_singleton__` backward-compat before any other phase code merges. The full 8-phase sequence is in `memory-bank/tasks/per-user-session-isolation.md` § Implementation Roadmap.
