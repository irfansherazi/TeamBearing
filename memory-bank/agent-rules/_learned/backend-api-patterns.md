---
derived_from: [nightly-scheduled-playwright-test-suite-run]
evidence_count: 2
last_validated: 2026-08-11
---
# Learned Rules: backend-api-patterns

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **dedicated-subrouter-pattern** (`backend/api/`): For any feature that adds ≥3 new endpoints, create a dedicated `backend/api/{feature}_routes.py` FastAPI sub-router rather than appending to `routes.py`. Mount it in `main.py` with `app.include_router(router, prefix="/feature")`. Keep module-level semaphores, locks, and PID tracking dicts scoped to the sub-module — this prevents cross-feature state leakage and makes the module independently testable and replaceable.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **subprocess-concurrency-gate** (`backend/api/`): When an endpoint can spawn resource-intensive subprocesses (e.g., browser-based test runners, auth generators), always add a concurrency gate: `asyncio.Semaphore(N)` for parallel processes, `asyncio.Lock` for serialized-only processes. Expose the limit in config (default to a safe low value like 2). Return HTTP 429 with a clear `{"detail": "Too many concurrent X runs. Max: N"}` when the gate is saturated. Never let unlimited subprocess spawning reach the OS.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **pid-tracking-cleanup** (`backend/api/`, `backend/main.py`): When spawning subprocesses via `asyncio.create_subprocess_exec`, track PIDs in a module-level dict (`_pids: dict[str, int]`). Register a FastAPI lifespan shutdown handler that iterates the dict and sends `SIGTERM` to all live PIDs. Without this, long-running subprocesses (e.g., Playwright tests running for minutes) become orphaned when the FastAPI server restarts under a process manager.
  - _Source_: reflection-TASK-060 (2026-05-27)
  - _Reinforced_: 0x

- **subprocess-env-var-path-override** (`backend/api/playwright_routes.py`, `playwright/utils/setup.ts`): When spawning a subprocess that uses a tool config file (e.g., `playwright.config.ts`) that resolves paths relative to a CWD, pass absolute-path env vars (`STORAGE_DIR`, `DATA_DIR`) to override internal relative-path logic. `asyncio.create_subprocess_exec` inherits the backend server's CWD, which is almost never the same as the Playwright project root. Relying on CWD matching produces silent path-resolution failures (e.g., "No available users detected") that are hard to diagnose without headed mode.
  - _Source_: reflection-TASK-061 (2026-05-27)
  - _Reinforced_: 0x

- **cli-flag-prevalidate** (`backend/api/playwright_routes.py`): Before implementing a CLI-flag-based workaround for a subprocess tool, verify the flag exists via `--help` (e.g., `npx playwright test --help`). Playwright's CLI does not include `--headless` (only `--headed`). Building a feature around an invalid CLI flag requires full reversal. For Playwright specifically: use `headless: <bool>` in `playwright.config.ts` as the primary authority; `--headed` as a belt-and-suspenders override only.
  - _Source_: reflection-TASK-061 (2026-05-27)
  - _Reinforced_: 1x (TASK-062: headed mode regression confirmed same vector)

- **isci-ecs-headless-danger** (`playwright.config.ts`, `backend/api/playwright_routes.py`): In ECS/container deployments, the `CI` environment variable is **always** `true`. Any Playwright config property gated on `isCI` will behave as if in CI — including `headless: isCI` evaluating to `true`. The correct contract for vQA: `headless` must always be `false` (unconditional). Use `isCI` only for properties that legitimately differ between CI and production (e.g., `retries`, sandbox `launchOptions`, browser selection). Gating `headless` on `isCI` survived local testing but failed in production within the same day — twice (TASK-061 → TASK-062 regression cycle).
  - _Source_: reflection-TASK-062 (2026-05-28)
  - _Reinforced_: 0x

