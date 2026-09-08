# Product Brief

> This document captures the business and product context for development teams.
> It ensures all agents understand the product's purpose, users, and constraints.

## Product Overview

- **Name**: vQA
- **Value Proposition**: Autonomous AI-driven web QA agent that eliminates test maintenance by visually reasoning about the live browser — tests vSuite from Jira AC to HTML audit report with zero manual selector upkeep. When the vSuite UI changes across sprints, vQA adapts because it reasons from live screenshots and accessibility trees rather than hardcoded CSS selectors.
- **Product Type**: Internal Platform / Autonomous Agent
- **Stage**: Beta (actively developed)

## Key Functionality

- Fetch Acceptance Criteria directly from Jira tickets via `customfield_10031` — no test script authoring required
- Parse AC into a structured test plan via a two-stage LLM pipeline (BDD normalization → JSON)
- **Vision-Assisted AC Enrichment**: Automatically fetches Jira image attachments (wireframes, screenshots), analyzes them with Claude Vision, and injects visual grounding context into the BDD normalization prompt for higher-accuracy test plans
- **AC Quality Gate**: Zero-LLM rule-based scorer that grades raw AC text as GOOD/FAIR/POOR before parsing, surfacing vague or incomplete ACs to the report
- Execute tests through a multimodal **See-Think-Act** loop: screenshot + ARIA tree → Claude 3.5 Sonnet → Playwright action
- Test from 8 distinct vSuite user roles with automatic RBAC violation detection
- Produce self-contained HTML audit reports with embedded session video, screenshot gallery, and per-action reasoning
- **COVERAGE_GAP-Aware Reporting**: Report header and AC table correctly classify uncovered steps as FAILED rather than passing
- Human-in-the-Loop (HITL) takeover: pause the agent, accept manual input, learn the action for future runs
- **Interactive Remote Browser Takeover**: Directly control the remote browser via an integrated VNC stream during HITL events, replacing static coordinate injection with full visual and keyboard/mouse interaction.
- **CopilotSidebar**: Real-time AC step tracker panel showing pass/fail status for each step during execution, and HITL copilot controls
- **Triage Panel**: After a failed run, displays an AI-generated failure analysis (Product Bug / Jira Unclear / Mixed), executive summary, per-step reasoning, and a guidance input field for PM/QA self-service triage
- **E2E Benchmarking**: Quantitative accuracy baseline tracking via a “Golden 10” dataset, measuring both AC parsing coverage and browser execution success rates.
- **Static Playwright Test Library** (FEAT-051): Browse, run, and stream output from pre-authored Playwright `.spec.ts` files directly from the dashboard — enables deterministic regression testing alongside AI exploration
- **Independent React Auth System** (FEAT-048): JWT/RS256 session management with MFA support, vcAPI SSO integration, and protected routing — all handled client-side without backend session coupling
- **vcAPI RS256 SSO Migration** (FEAT-047): Backend validates vcAPI-issued RS256 JWTs via `backend/auth/sso.py`, eliminating shared-secret auth for production deployments
- **Prompt Budget Trimmer** (TASK-054): Prevents Bedrock context-overflow by progressively trimming low-priority context sections while preserving the AC step and screenshot
- **Interactive mode**: live per-user browser streaming via session-scoped noVNC paths (`/vnc/<session_id>/vnc.html`) embedded in React dashboard — each authenticated user sees only their own browser session
- **Headless batch mode**: CI/CD deployment gating via `/execute-batch`

## Markets Serviced

- **Primary Market**: Internal — vProMedia engineering and operations teams
- **Secondary Markets**: N/A (internal tool, not sold externally)
- **Geographic Focus**: US-based vProMedia operations
- **Market Size**: Internal tool — team of ~10–50 users

## Competitive Landscape

- **Direct Competitors**: Playwright codegen (brittle selector-based), Cypress, TestRail + manual QA
- **Indirect Competitors**: Meticulous, Reflect.run, Autify, testRigor (commercial AI test tools)
- **Key Differentiators**: Jira-native AC ingestion; HITL learning loop; role-based RBAC testing; deep vSuite-specific KB with 150+ pre-mapped selectors and blueprint YAMLs
- **Competitive Advantages**: Institutional domain knowledge baked into the KB; grows smarter with every HITL session; purpose-fit for Angular/PrimeNG stack

## Key Personas

### Primary Users

