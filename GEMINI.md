# vQA Project Rules and Conventions

## Agent Workflows
- **Code Review Protocol**: Any code written or modified by an agent MUST be reviewed by a different sub-agent or agent persona before it is considered complete. This ensures another layer of validation and catches syntax or architectural errors (e.g., indentation errors, unused code) that the authoring agent might have missed.
- **VC Workflow Adherence**: Strict adherence to the VC Workflow (PLAN -> BUILD -> REFLECT -> ARCHIVE) is MANDATORY for all `/vc-` commands. Initialization of tasks in the Memory Bank must occur BEFORE any implementation begins. This is enforced by a critical agent rule in `memory-bank/agent-rules/vc-workflow.md`.
- **Feature Interrogator Human Sign-off Gate**: When running or activating the `feature-interrogator` skill (or performing any design interrogation/review), the agent MUST halt after completing the design review and creating the report (`.agent-logs/interrogations/<TARGET_ID>-interrogation-report.md`). The agent is STRICTLY FORBIDDEN from starting any file modifications or code changes until a subsequent, explicit human Directive (e.g., instructions to implement) is received.

## Post-Mortem & Analysis Integrity

These rules govern any post-mortem, reliability analysis, or architectural assessment produced by an agent.

- **No Fabricated Metrics**: NEVER use a theoretical placeholder as a reliability figure (e.g., "assuming 95% per-node success rate"). All metrics cited in a post-mortem MUST be derived from actual log data (`session-*.jsonl`, `benchmark_report.json`). If empirical data does not exist, state that explicitly: *"Empirical per-node failure rate: unmeasured — pending log parse."*
- **No Borrowed Numbers**: NEVER echo a reliability figure supplied by a human in the conversation (e.g., "couldn't hit 10%") without first verifying it against actual run data. If no data exists, the agent must say so and use 0/N from the benchmark as the baseline.
- **Failure Math Must Cite Per-Node Rates**: Any compounding failure probability calculation must state its source assumption. If per-node rates are assumed, the calculation must be labeled `[THEORETICAL]`. If derived from logs, label it `[EMPIRICAL]`.
- **Correlated Failures Must Be Acknowledged**: Do not model multi-stage pipeline failures as independent Bernoulli trials. State explicitly when failures are correlated (Markov chain) and note that real-world reliability is *worse* than the naive product.
- **"Repaired" Requires a Success Rate**: Never declare a component "repaired" without a measurable output success rate. Internal logic correctness ≠ production readiness. Cite the benchmark run result (e.g., `0/10 = 0%`) alongside any repair claim.

## Architecture Decision Rules

These rules apply before any architectural pivot or new execution strategy is proposed.

- **Fallback Reliability Must Be Proven Before Proposed**: Never propose a fallback mechanism (e.g., "LLM catches failures") without first stating its measured or estimated success rate on the target failure mode. A 0% fallback is a false confidence layer, not a safety net.
- **Visual Delta Is Not a Trust Signal**: DOM-count diffing and ARIA tree diffing have a known high false-positive rate (loading spinners, toast notifications, cursor blinks all trigger them). NEVER use visual delta as the sole success signal for an action. Verification must be deterministic: use explicit `await expect(locator).toBeVisible()` state assertions, not "did the DOM change?"
- **Recipe/Fixture Backbone Requires Dedicated Tests**: Any helper utility promoted to a critical fast-path (e.g., `SearchHelper.ts`) MUST have a dedicated unit test suite before it is used in production execution. Implicit end-to-end coverage is NOT sufficient. Minimum contract: cover the happy path, the already-open guard, the catch/fallback block, and at least one PrimeNG-specific failure mode.
- **Business Alignment Gates Implementation**: A product architecture pivot (e.g., "autonomous agent" → "recipe-backed runner") cannot be implemented until the Product Owner has explicitly signed off on the value proposition change. No implementation work begins on a redefined architecture until this sign-off is documented in the task file under `## Business Alignment`.
- **LLM Role Is Pre-Run or Post-Run, Not Real-Time**: On dynamic SPAs (Angular/PrimeNG), LLMs must NOT be used for real-time, zero-shot DOM traversal as the primary execution path. Valid LLM roles: (1) pre-run test code generation from AC, (2) post-run log analysis and failure explanation. Real-time LLM reasoning is only permissible as a CV fallback after deterministic Playwright exhaustion.

## Reliability Standards

- **Reliability Targets Require Denominators**: Every reliability target (e.g., "80% completion rate") MUST define: (1) what counts as a success unit (step? card end-to-end? card with zero HITL?), (2) the test corpus (which cards, how many), and (3) the environment (local/staging/production-equivalent). Targets without denominators cannot be tracked or validated.
- **Per-Node Failure Distribution Before Rewrite**: Before any execution layer rewrite is proposed, the agent MUST parse `session-*.jsonl` to produce an empirical per-node failure distribution table: `(Planner→Executor, Executor→Verifier, Verifier→Evaluator, Evaluator→Decision)`. This is the minimum evidence required to scope a rewrite.