- **regression-prevention-comment** (`playwright.config.ts`, config files): When a change is required to prevent a known, specific regression vector (e.g., "do not gate on isCI for headless"), embed the prevention note as an inline comment immediately adjacent to the changed line — not only in the commit message or task file. The inline comment is the only artifact visible at the point of future modification. A future engineer editing the config may never consult git history. Pattern: `// NOTE: Do NOT [pattern] here — because [environment-specific reason]`.
  - _Source_: reflection-TASK-062 (2026-05-28)
  - _Reinforced_: 0x

- **secret-env-injection** (`backend/secrets.py`): When resolving secrets via external providers (SSM, Vault, Secrets Manager), inject the final resolved values into `os.environ`. This provides a backward-compatibility bridge for legacy modules that use `os.getenv` directly, avoiding the need for a system-wide refactor of credential resolution while still centralizing the resolution logic in `secrets.py`.
  - _Source_: reflection-TASK-075 (2026-05-29)
  - _Reinforced_: 0x

- **ws-broadcast-signature-idempotency** (`backend/api/routes.py`): When extending WebSocket broadcast functions (e.g., `_broadcast_human_takeover`), always use keyword arguments with `None` defaults to ensure backward compatibility for test mocks and legacy call sites. This prevents `TypeError` crashes when new parameters are added but not yet passed by all callers.
  - _Source_: reflection-TASK-082 (2026-05-31)
  - _Reinforced_: 0x

- **circular-import-re-export-pattern** (`backend/engine/ac_parser.py`, `backend/api/routes.py`): When Module A (e.g., `ac_parser.py`) defines shared state that Module B (e.g., `routes.py`) needs to expose, but B is imported by A at runtime (circular), place the state and any helper in A, use lazy local imports in A when accessing B's runtime data (inside function bodies, not at module top), and re-export A's symbols from B at module level (`from backend.engine.ac_parser import _pre_parse_events`). This pattern: (1) avoids circular import at load time, (2) allows external callers (tests, other modules) to reference `routes._pre_parse_events` via the re-export, and (3) requires no monkey-patching or `importlib` hacks.
  - _Source_: reflection-TASK-096 (2026-06-03)
  - _Reinforced_: 0x

- **stacked-router-decorator-head-pattern** (`backend/api/routes.py`): When an endpoint needs to support HTTP `HEAD` requests in addition to `GET` (for example, to allow frontend pre-flight availability checks or HEAD probing), use FastAPI's stacked decorator pattern: stack `@router.head` directly beneath `@router.get` on the same path handler, and specify `include_in_schema=False` on the `HEAD` decorator. This avoids duplicating any route handling logic and lets Starlette's ASGI pipeline automatically strip the response body while keeping all headers (like `Content-Length` and `Content-Type`) completely identical.
  - _Source_: reflection-TASK-111 (2026-06-08)
  - _Reinforced_: 0x

- **pipeline-transform-and-analyze-tuple** (`backend/engine/codegen_*.py`): When a pipeline step must both transform input and analyze the output in a single atomic operation, expose a combined function returning a tuple `(result, metadata | None)` and keep the original single-return function as a thin wrapper for backward-compatible callers. The `None` in the tuple is the graceful-degradation signal — callers use `if metadata is not None` guards rather than try/except. This avoids two separate service calls and preserves call-site compatibility.
  - _Source_: reflection-TASK-121 (2026-07-14)
  - _Reinforced_: 0x

- **scheduled-trigger-endpoint-pattern** (`backend/api/*_routes.py`): For scheduled-trigger endpoints (EventBridge Scheduler, cron, external webhooks) that dispatch a longer-running job, return `202 Accepted` + `{job_id}` immediately and run the poll-and-notify cycle in an asyncio background task (`asyncio.create_task(_poll_and_notify(...))` inside the handler). Keeps the HTTP connection short-lived so external schedulers with strict response timeouts (EventBridge API destinations have a hard cap) don't time out mid-run. The background task polls the in-process store — no HTTP round-trip — and posts terminal-state notification to the configured sink (Slack, webhook, etc.). Contrast with foreground endpoints that block until completion.
  - _Source_: reflection-nightly-scheduled-playwright-test-suite-run (2026-08-11)
  - _Reinforced_: 0x

