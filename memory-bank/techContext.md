# Tech Context

## Technology Stack

### Backend (Python)
- **Runtime**: Python 3.12
- **API Framework**: FastAPI 0.115+ (async REST + WebSocket at `/ws/{run_id}`)
- **Agent Orchestration**: LangGraph 0.2+ (StateGraph with 10 nodes)
- **Browser Automation**: Playwright 1.49+ (async_api, Chromium, video recording)
- **LLM Provider**: `langchain-aws` — ChatBedrockConverse (Claude 3.5 Sonnet via AWS Bedrock)
- **AWS SDK**: boto3 (S3 put/get, Bedrock Knowledge Base retrieval)
- **Data Validation**: Pydantic 2.7+
- **Knowledge Retrieval**: scikit-learn (TF-IDF vectorizer for KB RAG)
- **Process Manager (Docker)**: supervisord

### Frontend (JavaScript/TypeScript)
- **Framework**: React 19+
- **Build Tool**: Vite 8+
- **Language**: TypeScript 5.9+
- **Dev Server Port**: 3000
- **Routing**: React Router (router.tsx) — protected routes, auth guard
- **Auth**: Independent React Auth System (`src/auth/`) — JWT/RS256 session management, MFA, vcAPI SSO integration
- **Key Components**: Dashboard, ProductSelector (product context anchor, FEAT-115), ExecutionPanel, LiveBrowser (noVNC iframe), ExecutionLog, TakeoverPanel, CopilotSidebar (AC tracker + HITL), TriagePanel (failure analysis), ReportsArchive, AnalyticsDashboard, PlaywrightLibrary (static test browser), LoginPage, MfaPage
- **Key Contexts**: ProductContext (active product slug + environments, persisted to `localStorage['vqa_product']`, FEAT-115)

### Infrastructure
- **Containerization**: Docker (multi-stage Dockerfile)
- **Orchestration**: docker-compose.yml (interactive), docker-compose.ci.yml (headless CI)
- **Virtual Display**: Xvfb + x11vnc + noVNC (for live browser streaming in interactive mode)
- **Dynamic VNC Routing**: Runtime URL construction (VncUrlBuilder) based on Request headers to support remote host access in Docker/Production environments.
- **Task Automation**: Makefile

### External Services
- **AWS Bedrock**: Claude 3.5 Sonnet (multimodal planner), Claude Haiku (verifier fallback)
- **AWS Bedrock KB**: JXMMTMTI06 (vSuite Roles Knowledge Base)
- **AWS S3**: `vcreative-deployments/vSuitePlatform/Buildartif/vqa-results/` (screenshots, videos, reports)
- **Jira REST API v3**: Basic Auth (email + API token) — fetches AC from `customfield_10031`

## Development Commands

### Local Development
```bash
./start.sh           # Start backend (port 8000) + frontend (port 3000)
./start.sh --stop    # Stop both services
```

- **Windows**: `.\start.ps1` / `.\start.ps1 -Stop` — feature-for-feature equivalent; loads `.env`, activates `.venv`, kills port conflicts, health-polls, streams logs

### Backend
```bash
cd backend && uvicorn main:app --port 8000 --reload   # Dev server
python -m backend.cli --ticket VC2-8967 --role account_executive  # CLI runner
pytest tests/ -v     # Run unit tests
```

### Frontend
```bash
cd frontend && npm install   # Install deps
cd frontend && npm run dev   # Dev server (port 3000)
cd frontend && npm run build # Production build
```

### Docker
```bash
docker compose up --build              # Interactive mode (all services)
docker compose -f docker-compose.ci.yml up --build  # Headless CI mode
```

### Knowledge Base
```bash
make kb-refresh       # Re-extract selectors from Playwright tests
make kb-human-sync    # Upload human_guidance.md to Bedrock KB
python scripts/sync_human_kb.py       # Direct sync
python scripts/extract_playwright_kb.py  # Direct extraction
```