## Infrastructure & Runtime Debugging

These rules govern how agents diagnose and fix runtime, container, display, and process-level issues. See `memory-bank/agent-rules/_learned/infrastructure-debugging.md` for the full set.

- **Evidence Before Code (EBC)**: When debugging a runtime or infrastructure issue (browser not showing, process not starting, display not mapping, VNC not streaming), the agent MUST collect empirical evidence from the **actual running environment** BEFORE writing or modifying any code. "Pytest passes" is NEVER evidence that a runtime behavior works. Minimum diagnostics: `docker exec` process inspection, environment variable verification, subsystem health checks (e.g., `xdpyinfo`, socket handshakes), and live application log review.
- **Two-Iteration Escalation Rule**: If a runtime/infra fix has been attempted twice without empirical validation from the target environment, the agent MUST stop writing code and switch to **pure diagnostics mode**. The third iteration must consist exclusively of evidence collection (container exec, log analysis, process inspection) before any further code changes are proposed. This prevents the "guess-and-check" anti-pattern.
- **Configuration Layer Tracing**: Before modifying environment variable handling in Docker-based deployments, the agent MUST trace the full inheritance chain: `Dockerfile ENV` → `docker-compose environment:` → `supervisord environment=` → `os.environ` in Python. Removing a variable at one layer is cosmetic if a higher-priority layer still sets it.
- **Platform Guard Scoping**: NEVER use `sys.platform` or `os.path.exists("/.dockerenv")` to gate container-specific behavior. Use the application's own deployment mode enum (`VQA_MODE`) which is explicitly set per deployment target.

## Playwright Test Fixing Rules

These rules govern how agents diagnose and fix failing Playwright tests, particularly failures that occur on the vQA production runner (AWS Fargate) but pass locally. They exist because agents have repeatedly misdiagnosed infrastructure-caused failures as application-level bugs.

- **Bind Infrastructure Constraints Before Proposing Fixes**: Before proposing or implementing a test fix, search the backend codebase for hardcoded timeouts, subprocess limits, and environmental variables. Specifically check: `timeout=360.0` in `_run_single_suite_test()` (`playwright_routes.py`), `VQA_SUITE_WORKERS` in `_run_suite_orchestrator()`, and the Fargate task definition CPU/memory in `deploy.sh`. If a test's `test.setTimeout()` exceeds the orchestrator's subprocess timeout, resolve the configuration mismatch first — the test is being SIGTERM'd, not crashing.
- **Reproduce in Headless Locally, Not via Ephemeral Traces**: Since Fargate runs are ephemeral and Playwright traces are not persisted to an external volume, agents are strictly forbidden from assuming trace analysis is available. Reproduce failures locally in headless mode: `VQA_HEADLESS=1 TEST_ENV=qa STORAGE_DIR=$(pwd)/playwright/storage/qa npx playwright test <path> --project=chromium`. Examine the error snippet captured by `_extract_playwright_error()` in `playwright_routes.py` for production failures.
- **Pragmatic Scope Matching Over Dogmatism**: Match test workload to the runner's physical constraints. If a test can be split into sequential files or its loop iterations reduced to fit within the 360s subprocess limit while exercising the same code paths, implement that change immediately. Do NOT propose complex state-restoration or context-recycling schemes that would destroy active Angular component state. Document any scope reduction in a code comment citing the infrastructure constraint (e.g., `// Reduced from 10 to 5 spots to fit 360s subprocess timeout — see playwright_routes.py L1056`).
- **No External DB/API Dependencies**: The target application (qa.vcreative.net) is a closed box. Agents cannot seed data, modify its database, or run API calls against it. Write robust fallback-selection logic in Playwright (e.g., selecting the first visible row if a specific match is missing) rather than assuming a pristine environment state or proposing seeding scripts.
- **Playwright Input Best Practices**: Use `.fill()` for autocomplete and standard text inputs to minimize Angular change-detection cycles — do NOT use `.pressSequentially()` which fires individual keypress events and is unreliable under headless CPU contention. Only use picker/ARIA keyboard navigation for strictly `readonly` inputs (e.g., PrimeNG `p-datepicker` in popup mode). Never use `waitUntil: 'networkidle'` — the target SPA maintains persistent WebSocket connections that prevent the network from ever going idle, causing guaranteed deadlocks. Use `waitUntil: 'domcontentloaded'` instead.

## Local Development Setup

### First-Time Setup (per OS)

