---
version: next
linked_tasks: [per-user-session-isolation]
status: completed
priority: high
complexity: 4
created: 2026-08-06
completed: 2026-08-07
---

### per-user-session-isolation: Per-User Session Isolation for vQA Runs

- **Status**: completed (2026-08-07 — see `memory-bank/archive/per-user-session-isolation-archive.md`)
- **Version**: next
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Eliminate the shared-singleton browser architecture and scope every vQA run (Record a Demo, replay, AC-driven test execution) to the authenticated user who initiated it. Today, user A starting a "Record a Demo" and user B logging in from a different machine and clicking "Record a Demo" both attach to the same Playwright browser via a single noVNC stream — B sees A's session. This feature introduces a first-class `Session` keyed by the JWT-authenticated user, a `DisplayAllocator` (lazy, capacity-bounded) that provisions per-session Xvfb + x11vnc + websockify triplets on demand via supervisord's static-declared / dynamic-lifecycle pattern, an in-container nginx sidecar that multiplexes `/vnc/<session_id>/*` and `/websockify/<session_id>` to the right port so the ALB config stays static, session-scoped `SessionBrowserManager` instances (replacing the module-level singleton in `backend/browser/context.py`), auth-hardened boundaries (JWT `exp`/`jti`/`vc_id` required, `MAX_JWT_TTL_SECONDS=3600` enforced, in-memory `RevokedJtiSet`, HttpOnly Secure SameSite=Lax session cookies with explicit Set-Cookie re-issue on `POST /session/rebind`, `Origin` validation on WebSocket handshakes), and KB write attribution (`recorded_by` + `recorded_at` on every autorecord entry, `fcntl.flock`-guarded last-write-wins). Session lifecycle is bound to the frontend session-control WebSocket via server-side heartbeat (authoritative), with `beforeunload` as a best-effort optimization. Ships behind a `SESSION_ISOLATION_ENABLED` kill switch with staged rollout (single-user compat mode → multi-user cap of 4 → 8). Explicit ADR-documented deviations: (1) `productBrief.md`'s single `settings.novnc_port` description is superseded by the session-scoped URL schema; (2) `CLAUDE.md`'s OpenTelemetry standard is aspirational — this feature ships structured JSON logs + CloudWatch Metric Filters + Alarms, with full OTel bootstrap deferred as follow-up work.
- **Linked Tasks**: per-user-session-isolation
- **Branch**: feature/per-user-session-isolation
- **Created**: 2026-08-06

**Complexity rationale**: inferred by /bmb:brainstorm — architectural rework spanning auth boundary hardening, new backend session subsystem (SessionManager + DisplayAllocator + lifecycle state machine + nginx-map projection), in-container multi-display infrastructure (templated supervisord, nginx sidecar, entrypoint renderer), frontend context/hooks refactor (SessionContext, useSessionWebSocket, useRebindTimer, capacity-reached UX), ALB path-prefix change, Fargate memory sizing bump, 8 sequenced phases including a dedicated Phase 0 for the high-risk `BrowserManager → SessionBrowserManager` refactor with backward-compat singleton stub, and a staged rollout behind `SESSION_ISOLATION_ENABLED` with three enablement stages. Blast radius touches auth, browser lifecycle, WebSocket topology, KB write path, container orchestration, and load-balancer routing — every hallmark of Level 4.
