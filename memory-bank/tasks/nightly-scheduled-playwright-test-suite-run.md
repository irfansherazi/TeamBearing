---
slug: nightly-scheduled-playwright-test-suite-run
feature: nightly-scheduled-playwright-test-suite-run
status: COMPLETE
---

# nightly-scheduled-playwright-test-suite-run: Nightly Scheduled Playwright Test Suite Run

**Complexity**: Level 2
**Status**: COMPLETE
**Roadmap**: nightly-scheduled-playwright-test-suite-run
**Branch**: feature/nightly-scheduled-playwright-test-suite-run
**Worktree**: N/A (primary checkout)
**Reflection**: memory-bank/reflection/nightly-scheduled-playwright-test-suite-run-reflection.md
**Archived**: memory-bank/archive/nightly-scheduled-playwright-test-suite-run-archive.md
**Completed**: 2026-08-11

## Task Description

Wire the existing headless suite runner into a nightly automated schedule so a two-test regression subset runs unattended every night and posts pass/fail results to Slack. Every underlying piece already ships and runs 24/7 — only the schedule + notification path are missing.

**Architecture (resolved during planning):**

- **Trigger**: AWS EventBridge Scheduler rule (rate-per-day cron) → API destination → `POST /api/playwright/nightly` on the running vQA Fargate service. No GitHub Actions runner, no Lambda, no new compute — the schedule fires directly into the endpoint that already runs 24/7.
- **New endpoint** `POST /api/playwright/nightly` handles the full flow internally: fires the group-run, polls to terminal, formats and posts the Slack message. Encapsulates all the nightly-specific logic behind one HTTP surface so the schedule config stays a single line.
- **Test subset (pinned)**: `qa-170-search.test` + `qa-172-production.test`, both 1-step, aligned with the `DemoProdDirector` (ProdDirector role).
- **Environment**: `env: "test"` → `two-test.vcreative.net` (per `backend/config/products.yaml`).
- **Slack**: incoming webhook, URL stored at SSM `/vQA/slack/nightly_webhook_url`, loaded at settings init via the existing `backend/secrets.py` pattern. **Compact Block Kit payload**: one line per test with ✅/❌ + duration + name; separate from the existing verbose per-run Slack format in `webhooks.py`.

**What already exists (not in scope to rebuild):**

- `POST /api/playwright/run-group` — runs a caller-specified test subset async, returns `suite_run_id` (`backend/api/playwright_routes.py:1579`). This is the correct endpoint; the "run-suite" name in the original ask was stale.
- `GET /api/playwright/run-all/{suite_run_id}/report` — poll for terminal status + per-test results incl. `duration_ms`.
- `backend/engine/webhooks.py` — Slack Block Kit builder pattern; we add a separate compact builder rather than overloading the existing one.
- `backend/secrets.py` — `_get_ssm_client()` + `get_parameter` pattern for `/vQA/*` secrets.
- Fargate deployment (`deploy.sh`) — ECS cluster `vqa-cluster`, service `vqa-backend`, log group `/ecs/vqa-backend`; container reachable at the vQA public URL.

**Out of scope:**

- Results routing beyond Slack (Jira comments, dashboards, per-team routing)
- Historical result storage / trend visualization
- Alerting escalation (paging, retries)
- Expanding beyond the two-test subset (a follow-up can broaden coverage once the schedule is proven stable)
- Adding Terraform / CDK — this project bootstraps infra via bash + AWS CLI (`deploy.sh`); the EventBridge rule follows the same pattern

## Specification

**Feature Type**: NFR/Infrastructure
*Note: this is a scheduled automation feature — an EventBridge cron trigger + one new backend endpoint + Slack notification with no end-user UI.*
**Primary Persona**: Platform Admin / vProMedia Engineering — maintains vQA itself; is the first person who needs to know a nightly regression broke.
**Creative Exploration Needed**: No — all three open decisions were resolved in the planning conversation: (1) Trigger = EventBridge Scheduler → API destination → Fargate endpoint; (2) Subset = `qa-170-search.test` + `qa-172-production.test`; (3) Slack = incoming webhook stored at SSM `/vQA/slack/nightly_webhook_url`.

### Verification Method