### Benchmarking
```bash
# Run baseline accuracy benchmark (Parser only)
python scripts/benchmark_pipeline.py

# Run full E2E execution benchmark (Parser + Playwright)
python scripts/benchmark_pipeline.py --full
```

## Component Structure

```
backend/
├── main.py                  # FastAPI entry point
├── config.py                # Pydantic settings (loads .env)
├── config/
│   ├── products.yaml        # Multi-product registry (FEAT-115/TASK-124) — single source of truth
│   └── product_registry.py  # ProductRegistry loader, ProductContext, ProductPublic (FEAT-115)

- `playwright/fixtures/users/users.json` — user roster per product; `productUrl` field on cross-domain user entries drives storage state capture for both SSO and app domains
- `playwright/utils/generateStorageStates.mjs` — generates `playwright/storage/<TEST_ENV>/storageState_<username>.json`; for cross-domain products, navigates to `productUrl` after login to capture PHP/RC-domain cookies
├── api/
│   ├── routes.py            # REST + WebSocket endpoints
│   ├── schemas.py           # Pydantic request/response schemas
│   └── auth_middleware.py   # API key + JWT auth middleware (TASK-054)
├── auth/
│   └── sso.py               # vcAPI RS256 SSO token validation (FEAT-047/TASK-052)
├── engine/                  # LangGraph state machine (CORE)
│   ├── state_tracker.py     # Deterministic DOM state (overlays, views)
│   ├── state.py             # VQAState TypedDict
│   ├── graph.py             # StateGraph wiring
│   ├── graph_orchestrator.py # Multi-graph orchestration layer
│   ├── planner.py           # Multimodal see-think loop (uses tracker for grounding)
│   ├── executor.py          # Playwright action dispatcher (uses tracker for dismissal)
│   ├── playwright_executor.py # Static Playwright test runner (FEAT-051/TASK-059)
│   ├── evaluator.py         # Step validation + routing
│   ├── verifier.py          # Programmatic + LLM verification
│   ├── verifier_node.py     # LangGraph verifier node wrapper
│   ├── human_takeover.py    # HITL pause/resume
│   ├── ac_parser.py         # Jira AC → test plan (vision-enriched)
│   ├── ac_enricher.py       # FEAT-002: KB domain-context injection pre-BDD
│   ├── ac_quality_gate.py   # FEAT-001: Rule-based AC quality scorer (GOOD/FAIR/POOR)
│   ├── vision_analyzer.py   # FEAT-045: Claude Vision for Jira image attachments
│   ├── prompts.py           # LLM system prompts
│   ├── prompt_budget.py     # LLM prompt token budget trimmer (TASK-054)
│   ├── kb_client.py         # KB retrieval client abstraction (TASK-054)
│   ├── validators.py        # Input + action validation
│   ├── roles.py             # Role credentials + permissions
│   ├── reporter.py          # HTML report + S3 upload (COVERAGE_GAP-aware)
│   ├── exploration_runner.py # FEAT-040: Autonomous KB self-heal via exploration
│   ├── recovery_router.py   # FEAT-022: Failure-type-specific recovery routing
│   ├── failure_classifier.py # Failure type classification
│   ├── failure_analyzer.py  # Post-failure root-cause analysis
│   ├── rag_debugger.py      # RAG retrieval diagnostics
│   ├── rag_ingestion.py     # RAG knowledge ingestion pipeline
│   ├── replay_engine.py     # Step replay / re-execution
│   ├── scheduler.py         # Batch run scheduling
│   ├── supervisor.py        # Agent supervision layer
│   ├── step_classifier.py   # AC step type classification
│   ├── metrics.py           # Execution metrics collection
│   ├── webhooks.py          # Outbound webhook notifications
│   ├── autorecord.py        # FEAT-044: Automatic session recording
│   ├── debugger.py          # Interactive debug tooling
│   ├── auth_manager.py      # Authentication state management
│   ├── fixture_manager.py   # Test fixture lifecycle management
│   ├── recipe_runner.py     # Blueprint YAML execution engine
│   ├── preflight_check.py   # DR-007: Pre-flight session health check (URL, auth, role)
│   ├── cb_telemetry.py      # MVE-001: Circuit breaker JSONL telemetry emitter
│   └── web_surfer.py        # Navigation helper utilities
├── browser/                 # Playwright infrastructure
│   └── cv_resolver.py       # FEAT-037: CV fallback (Set-of-Marks)
├── kb/                      # Knowledge base loaders + TF-IDF RAG
├── storage/                 # S3 + run history + test suites
├── adapters/                # Pluggable test source adapters (Jira, GitHub, raw text)
├── jira/                    # Jira client (AC + attachment retrieval)
├── memory/                  # Long-term HITL memory
└── llm/provider.py          # LLM client factory

frontend/src/
├── App.tsx
├── router.tsx               # React Router config (FEAT-048/TASK-053)
├── AuthContext.tsx           # Auth context provider
├── auth/                    # Independent auth system (FEAT-048/TASK-053)
│   ├── AuthProvider.tsx     # JWT/RS256 session management + vcAPI SSO
│   ├── ProtectedRoute.tsx   # Auth guard HOC
│   ├── authService.ts       # Token refresh + decode logic
│   ├── authStorage.ts       # Secure localStorage token persistence
│   ├── authTypes.ts         # Auth type definitions
│   ├── realAuthApi.ts       # vcAPI auth endpoints client
│   └── useAuth.ts           # Auth hook
├── pages/
│   ├── HomePage.tsx         # Root redirect
│   ├── LoginPage.tsx        # Login form with SSO
│   ├── MfaPage.tsx          # MFA challenge page
│   └── ProtectedPage.tsx    # Auth-gated page wrapper
├── context/
│   └── ProductContext.tsx     # Active product provider + useProductContext hook (FEAT-115/TASK-124)
├── components/
│   ├── Dashboard.tsx          # Main app shell
│   ├── ProductSelector.tsx    # Product context anchor in header (FEAT-115/TASK-124)
│   ├── SelectView.tsx         # SELECT mode: ticket + role + environment config
│   ├── ExecutionPanel.tsx     # Run config + control panel
│   ├── ExecutionLog.tsx       # Real-time step log viewer
│   ├── LiveBrowser.tsx        # noVNC iframe (interactive mode)
│   ├── TakeoverPanel.tsx      # HITL takeover controls
│   ├── CopilotSidebar.tsx     # AC step tracker + HITL copilot panel
│   ├── TriagePanel.tsx        # Failure analysis + guidance input
│   ├── ReportsHistory.tsx     # Recent runs list
│   ├── ReportsArchive.tsx     # Full archived reports browser
│   ├── AnalyticsDashboard.tsx # Metrics + trend visualization
│   ├── PlaywrightLibrary.tsx  # Static Playwright test browser UI (FEAT-051/TASK-059)
│   ├── ThinkingCard.tsx       # Agent reasoning display card
│   └── CredentialPrompt.tsx   # Role credential input UI
├── hooks/                   # useExecution, useWebSocket
└── types/index.ts

knowledge/
├── selector_registry.json   # 150+ Playwright selectors
├── human_guidance.md        # HITL-captured hints (RAG source)
├── vSuite-actions.md        # Workflow patterns (RAG source)
└── blueprints/              # YAML interaction templates

playwright/                  # Static Playwright test registry (FEAT-051)
├── playwright_index.json    # Canonical index: maps test files → IDs, descriptions, jira_keys (TASK-124/Phase5)
└── tests/
    ├── vpromedia/           # vProMedia product tests (26 .spec.ts files, TASK-124/Phase5)
    ├── vtrade/              # vTrade product stub (empty, .gitkeep)
    ├── vep/                 # vEP product stub (empty, .gitkeep)
    ├── vppo/                # vPPO product stub (empty, .gitkeep)
    ├── vpromotions/         # vPromo product stub (empty, .gitkeep)
    └── psn/                 # PSN product stub (empty, .gitkeep)
```