| Step | macOS / Linux | Windows (PowerShell) |
|------|---------------|---------------------|
| Create Python venv | `python3 -m venv .venv && source .venv/bin/activate` | `python -m venv .venv` |
| Install Python deps | `pip install -r requirements.txt` | same |
| Install JS deps | `npm install` | same |
| Copy env file | `cp .env.example .env` | `Copy-Item .env.example .env` |
| Fill in secrets | Edit `.env` — see `DEPLOYMENT.md` for required vars | same |
| Generate storage states | `node playwright/utils/generateStorageStates.mjs` | same |
| Start the app | `./start.sh` | `.\start.ps1` |

> **Windows note**: `.venv` activation is handled automatically by `start.ps1`. You do **not** need to activate it manually before running the app. Both scripts load `.env`, activate the venv, kill port conflicts (8000 + 5173), poll health, and stream logs.

### Daily Workflow

```bash
# Start (backend :8000 + frontend :5173)
./start.sh          # macOS/Linux
.\start.ps1         # Windows

# Stop
./start.sh --stop
.\start.ps1 -Stop
```

### Storage State Regeneration

Storage states cache pre-authenticated browser sessions so tests don't re-login every run:

```bash
# Regenerate all users for test environment (default)
node playwright/utils/generateStorageStates.mjs

# Specific environment
TEST_ENV=qa node playwright/utils/generateStorageStates.mjs          # macOS
$env:TEST_ENV='qa'; node playwright/utils/generateStorageStates.mjs  # Windows
```

Files land in `playwright/storage/<TEST_ENV>/storageState_<username>.json`. Users are defined in `playwright/fixtures/users/users.json`.

### Adding a New Product

1. Add an entry to `backend/config/products.yaml` (the single source of truth — no Python changes needed)
2. If the product lives on a **different domain** from `*.vcreative.net` after login (cross-domain, e.g. a PHP app), also add:
   ```yaml
   playwright_base_url:
     <env>: <full URL the test should navigate to after login>
   ```
3. Add users to `playwright/fixtures/users/users.json` with `"product": "<slug>"` and `"productUrl": "<same URL>"` for cross-domain products
4. Export a `PRODUCT_BASE_URL` constant from `playwright/utils/setup.ts`
5. Run `node playwright/utils/generateStorageStates.mjs` to capture storage states
6. See `playwright/CLAUDE.md` → Multi-Product Architecture for test writing conventions

## VC Workflow Commands

This project uses the **VC Workflow** system (Antigravity Memory Bank) for structured development. All workflows are in `.agent/workflows/`.

### Core Pipeline

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/vc-init` | Initialize/refresh Memory Bank | First time or after major changes |
| `/vc-task <text\|JIRA-KEY>` | Create a task with AC | Start of every task |
| `/vc-plan TASK-XXX` | Write detailed spec + test strategy | L2+ features |
| `/vc-creative TASK-XXX` | Design exploration | L3-4 features |
| `/vc-build TASK-XXX` | TDD build (tests → code → review → docs) | Every build |
| `/vc-reflect TASK-XXX` | Post-build analysis & learning | After build |
| `/vc-archive TASK-XXX` | Commit → push → PR link | When done |

### Utility Commands

| Command | Purpose |
|---------|---------|
| `/vc-verify` | Run lint + typecheck + build + tests |
| `/vc-review` | Manual code review |
| `/vc-document` | Update docs without a full build |
| `/vc-write-tests` | Manual RED phase (write tests only) |
| `/vc-implement` | Manual GREEN phase (implement only) |
| `/vc-jira-setup` | Configure Jira credentials |
| `/vc-roadmap` | Manage feature roadmap |
| `/vc-scan-arch` | Scan and document architecture |
| `/vc-rules-index` | Index project-specific coding rules |
| `/vc-uat-init` | Set up browser acceptance testing |
| `/vc-uat` | Run browser acceptance tests |

### Design Commands (used inside `/vc-creative`)

| Command | Purpose |
|---------|---------|
| `/vc-design-ui` | UI/UX component design |
| `/vc-design-arch` | Architecture design |
| `/vc-design-algo` | Algorithm design |
| `/vc-design-journey` | User journey mapping |

### Memory Bank

All Memory Bank files live in `memory-bank/` — see `CLAUDE.md` for the full file index and workflow conventions.

### Complexity Levels

| Level | Example | Build Strategy |
|-------|---------|---------------|
| **L1** | Fix a typo, rename a variable | Inline fix — no sub-agents |
| **L2** | Add a form field, fix a bug | Full TDD with sub-agents |
| **L3** | New feature, API endpoint | TDD + design exploration |
| **L4** | Architecture change, migration | TDD + mandatory human gates |

### Tech Stack (vQA)

- **Backend**: Python 3.12, FastAPI, LangGraph, Playwright
- **Frontend**: React 19+, Vite, TypeScript
- **Tests**: pytest (`pytest tests/ -v`)
- **Dev Server**: `./start.sh` (macOS/Linux) · `.\start.ps1` (Windows) — backend:8000 + frontend:5173