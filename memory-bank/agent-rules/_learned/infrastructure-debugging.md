---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: infrastructure-debugging

_Extracted from TASK-113 post-mortem: 7-iteration display-mapping fix that should have been resolved in 1-2 iterations._

---

## Rules

### Evidence-Before-Code (EBC) — MANDATORY for Runtime/Infra Issues

- **empirical-diagnostics-first** (`docker/`, `backend/browser/`, `backend/api/playwright_routes.py`): When debugging a runtime or infrastructure issue (browser not showing, process not starting, display not mapping, VNC not streaming), you MUST collect empirical evidence from the **actual running environment** BEFORE writing or modifying any code. "Pytest passes" is never evidence that a runtime behavior works. Minimum diagnostics for container/display issues:
  1. `docker exec` into the container and inspect the live process tree (`ps aux | grep <process>`)
  2. Verify the environment variables the process actually inherited (`cat /proc/<pid>/environ | tr '\0' '\n'`)
  3. Check the specific subsystem (e.g., `xdpyinfo -display :99` for X11, socket handshake for VNC)
  4. Inspect application logs from the running process, not from pytest output
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x

### Configuration Layering Awareness

- **dockerfile-env-awareness** (`docker/Dockerfile`, `docker/supervisord.conf`, `docker-compose*.yml`): Before modifying environment variable handling, trace the full inheritance chain: `Dockerfile ENV` → `docker-compose environment:` → `supervisord environment=` → `os.environ` in Python. A variable set in the Dockerfile `ENV` layer propagates to ALL processes in the container. Removing it from supervisord is cosmetic if the Dockerfile still sets it. Always check ALL layers before claiming a variable is "unset."
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x

### Single Source of Truth for Cross-Cutting Logic

- **shared-helper-over-inline-duplication** (`backend/browser/context.py`, `backend/api/`, `backend/engine/`): When the same environment or configuration resolution logic appears in more than one code path, extract it into a single shared helper function immediately. Do NOT copy-paste with "slight variations" — divergent behavior between code paths is a maintenance landmine that causes bugs when one path is fixed but the other is forgotten. The helper MUST have its own unit test suite covering all branches.
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x

### Runtime vs. Unit Test Proof Hierarchy

- **proof-hierarchy-for-runtime-claims** (`tests/`, `docker/`): When claiming a runtime fix works, evidence must be presented in this priority order. Lower tiers alone are INSUFFICIENT for runtime/infra claims:
  1. **Tier 1 (Required)**: Live environment evidence — screenshot/recording from the running system, `docker exec` diagnostics, socket handshakes, actual log output from the process
  2. **Tier 2 (Supplementary)**: Integration test that exercises the real subprocess/service
  3. **Tier 3 (Necessary but not sufficient)**: Unit tests with mocks — proves code correctness, NOT runtime behavior
  - Stating "all 24 tests pass" as sole evidence for a container display issue is explicitly prohibited. Mocked tests cannot prove X11, VNC, or process inheritance behavior.
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x

### Platform-Conditional Code Scoping

- **scope-platform-guards-to-deployment-mode** (`backend/`): Never use `sys.platform` or `os.path.exists("/.dockerenv")` to gate container-specific behavior. These heuristics are fragile — `sys.platform == "linux"` is true on bare-metal CI runners, and `/.dockerenv` doesn't exist in ECS Fargate. Instead, use the application's own deployment mode enum (`VQA_MODE`) which is explicitly set per deployment target and is always reliable.
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x

### Iteration Discipline

- **two-iteration-escalation-rule** (`*`): If a fix has been attempted twice without empirical validation from the target environment, the agent MUST stop writing code and switch to pure diagnostics mode. The third iteration must consist exclusively of evidence collection (container exec, log analysis, process inspection) before any further code changes are proposed. This prevents the "guess-and-check" anti-pattern that caused TASK-113 to consume 7 iterations.
  - _Source_: reflection-TASK-113 (2026-06-08)
  - _Reinforced_: 0x