## Environment Configuration

**Config module layout**: New Pydantic settings fields are added to `backend/config/__init__.py` (the active `Settings` class). `backend/config.py` at the repo root is a legacy stub — do not add new fields there. Both files exist; only the package-level `__init__.py` is loaded at runtime.

Copy `.env.example` → `.env`. Key variables:

| Variable | Purpose |
|---|---|
| `JIRA_BASE_URL` | Jira instance URL |
| `JIRA_EMAIL` | Jira auth email |
| `JIRA_API_TOKEN` | Jira API token |
| `AWS_REGION` | AWS region (Bedrock + S3) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS credentials |
| `BEDROCK_ROLES_KB_ID` | Bedrock KB ID for role permissions |
| `S3_BUCKET` | S3 bucket for artifacts |
| `VSUITE_BASE_URL` | Target app URL to test |
| `ENABLE_SESSION_NAVIGATION_CONTEXT` | Inject URL, heading, and history into prompt |
| `ROLE_EMAIL_AE`, `ROLE_EMAIL_PRODUCER`, etc. | Per-role credentials |
| `API_KEY` | vQA API key for `X-API-Key` header |
| `SHARED_TEST_PASSWORD` | Shared password for non-admin test users (storage state generation) |
| `ADMIN_TEST_PASSWORD` | Admin test account password |