| Persona | Role | Goals | Pain Points | Success Metrics |
|---------|------|-------|-------------|-----------------|
| QA Lead / Automation Engineer | Senior QA, owns regression suite | Eliminate maintenance burden of hand-written test scripts across rapid UI sprints; get auditable regression reports each sprint | Spends 30–40% of sprint time updating broken selectors after UI changes; needs audit trails credible enough to share with engineering | Regression suite runs fully autonomous; HITL escalation rate < 20%; audit reports accepted by engineering as evidence |
| Product Manager | PM owning vSuite tickets | Verify AC is satisfied before marking a ticket "Done" — without waiting for a QA cycle | No way to self-verify a ticket except manual smoke testing; wants visual confirmation, not just a green checkmark | Can run a ticket, watch it pass live on the dashboard, and close it with confidence |
| Release Engineer / DevOps | CI/CD pipeline owner | Gate staging deployments on test pass/fail via automated pipeline integration | Ships blind or blocks on slow manual QA cycle; no automated regression gate exists today | Every staging deploy automatically gated; failed runs block merge |

### Secondary Users

| Persona | Role | Goals |
|---------|------|-------|
| Human-in-the-Loop Operator (QA Analyst) | QA analyst on-call during stuck runs | Unblock stuck agent; teach new interaction patterns via dashboard; knows their actions are being learned and captured permanently |

### Administrators/Operators

| Persona | Role | Responsibilities |
|---------|------|------------------|
| Platform Admin / vProMedia Engineering | Maintains vQA itself | Update `selector_registry.json`; write blueprint YAMLs; sync `human_guidance.md` to Bedrock KB; manage role credentials in `.env`; diagnose and patch agent blind spots when new PrimeNG components are introduced |

## User Flows

- **Primary Flow**: PM or QA engineer enters Jira ticket ID + selects role → vQA fetches AC, parses test plan, logs in, executes each step via See-Think-Act loop, produces HTML audit report → reviewer confirms result, closes ticket
- **Onboarding**: Clone repo → copy `.env.example` → `.env`, fill credentials → `./start.sh`
- **Key Workflows**:
  - Single-ticket interactive run via React dashboard (PM self-verification)
  - Batch regression run via `POST /execute-batch` (CI/CD, GitHub Actions)
  - HITL takeover: agent stuck → operator clicks in live noVNC browser → agent learns → resumes
  - KB expansion: platform admin adds entries to `human_guidance.md` → `make kb-human-sync` → Bedrock KB updated

## Success Metrics & KPIs

### Efficiency
- **Test maintenance time reduction**: % decrease in engineer hours spent updating selectors or test scripts per sprint. Target: **80% reduction from baseline**
- **Time-to-test**: Minutes from ticket AC merge to first completed automated test run. Target: **under 5 minutes** for a single-ticket run

### Quality
- **AC coverage rate**: % of Jira AC steps that reach a verified outcome (pass or fail) without HITL intervention per run. Target: **≥ 85% autonomous completion rate**
- **False positive rate**: % of runs that report "pass" when the feature is actually broken. Target: **< 2%**
- **False negative rate**: % of runs that report "fail" on correctly-working features. Target: **< 5%**

### Reliability
- **HITL escalation rate**: % of AC steps requiring human takeover. Healthy: decreasing over time as KB grows. Alarm threshold: **> 20% consistently**
- **Run crash rate**: % of runs that terminate with an unhandled exception before producing a report. Target: **< 1%**
- **Retry resolution rate**: % of initially-failed AC steps that self-heal on retry without HITL. Target: **≥ 70% of retried steps**

### Adoption
- **Tickets tested per sprint**: Count of Jira tickets run through vQA per two-week sprint. Directional signal of PM/QA adoption
- **Roles tested per ticket**: Average number of role executions per ticket. Target: **≥ 2** (single-role runs leave RBAC gaps)
- **HITL knowledge accumulation rate**: Entries added to `human_guidance.md` per month — indicates the system is learning and growing institutional coverage

### Business
- **Regression detection in CI**: Count of deployments blocked by vQA catching a regression before it reached production. The **key ROI metric**
- **Time from AC to confidence**: End-to-end time from "ticket in Review" to "PM has visual confirmation the feature works." Baseline is current manual process

## Non-Functional Requirements

### Reliability

- The system must tolerate transient Playwright timeouts without aborting a run — up to **2 retries per AC step** before escalating to HITL
- AWS Bedrock and S3 calls must have timeout handling and exponential backoff; a single LLM timeout must not fail an entire run
- Batch runs must be isolated — one ticket failure must not block or corrupt other tickets in the same batch

