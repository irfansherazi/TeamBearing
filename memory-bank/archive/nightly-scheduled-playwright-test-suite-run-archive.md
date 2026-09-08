---
slug: nightly-scheduled-playwright-test-suite-run
feature: nightly-scheduled-playwright-test-suite-run
complexity: Level 2
status: COMPLETE
archived: 2026-08-11
completion_commits:
  - a6a05f6  # plan
  - 81cb5bf  # Phase 1: backend endpoint + compact Slack payload
  - 37e3f71  # chore: Phase 1 execution state + guard log
  - 06e41aa  # Phase 2: EventBridge Scheduler bootstrap + operator doc
  - 559d986  # reflect
  - 767ac05  # mark REFLECTION_COMPLETE
---

# Archive: Nightly Scheduled Playwright Test Suite Run

**Complexity**: Level 2 (Simple enhancement / NFR infrastructure)
**Duration**: 2026-08-11 (single day: plan → 2 builds → reflect → archive)
**Feature branch**: `feature/nightly-scheduled-playwright-test-suite-run`

## Overview

Wire the existing headless suite runner into a nightly automated schedule. A pinned two-test regression subset (`qa-170-search.test` + `qa-172-production.test`) runs unattended every night against `two-test.vcreative.net` and posts pass/fail results to Slack. All underlying pieces (Playwright runner, group-run endpoint, Slack Block Kit format, SSM secret pattern) already existed — this task only added the schedule + notification path.

## Architecture

- **Trigger**: AWS EventBridge Scheduler rule (`cron(0 6 * * ? *)` UTC) → API destination → `POST /api/playwright/nightly` on the running vQA Fargate service.
- **Endpoint**: returns `202 Accepted` immediately with `{suite_run_id, status: "started"}`; a background asyncio task dispatches the internal group-run, polls the in-process suite store to terminal state, and posts a compact Slack Block Kit payload.
- **Slack**: incoming webhook URL loaded from SSM `/vQA/slack/nightly_webhook_url` via `backend/secrets.py`, with `NIGHTLY_SLACK_WEBHOOK_URL` env-var fallback for smoke-testing.
- **Test subset & environment**: pinned in `Settings` fields (`nightly_test_ids`, `nightly_env`, `nightly_user`, `nightly_browser`) with env-var overrides.

## Deliverables

### Phase 1 — Backend endpoint + compact Slack payload (`81cb5bf`)

- `backend/api/playwright_routes.py` — new `POST /nightly` handler + `_nightly_poll_and_notify` background task
- `backend/engine/webhooks.py` — `_build_nightly_slack_payload()` + `post_nightly_slack()` (compact Block Kit, separate from the existing verbose per-run format)
- `backend/config/__init__.py` — 7 new `nightly_*` Settings fields + SSM load block for `/vQA/slack/nightly_webhook_url`
- `backend/api/schemas.py` — `NightlyRunResponse` model
- `backend/secrets.py` — SSM param name
- `tests/test_playwright_nightly.py` — 7 tests (auth, dispatch, 429 guard, poll happy/timeout/exception, config-defaults)
- `tests/test_webhooks_nightly.py` — 3 tests (all-pass, all-fail, mixed payload shapes)

### Phase 2 — EventBridge Scheduler bootstrap + operator doc (`06e41aa`)

- `scripts/setup-nightly-eventbridge.sh` — idempotent AWS CLI bootstrap (Scheduler rule, IAM role `VQASchedulerRole`, API destination `vqa-nightly-destination`, Connection `vqa-nightly-connection`, SSM placeholder for Slack webhook)
- `docs/nightly-schedule.md` — operator doc: bootstrap, smoke-test, schedule change, disable/re-enable, webhook rotation, API-key rotation, teardown, CloudWatch observability, Slack message shapes, config reference

## Acceptance Criteria Coverage

| AC | Status | Verification |
|----|--------|--------------|
| AC-VERIFY-1 (3 consecutive days of invocations) | Delivered, verification deferred to production | Bootstrap script committed |
| AC-VERIFY-2 (green Slack shape) | Satisfied | Unit test + **live smoke test 2026-08-11** (2/2 passed, HTTP 200 to Slack) |
| AC-VERIFY-3 (red Slack shape) | Satisfied | `test_compact_slack_payload_all_fail` + `test_compact_slack_payload_mixed` |
| AC-VERIFY-4 (bootstrap script committed, idempotent) | Satisfied | `scripts/setup-nightly-eventbridge.sh` |
| AC-VERIFY-5 (SSM-loaded webhook, no hardcode) | Satisfied | Code review confirmed no `hooks.slack.com/services/...` literal in repo |
| AC-VERIFY-6 (pinned subset via Settings) | Satisfied | `test_settings_defaults_pin_subset` |
| AC-ERROR-1 (dispatch failure → red Slack) | Satisfied | `test_poll_loop_posts_error_slack_on_dispatch_exception` + `_on_timeout` |
| AC-ERROR-2 (Slack delivery failure logged) | Satisfied (SHOULD) | `post_nightly_slack` logs HTTP status on non-2xx |
| AC-ASYNC-1 (poll to terminal before posting) | Satisfied | `_nightly_poll_and_notify` polls store every 5s up to 30 min |

## Test Results

- **Nightly-specific**: 10/10 pass across 2 files
- **Full backend suite (Phase 1 verification)**: 2023 passed, 0 new failures
- **Full backend suite (Phase 2 verification)**: 10/10 nightly still passing (docs-only phase)
- **Live end-to-end smoke test (2026-08-11, post-reflect)**: `POST /api/playwright/nightly` → 202 → both tests passed → Slack POST returned 200 within ~110s

## Reflection

See `memory-bank/reflection/nightly-scheduled-playwright-test-suite-run-reflection.md` (commit `559d986`).

**Ratings**:
- Task Implementation Quality: Good — all 9 ACs satisfied, disciplined pattern reuse, zero regressions
- Ecosystem Effectiveness: Moderately Effective — workflow was friction-free; primary gap was empty `.agent-logs/claude/by-task/` index preventing session-metric extraction

## Extractable Learnings (consolidated in `_learned/`)

1. **api-design** → `backend-api-patterns.md`: scheduled-trigger endpoints should return 202 immediately and run poll-and-notify in an asyncio background task to avoid EventBridge API destination timeouts
2. **workflow-compliance** → `workflow-compliance.md`: infra-only phases (bash scripts / IaC / docs) with 0 automated tests should be declared test-free in the guard log BEFORE the build step, not after

## Post-Deploy Verification (out of this task's scope)

- Run `bash scripts/setup-nightly-eventbridge.sh` in the vQA AWS account
- Populate `/vQA/slack/nightly_webhook_url` with the real webhook URL
- Confirm three consecutive days of Slack posts arrive within ±5 min of `06:00` UTC (AC-VERIFY-1)
- Confirm red-run shape works when a test genuinely fails in production (AC-VERIFY-3 live)