## Testing

- **Framework**: pytest
- **Test location**: `tests/` (separate from source); frontend tests under `frontend/src/components/__tests__/`
- **Current coverage**: `test_kb_matcher.py`, `test_suites.py`, `tests/backend/test_playwright_scoping.py` (TASK-124/Phase5)
- **Run**: `pytest tests/ -v`

### Cross-Domain Product Auth

Some products (vPPO, vPromotions) run on a separate domain from the Angular SSO gateway. The framework handles this transparently via:

- `playwright_base_url` in `products.yaml` — URL tests navigate to after login
- `productUrl` in `users.json` — drives `generateStorageStates.mjs` to capture cross-domain cookies
- `VPPO_BASE_URL` exported from `playwright/utils/setup.ts` — tests import this constant instead of `page.goto('/')`
- URL-based auth detection in `loginHelper.mjs` — replaces Angular CSS selector checks

See `memory-bank/systemPatterns.md` → *Cross-Domain Product Auth Pattern* for full details.

<!-- AUTO-MANAGED: c4-references-start -->
## C4 References

<!--
  This section is auto-managed by /vc-c4. Run /vc-c4 to refresh.
  Do not hand-edit between the AUTO-MANAGED markers — edits are overwritten.
-->

For runtime architecture, deployment topology, and tech-stack mapping per container, see:

- **Container index** (one-line-per-container): [memory-bank/c4/c4-container.md](./c4/c4-container.md)
- **System-wide container diagram + cross-container matrix**: [memory-bank/c4/c4-container-relationships.md](./c4/c4-container-relationships.md)
- **Per-container detail docs** (always-on, one per container): [memory-bank/c4/containers/](./c4/containers/)
- **API specifications referenced from**: container detail docs (do not duplicate schemas inline; see canonical schema paths)

This file (`techContext.md`) remains the canonical source for:

- Component Structure (file paths, languages, test directories)
- Development Commands (lint, type, build, test)
- Tech versions (runtimes, frameworks, libraries)

The Container-level C4 doc summarizes deployment topology and references this file for tech versions — it does not duplicate them.

**Last refreshed**: 2026-05-27
**Plugin version**: gemini-cli-4-6

<!-- AUTO-MANAGED: c4-references-end -->