- **Test method**: After deploy, monitor the configured Slack channel for 24 hours; expect exactly one Slack post at the configured UTC time (±5 min). To smoke-test without waiting, invoke `POST /api/playwright/run-group` manually with the two chosen test IDs, then trigger the Slack notification step in isolation to confirm the message shape.
- **Success metrics**: (a) Slack post lands within 5 minutes of the configured fire time; (b) green run post contains "✅ Nightly suite — 2/2 passed"; (c) red run post contains "❌ Nightly suite — 1/2 passed" or "0/2 passed" with the failing test ID(s); (d) `GET /api/playwright/run-all/{suite_run_id}/report` returns `outcome: "PASS"` or `outcome: "FAIL"` for each run; (e) three consecutive days of scheduled invocations visible in cron logs / GitHub Actions history
- **Observable at**: Slack channel `#vqa-nightly` (to be created or confirmed during build); GitHub Actions run history (if GH Actions cron) or EventBridge invocation history in CloudWatch under `/ecs/vqa-backend` log group (if EventBridge + Fargate)
- **Verification frequency**: daily (nightly cron); confirmed stable after 3 consecutive green or mixed-signal days

### Acceptance Criteria

#### AC-VERIFY-1: Scheduled trigger fires at the configured UTC time on three consecutive days
**Priority**: MUST
**Given** the cron resource is deployed (GitHub Actions `schedule:` event, or EventBridge Scheduler rule targeting the vQA Fargate endpoint)
**When** a reviewer checks the cron execution log or GitHub Actions run history after three calendar days
**Then** three successful invocations appear, each within ±5 minutes of the configured fire time; no invocations are missing or duplicated

#### AC-VERIFY-2: Green run produces the compact Slack message shape
**Priority**: MUST
**Given** both test IDs in the two-test subset pass
**When** the nightly endpoint completes its poll loop and the Slack notification step runs
**Then** the Slack channel receives exactly one Block Kit message per run containing: (a) a green header emoji (`✅`), (b) the text "Nightly suite — 2/2 passed", (c) exactly one line per test in the format `✅ qa-170-search.test — 12.4s`, `✅ qa-172-production.test — 18.7s`, and (d) a clickable "View Report" button linking to the vQA run report path for `suite_run_id`. Compact — no cost, no role, no AC counts (those belong to the existing ticket-run payload, not this one)

#### AC-VERIFY-3: Red run produces the compact Slack message shape with failing test names
**Priority**: MUST
**Given** one or both test IDs in the two-test subset fail
**When** the nightly endpoint completes its poll loop and the Slack notification step runs
**Then** the Slack channel receives exactly one Block Kit message containing: (a) a red header emoji (`❌`), (b) the text "Nightly suite — 1/2 passed" or "Nightly suite — 0/2 passed", (c) one line per test with the correct emoji + duration + name (failing tests use `❌`, passing use `✅`, e.g. `❌ qa-170-search.test — 12.4s`), (d) the `error_snippet` (truncated to 200 chars) inline under each failing test, and (e) a "View Report" button. Same compact layout as green — the only visual difference is the emojis and count

#### AC-VERIFY-4: Cron resource is defined in a committed, idempotent AWS CLI bootstrap script — not manually created
**Priority**: MUST
**Given** the nightly schedule is operational
**When** a reviewer inspects the repository
**Then** the EventBridge Scheduler rule is declared in `scripts/setup-nightly-eventbridge.sh` (idempotent — safe to re-run; matches the `deploy.sh` bash + AWS-CLI convention already in the repo); the schedule does NOT exist solely as a manually created AWS console resource

#### AC-VERIFY-5: Slack webhook URL is loaded from SSM at settings init, not hardcoded
**Priority**: MUST
**Given** the notification step runs
**When** a reviewer audits `backend/config/__init__.py`, `backend/api/playwright_routes.py`, and every committed script/YAML
**Then** the Slack destination URL is loaded from AWS SSM Parameter Store path `/vQA/slack/nightly_webhook_url` via the existing `backend/secrets.py` pattern (consistent with `/vQA/jira/*`, `/vQA/roles/*`); the literal `hooks.slack.com/services/...` URL does NOT appear in any committed file