### Performance

- **First browser action**: < 30 seconds from ticket submission (single-ticket interactive run)
- **Per-step see-think-act cycle**: < 15 seconds under normal load
- **Batch run throughput**: 10 tickets in < 30 minutes (headless, parallelized)
- **WebSocket log stream latency**: < 500ms end-to-end from action execution to dashboard display

### Observability

- Every action must produce a persisted audit artifact (screenshot URL, reasoning text, locator used, success/fail status) even on failure
- HTML audit reports must be **self-contained** and loadable from S3 without backend connectivity
- Run state must be queryable via `GET /status/{run_id}` at any point during or after execution

### Security

- Role credentials must **never appear** in logs, screenshots, or audit reports
- All API endpoints must require a valid API key (`X-API-Key` header)
- S3 artifacts must be in a **private bucket**; presigned URLs used for report delivery

### Maintainability

- Adding a new vSuite workflow requires only a new blueprint YAML + selector registry entries — **no code changes**
- Adding a new user role requires only `.env` credential entries + Bedrock KB update — **no code changes**
- HITL-learned actions must automatically propagate to future runs via the Bedrock KB sync pipeline

### Scalability

- Each run must get its own isolated Playwright browser context — concurrent batch runs must not conflict
- Docker deployment must support horizontal scaling — multiple container instances behind a load balancer

### Data & Privacy

- **Data Residency**: AWS (region configured via `AWS_REGION`)
- **Data Retention**: S3 artifacts retained indefinitely (no automated cleanup configured — open question)
- **PII Handling**: Role credentials in `.env` only; vSuite user data visible in screenshots/reports (internal use only)

### Availability & Reliability

- **Uptime Target**: Internal tool — best effort, no formal SLA
- **Run Isolation**: S3 artifacts persist independently of backend uptime
- **Failure Handling**: 2 retries → HITL escalation → fatal abort with partial report

## Integration Points

### External Systems

| System | Purpose | Protocol | Direction |
|--------|---------|----------|-----------|
| Jira REST API v3 | Fetch ticket summary + AC from `customfield_10031` | REST / Basic Auth | Outbound |
| AWS Bedrock (Claude 3.5 Sonnet) | Multimodal see-think-act planner | AWS SDK (ChatBedrockConverse) | Outbound |
| AWS Bedrock (Claude Haiku) | LLM fallback verifier (Tier 2) | AWS SDK | Outbound |
| AWS Bedrock Knowledge Base (`JXMMTMTI06`) | Role permissions matrix RAG retrieval | AWS SDK (RetrieveAndGenerate) | Outbound |
| AWS S3 | Store screenshots, videos (.webm), HTML audit reports | AWS SDK (boto3) | Outbound |
| Playwright / Chromium | Browser automation, video recording, screenshot capture | Local process | Internal |
| Xvfb / x11vnc / noVNC | Per-user virtual display + VNC → WebSocket streaming (interactive mode only). Phase 3+ (per-user-session-isolation): each session gets an isolated display (`:N`) and per-session noVNC URL (`/vnc/<session_id>/vnc.html?path=websockify/<session_id>`) routed by the in-container nginx sidecar. | Docker sidecar | Internal |

### APIs Consumed

| API | Provider | Purpose |
|-----|----------|---------|
| Jira REST v3 `/issue/{key}` | Atlassian | Fetch ticket ACs |
| Bedrock InvokeModel — Claude 3.5 Sonnet | AWS | Multimodal planning |
| Bedrock InvokeModel — Claude Haiku | AWS | Lightweight visual verification |
| Bedrock KnowledgeBase Retrieve | AWS | Role permissions lookup |
| S3 PutObject / GetObject | AWS | Artifact storage and retrieval |

### APIs Provided

| API | Purpose | Consumers |
|-----|---------|-----------|
| `POST /execute` | Start single test run | React dashboard, CI/CD |
| `POST /execute-batch` | Start batch test run | CI/CD (GitHub Actions) |
| `GET /status/{run_id}` | Poll run status + artifact URLs | Dashboard, CI/CD |
| `GET /batch-status/{batch_id}` | Poll batch status | CI/CD |
| `GET /health` | Liveness probe (Bedrock, S3, Jira) | Docker healthcheck, load balancer |
| `POST /runs/{run_id}/interact` | Inject mouse click during HITL | React dashboard |
| `POST /runs/{run_id}/human-takeover/done` | Signal HITL completion | React dashboard |
| `WS /ws/{run_id}` | Real-time execution log stream | React dashboard |

## Constraints & Assumptions

### Technical Constraints

- AWS Bedrock availability is required for all runs — no local LLM fallback
- S3 write access required for artifact persistence
- Jira credentials required for AC ingestion; all ACs expected in `customfield_10031`
- Interactive mode requires Docker with Xvfb (not supported on bare-metal macOS without virtual display)
- vSuite is Angular/PrimeNG — agent KB and blueprints are purpose-fit for this stack

### Business Constraints

- Internal tool — no external customers, no revenue constraint
- Knowledge base must be actively maintained as vSuite evolves — agent blind spots grow if KB lags UI changes

### Assumptions

- vSuite is always available at `VSUITE_BASE_URL` during test runs
- Jira tickets always carry AC in `customfield_10031`
- Role credentials in `.env` are kept current as vSuite users change
- The agent's architecture (LangGraph + multimodal planner + YAML blueprints) is generic enough to target any Angular/PrimeNG application with minimal reconfiguration

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| vSuite UI redesign outpaces selector KB | Medium | High | Semantic locators resist layout changes; `make kb-refresh` pipeline for KB updates |
| AWS Bedrock rate limits block batch runs | Low | High | Retry with exponential backoff; limit concurrent LLM calls per batch |
| HITL escalation rate stays high — agent doesn't learn fast enough | Medium | Medium | Proactive KB expansion; sync `human_guidance.md` after every sprint |
| False positives gate deployments incorrectly | Low | High | Dual-tier verifier (programmatic first, LLM fallback) enforces low FP rate |
| Role credential rotation breaks runs | Medium | Medium | Centralize credential management; alert on login failure in evaluator |
| Knowledge base drift — HITL learnings not reviewed before syncing | Low | Medium | Add curation step before `kb-human-sync` (open question) |

## Open Questions

- [ ] Should S3 artifacts have an automated retention/cleanup policy?
- [ ] Should HITL-learned actions be reviewed/curated before syncing to Bedrock KB?
- [ ] Should vQA formally support non-vSuite Angular/PrimeNG apps as a second product direction?
- [ ] Should there be alerting (Slack/email) when a batch run produces > N failures?

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-07 | vc-init agent + product debrief | Initial creation with full personas, NFRs, success metrics |

## Last Refreshed

2026-07-22

## Project Foundation (merged from projectbrief.md)

# Project Brief

## Project Overview

**vQA** is an autonomous web QA agent that tests vSuite — vProMedia's internal Angular/PrimeNG production media management platform. It replaces brittle, hand-written Playwright `.spec.ts` files with a multimodal AI agent that sees the live browser, reasons about it like a human tester, and executes tests through real browser automation with zero test maintenance.

## Goals

- Eliminate the maintenance burden of hardcoded CSS selectors in test scripts
- Gate CI/CD deployments on automated acceptance-criteria pass/fail
- Provide visual, auditable proof that Jira ACs are satisfied before tickets close
- Test all 8 vSuite user roles for RBAC compliance automatically
- Build an institutional knowledge base that grows with every HITL interaction

## Key Stakeholders

- **vProMedia Engineering** — Owns and deploys vQA
- **QA Leads / Automation Engineers** — Primary operators of batch test runs
- **Product Managers** — Use interactive mode to verify own tickets
- **Release Engineers / DevOps** — Integrate headless mode into CI/CD pipelines

## Repository Structure

- **Type**: Poly-repo (single multi-layered application, no mono-repo workspace tooling)
- **Workspace Tool**: None
- **Workspace Root**: N/A
- **Apps/Services**:
  - `backend/` — Python FastAPI + LangGraph agent engine
  - `frontend/` — React 19 + Vite dashboard SPA
- **Shared**: `knowledge/` — agent knowledge base (selectors, blueprints, guidance docs)

## Git Configuration

- **Repository**: Yes
- **Provider**: GitHub
- **CLI Available**: gh
- **Remote URL**: https://github.com/vcreativeinc/vQA.git
- **Default Branch**: main
- **Archive Strategy**: push-and-pr

## Working Directory Notes

As of 2026-05-27, the codebase is on `main` with all work through TASK-059 merged. A major frontend restructuring was introduced in TASK-053 (React Auth System + routing) and TASK-059 (Playwright Test Library). Key new directories: `frontend/src/auth/`, `frontend/src/pages/`, `playwright/`. TASK-052 (vcAPI RS256 SSO) implementation is complete but pending final verification/review. Start new feature branches from latest `main`.