#### AC-VERIFY-6: The two-test subset IDs, env, and user are pinned in `backend/config/__init__.py` — not selected at runtime
**Priority**: MUST
**Given** the nightly endpoint fires
**When** the internal group-run is dispatched
**Then** the values `test_ids=["qa-170-search.test", "qa-172-production.test"]`, `env="test"`, `user="DemoProdDirector"`, `browser="chromium"` come from `Settings` fields (`nightly_test_ids`, `nightly_env`, `nightly_user`, `nightly_browser`) with those exact defaults; the subset is deterministic across runs and overridable via env vars for smoke-testing without a code change

#### AC-ERROR-1: When the internal group-run dispatch fails or the poll loop detects a suite-level failure, the Slack message surfaces the error rather than silently succeeding
**Priority**: MUST
**Given** the nightly endpoint fires but the internal group-run raises (HTTP 429 "suite run already in progress", or the run's terminal `outcome` is `FAIL` with `fail_reason` set)
**When** the endpoint's background task catches the exception / detects the terminal-FAIL state
**Then** a Slack message is posted to the same channel indicating the run did not complete (e.g., `❌ Nightly suite — could not start: suite run already in progress` or `❌ Nightly suite — poll timeout after 30 min`); the endpoint does NOT exit silently with no Slack post

#### AC-ERROR-2: When the Slack webhook delivery itself fails, the failure is logged and visible in the cron job's output — not silently swallowed
**Priority**: SHOULD
**Given** the Slack webhook URL is misconfigured or Slack's API returns a non-2xx
**When** the notification step attempts delivery
**Then** the cron job log (GitHub Actions run log, or CloudWatch `/ecs/vqa-backend`) records the failure with the HTTP status returned by Slack; the overall cron job marks itself as failed so the next run's human reviewer sees a red invocation in the history

#### AC-ASYNC-1: The nightly endpoint polls the in-memory suite run store to terminal state before posting to Slack — it does not post immediately after starting the run
**Priority**: MUST
**Given** the internal group-run has been dispatched and a `suite_run_id` is known
**When** the endpoint's background task runs
**Then** it polls `playwright_suite_run_store.get_run(suite_run_id)` in-process (no HTTP round-trip needed — same process) until `status ∈ {"completed", "failed"}`, with a max poll duration of 30 minutes and a poll interval of 5 seconds; it posts the Slack message only after receiving a terminal status; if the poll times out, it posts an error message per AC-ERROR-1 and marks the run FAIL via the existing `stop_suite_run` code path

### Scope Boundaries

- **In scope**: nightly cron trigger (GitHub Actions schedule or EventBridge Scheduler); HTTP call to `POST /api/playwright/run-group` with a pinned two-test subset; poll loop against `GET /api/playwright/run-all/{suite_run_id}/report`; Slack notification using the existing `backend/engine/webhooks.py` Slack Block Kit format (or a simple `requests.post` to a webhook URL — implementation choice during build); secret for Slack destination stored in GitHub Actions secrets or AWS SSM `/vQA/slack/webhook_url`
- **Out of scope**: adding a new `/playwright/run-suite` endpoint (the correct existing endpoint is `/api/playwright/run-group`); Jira comment routing; dashboard updates; historical result storage; alerting escalation or retry logic; expanding beyond the two-test subset; any UI changes to the React frontend
- **Dependencies**: the running vQA Fargate service (ECS cluster `vqa-cluster`, service `vqa-backend`) must be reachable from the trigger; `POST /api/playwright/run-group` requires the `X-VQA-API-Key` header; the two chosen test IDs must exist in `playwright/playwright_index.json`; a Slack workspace and channel (`#vqa-nightly` or equivalent) must exist
- **NFR implications**: no new AWS compute is required if GitHub Actions cron is chosen (zero incremental cost); if EventBridge + Fargate run-task is chosen, each invocation spins a short-lived Fargate task with its own cost; the existing `/ecs/vqa-backend` CloudWatch log group already captures the running container's logs — the schedule trigger's own invocation log is separate

### Design decisions (resolved during planning)

1. **Trigger vendor** → **EventBridge Scheduler → API destination → Fargate endpoint**. Chosen over GitHub Actions cron because it hits the existing 24/7 Fargate service directly (no runner spin-up, no cold path) and avoids adding a Lambda hop. The `deploy.sh` bash + AWS-CLI convention is reused for provisioning.
2. **Two-test subset** → `qa-170-search.test`, `qa-172-production.test`. Both 1-step, `DemoProdDirector` (ProdDirector role), env `test` (→ `two-test.vcreative.net`).
3. **Slack credential** → incoming webhook URL stored at SSM `/vQA/slack/nightly_webhook_url`, loaded via the existing `backend/secrets.py` pattern. Not stored in `.env`, not committed to the repo, not in a GH Actions secret.
4. **Schedule fire time** → `cron(0 6 * * ? *)` UTC (06:00 UTC daily = 02:00 EDT / 01:00 EST). Deferred: exact minute avoiding any future scheduled jobs; today there are no other scheduled Fargate jobs in the repo, so 06:00 is safe.

## User Journey Definition

**Feature Type**: NFR/Infrastructure — no end-user surface. The "journey" is:

```
EventBridge Scheduler rule
  → HTTPS POST to https://<vqa-fargate-public-url>/api/playwright/nightly
    (Authorization: X-VQA-API-Key header sourced from EventBridge Scheduler connection)
  → Backend handler validates auth, dispatches internal group-run against the pinned subset,
    returns 202 Accepted with {suite_run_id, status: "started"} immediately.
  → Background asyncio task polls playwright_suite_run_store in-process every 5s
    (max 30 min).
  → On terminal status: build compact Slack Block Kit payload, POST to Slack webhook URL
    loaded from SSM /vQA/slack/nightly_webhook_url.
  → On poll timeout or dispatch failure: post an error-shaped Slack message per AC-ERROR-1.

Observable to a human at: the configured Slack channel + CloudWatch log group /ecs/vqa-backend.
```

The "Primary Persona" — Platform Admin / vProMedia Engineering — sees a Slack message once per day and only cares when it's red.

## Test Strategy

### Approach

- **Emphasis**: **unit + integration** heavy. E2E is out of scope for this task's own tests (the underlying Playwright suite IS the E2E test — this task just automates its schedule). No new browser tests.
- **Target test count**: **10 total** across all phases (1 payload-builder × 3 shapes; 1 endpoint × 3 auth/state permutations; 1 poll loop × 2 outcomes; 1 SSM loader × 1 case; 1 config default × 1 case).

### File Organization

- **New test files**:
  - `backend/tests/api/test_playwright_nightly.py` — endpoint + poll-loop + config-default tests (7 tests)
  - `backend/tests/engine/test_webhooks_nightly.py` — compact-Slack-payload builder tests (3 tests)

- **Extend existing**:
  - `backend/tests/config/test_settings.py` — add 1 test verifying `nightly_slack_webhook_url` loads from SSM (mocked via the existing pattern) — only if a config-settings test file already exists; otherwise fold that assertion into `test_playwright_nightly.py`

### What NOT to Test

- The internal group-run orchestration (`_run_group_orchestrator`) — covered by existing tests for `POST /run-group`; the nightly endpoint reuses it, no need to re-test the mechanics
- EventBridge Scheduler rule creation in AWS — infra, verified out-of-band (`aws scheduler get-schedule` after running the bootstrap script)
- Live Slack delivery — asserted only via `httpx_mock` recording the POST and its body; no live Slack call in tests
- The actual `qa-170-search.test` / `qa-172-production.test` runs — those are tests OF vQA-under-test, not tests OF this feature

### Per-Phase Test Guidance

- **Phase 1 (backend endpoint + Slack payload)**: 10 tests
  - `test_webhooks_nightly.py::test_compact_slack_payload_all_pass` — 2/2 green shape
  - `test_webhooks_nightly.py::test_compact_slack_payload_all_fail` — 0/2 red shape with error_snippets
  - `test_webhooks_nightly.py::test_compact_slack_payload_mixed` — 1/2 mixed shape
  - `test_playwright_nightly.py::test_nightly_endpoint_rejects_missing_api_key` — 401/403 with no run started
  - `test_playwright_nightly.py::test_nightly_endpoint_returns_202_and_dispatches_group_run` — happy path, mocked `_run_group_orchestrator`
  - `test_playwright_nightly.py::test_nightly_endpoint_returns_429_when_run_active` — reuses existing suite-run store's active-run guard
  - `test_playwright_nightly.py::test_poll_loop_posts_slack_on_completed` — mocked store returns `completed` after 3 polls, verify Slack POST body
  - `test_playwright_nightly.py::test_poll_loop_posts_error_slack_on_timeout` — store never terminates, verify AC-ERROR-1 shape and store marked FAIL
  - `test_playwright_nightly.py::test_poll_loop_posts_error_slack_on_dispatch_exception` — orchestrator raises, verify AC-ERROR-1 shape
  - `test_playwright_nightly.py::test_settings_defaults_pin_subset` — assert `settings.nightly_test_ids == ["qa-170-search.test", "qa-172-production.test"]`, `env == "test"`, `user == "DemoProdDirector"`

- **Phase 2 (EventBridge Scheduler + SSM bootstrap)**: 0 automated tests
  - Verified manually: run `scripts/setup-nightly-eventbridge.sh` in the vQA AWS account, assert `aws scheduler get-schedule --name vqa-nightly` returns the expected cron + target; wait for first fire, expect Slack post
  - Documentation is a required deliverable (`docs/nightly-schedule.md` or a README section explaining bootstrap + rollback)

## Implementation Roadmap

### New Source Files (pin path + extension)

- [ ] `backend/tests/api/test_playwright_nightly.py` — endpoint + poll-loop + config-defaults tests
- [ ] `backend/tests/engine/test_webhooks_nightly.py` — compact Slack payload builder tests
- [ ] `scripts/setup-nightly-eventbridge.sh` — idempotent AWS-CLI bootstrap for the EventBridge Scheduler rule, IAM role, API destination, connection, SSM parameter placeholder
- [ ] `docs/nightly-schedule.md` — operator doc: what it is, how to bootstrap, how to change the schedule, how to disable, how to rotate the Slack URL
- [ ] `backend/api/playwright_routes.py` — **extend** (new `POST /nightly` handler + poll loop helper)
- [ ] `backend/engine/webhooks.py` — **extend** (new `_build_nightly_slack_payload()` + `post_nightly_slack()` helper reusing the existing httpx pattern)
- [ ] `backend/config/__init__.py` — **extend** (new `nightly_*` Settings fields + SSM load block for `/vQA/slack/nightly_webhook_url`)

### Phases

- [x] Phase 1: Backend endpoint + compact Slack payload (files 5–7 above + tests 1–2). Delivers a POST-able endpoint that runs the full flow when hit manually via `curl`. Manually testable end-to-end against dev Slack channel before Phase 2 lands.
- [x] Phase 2: EventBridge Scheduler + SSM bootstrap + operator doc (files 3–4 above). Delivers the actual nightly cadence. Manually verified against AWS + Slack after deploy.

### Files to Modify (Level 2 template)

- `backend/api/playwright_routes.py` — add `POST /nightly` endpoint (~60 lines) + `_nightly_poll_and_notify` background task helper (~40 lines)
- `backend/engine/webhooks.py` — add `_build_nightly_slack_payload(suite_run_id: str, run_data: dict, report_url: str) -> dict` + `async def post_nightly_slack(webhook_url: str, payload: dict) -> None` (~60 lines total)
- `backend/config/__init__.py` — add fields (`nightly_test_ids`, `nightly_env`, `nightly_user`, `nightly_browser`, `nightly_slack_webhook_url`, `nightly_poll_interval_seconds=5`, `nightly_poll_timeout_seconds=1800`) + SSM load block in the existing `load_secrets_from_ssm()` (~20 lines)

### Dependencies

- Phase 2 depends on Phase 1 (the endpoint must exist and be deployed before EventBridge can fire it)
- Phase 1 depends on: no external unknowns — all pieces (run-group, webhooks pattern, SSM pattern) already exist

### Observability Requirements

- **Applies**: Yes — `POST /api/playwright/nightly` is a new HTTP endpoint; the background poll-and-notify task runs inside the same process
- **Logging**: every nightly invocation logs `[nightly] started suite_run_id=<id>`, `[nightly] terminal status=<status> passed=<n> failed=<n>`, `[nightly] slack post status=<http_status>`. Errors log the exception with stack trace. All log lines flow through the existing `/ecs/vqa-backend` CloudWatch log group.
- **Tracing**: use existing FastAPI middleware; no distributed spans needed (single-process flow, no downstream HTTP except Slack)
- **Metrics**: none needed for MVP — the Slack channel is the metric

### API Requirements

- **REST API**: Yes — one new endpoint `POST /api/playwright/nightly`. No request body (or empty body accepted). Response: `202 Accepted` with `{suite_run_id, status: "started"}`. Auth: `X-VQA-API-Key` (existing middleware).
- **OpenAPI Spec**: auto-generated by FastAPI; no manual OpenAPI file to update.

## Creative Phases

- [ ] None — all three LOW-confidence design questions were resolved during the planning conversation. No `/bmb:creative` phase needed.

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Phase Number**: 2 of 2
**Is Multi-Phase**: YES
**Build Started**: 2026-08-11T14:00:00Z
**Can Resume**: NO

### Current Build Step
**Step**: /bmb:archive
**Status**: COMPLETE
**Completed**: 2026-08-11

### Completed Steps (Phase 1 — archived)
- PLAN: 2026-08-11 (Spec Writer + human review + design decisions locked)
- Phase 1 Step 0.5 Git Setup: COMPLETE — primary checkout confirmed
- Phase 1 Step 3 TDD Agent: COMPLETE — 10 tests in 2 files; 5 production files extended
- Phase 1 Step 6 Test Execution: COMPLETE — 10/10 PASS
- Phase 1 Step 7 Integration Verification: COMPLETE — 2023 passed, 0 new failures
- Phase 1 Step 8 Code Review: COMPLETE — Approved
- Phase 1 Step 11 Git Completion: COMPLETE — commit 81cb5bf

### Completed Steps (Phase 2)
- Step 0.5 Git Setup: COMPLETE — primary checkout on feature/nightly-scheduled-playwright-test-suite-run
- Step 0.6 Phase Gate: COMPLETE — Phase 2 unchecked, Phase 1 confirmed complete
- Step 1 Read Task Context: COMPLETE — Phase 2 identified (infra/docs only)
- Step 2 Load Context: COMPLETE — Level 2 rules loaded
- Step 3 Implementation: COMPLETE — scripts/setup-nightly-eventbridge.sh (idempotent AWS CLI bootstrap) + docs/nightly-schedule.md (operator doc)
- Step 7 Integration Verification: COMPLETE — 10/10 nightly tests still passing; no regressions (docs-only phase)
- Step 8 Code Review: COMPLETE — Approved; no hardcoded secrets; SSM placeholder + warning; AC-VERIFY-4/5 satisfied
- Step 10 Memory Bank: COMPLETE — Phase 2 [x] marked; Execution State updated
- Step 11 Git Completion: COMPLETE — Phase 2 committed to feature branch (06e41aa)

### Completed Steps (Reflect)
- Reflection Agent: COMPLETE (2026-08-11T15:35:23Z) — Output: memory-bank/reflection/nightly-scheduled-playwright-test-suite-run-reflection.md
- Git Commit: COMPLETE — commit 559d986 (reflection doc)

### Completed Steps (Archive)
- Archive Doc: COMPLETE — Output: memory-bank/archive/nightly-scheduled-playwright-test-suite-run-archive.md
- Learning Consolidation: COMPLETE — backend-api-patterns.md (scheduled-trigger-endpoint-pattern), workflow-compliance.md (infra-phase-test-free-declaration)
- Live Smoke Test: COMPLETE (2026-08-11) — POST /api/playwright/nightly returned 202; 2/2 tests passed; Slack POST returned 200
- Roadmap Feature: status → completed
- Task Status: COMPLETE

### Guard & Recovery Log
- Phase 1: guard C1 WARNING (pre-existing unrelated dirty files); C2 PASS prod=5 test=2; C3 PASS all 7 expected files in commit 81cb5bf
- Phase 2: test-free declared (pure infra/docs per task spec "0 automated tests"); prod=0 → C2 inapplicable; C3 PASS (scripts/setup-nightly-eventbridge.sh + docs/nightly-schedule.md in commit)

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A — reflection complete
**Notes**: Both phases + reflection complete. Next: /bmb:archive nightly-scheduled-playwright-test-suite-run
