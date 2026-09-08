# vQA Nightly Playwright Schedule

## Overview

A nightly regression subset runs automatically at **06:00 UTC** (02:00 EDT / 01:00 EST) every day. Results are posted to a Slack channel within 5 minutes of the scheduled fire time.

**Test subset:** `qa-170-search.test` + `qa-172-production.test`
**Target environment:** `test` → `two-test.vcreative.net`
**Persona:** `DemoProdDirector` (ProdDirector role)

The schedule fires via **AWS EventBridge Scheduler → API destination → `POST /api/playwright/nightly`** on the running vQA Fargate service. No Lambda or additional compute is needed.

---

## Architecture

```
EventBridge Scheduler
  cron(0 6 * * ? *) UTC
       │
       ▼
 EventBridge Connection
  (X-VQA-API-Key from SSM /vQA/api_keys)
       │
       ▼
 EventBridge API Destination
  POST https://vqa.vcreative.net/api/playwright/nightly
       │
       ▼
 vQA Fargate (vqa-backend, always running)
  POST /api/playwright/nightly
  ├── Dispatches internal group-run for the pinned subset
  ├── Returns 202 Accepted immediately {suite_run_id, status: "started"}
  └── Background asyncio task:
       ├── Polls playwright_suite_run_store every 5s (max 30 min)
       └── On terminal status:
            POST → SSM /vQA/slack/nightly_webhook_url
            (compact Block Kit: ✅/❌ header + per-test lines + "View Report" button)
```

---

## Bootstrap (First-Time Setup)

### Prerequisites

- AWS CLI v2 installed and configured with IAM permissions (see script header)
- The vQA Fargate service is deployed and reachable at `https://vqa.vcreative.net`
- SSM parameter `/vQA/api_keys` exists (created by `deploy.sh`)
- A Slack channel exists (e.g. `#vqa-nightly`) with an incoming webhook configured

### 1. Run the bootstrap script

```bash
chmod +x scripts/setup-nightly-eventbridge.sh
./scripts/setup-nightly-eventbridge.sh
```

The script is idempotent — safe to re-run. It creates or updates:
- IAM role `VQASchedulerRole` with `events:InvokeApiDestination` permission
- EventBridge Connection `vqa-nightly-connection` (stores the API key header)
- EventBridge API Destination `vqa-nightly-destination` (points to the endpoint)
- EventBridge Scheduler rule `vqa-nightly` (fires at 06:00 UTC daily)
- SSM placeholder at `/vQA/slack/nightly_webhook_url` if it does not already exist

### 2. Update the Slack webhook URL in SSM

The script creates a placeholder if the SSM parameter does not exist. Replace it with the real webhook URL:

```bash
aws ssm put-parameter \
  --name /vQA/slack/nightly_webhook_url \
  --value "https://hooks.slack.com/services/T.../B.../..." \
  --type SecureString \
  --overwrite \
  --region us-east-1
```

The vQA backend loads this URL at startup via `backend/secrets.py`. After changing it, restart the Fargate service (or wait for the next ECS deployment) so the new value is picked up:

```bash
aws ecs update-service \
  --cluster vqa-cluster \
  --service vqa-backend \
  --force-new-deployment \
  --region us-east-1
```

### 3. Smoke-test without waiting for 06:00 UTC

Trigger the endpoint manually to verify the end-to-end flow:

```bash
curl -X POST https://vqa.vcreative.net/api/playwright/nightly \
  -H "X-VQA-API-Key: $(aws ssm get-parameter \
        --name /vQA/api_keys --with-decryption \
        --query Parameter.Value --output text --region us-east-1 | cut -d, -f1)" \
  -s | jq .
```

Expected response:
```json
{"suite_run_id": "nightly-abc12345", "status": "started"}
```

Within 2–3 minutes (for 1-step tests), a Slack message should appear in the configured channel.

---

## Changing the Schedule

To change the fire time, update the cron expression (UTC):

```bash
# Example: move to 07:00 UTC
NIGHTLY_CRON="cron(0 7 * * ? *)" ./scripts/setup-nightly-eventbridge.sh
```

Or update directly via AWS CLI:

```bash
aws scheduler update-schedule \
  --name vqa-nightly \
  --group-name default \
  --schedule-expression "cron(0 7 * * ? *)" \
  --schedule-expression-timezone UTC \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "$(aws scheduler get-schedule \
      --name vqa-nightly --group-name default \
      --query Target --output json)" \
  --state ENABLED \
  --region us-east-1
```

---

## Disabling and Re-enabling

### Disable (pause) without deleting

```bash
aws scheduler update-schedule \
  --name vqa-nightly \
  --group-name default \
  --schedule-expression "cron(0 6 * * ? *)" \
  --schedule-expression-timezone UTC \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "$(aws scheduler get-schedule \
      --name vqa-nightly --group-name default \
      --query Target --output json)" \
  --state DISABLED \
  --region us-east-1
```

### Re-enable

```bash
aws scheduler update-schedule \
  --name vqa-nightly \
  --group-name default \
  --schedule-expression "cron(0 6 * * ? *)" \
  --schedule-expression-timezone UTC \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "$(aws scheduler get-schedule \
      --name vqa-nightly --group-name default \
      --query Target --output json)" \
  --state ENABLED \
  --region us-east-1
```

---

## Rotating the Slack Webhook URL

If the Slack webhook URL is revoked or rotated:

1. Create a new incoming webhook in Slack (App settings → Incoming Webhooks)
2. Update SSM:

```bash
aws ssm put-parameter \
  --name /vQA/slack/nightly_webhook_url \
  --value "https://hooks.slack.com/services/T.../B.../NEW_TOKEN" \
  --type SecureString \
  --overwrite \
  --region us-east-1
```

3. Force a new ECS task so the backend reloads secrets:

```bash
aws ecs update-service \
  --cluster vqa-cluster \
  --service vqa-backend \
  --force-new-deployment \
  --region us-east-1
```

---

## Rotating the API Key

If the vQA API key is rotated:

1. Update the key in SSM (path used by the vQA backend — see `deploy.sh`)
2. Re-run the bootstrap script to refresh the EventBridge Connection:

```bash
./scripts/setup-nightly-eventbridge.sh
```

The script always updates the connection's auth with the current key from SSM.

---

## Full Teardown (Rollback)

```bash
aws scheduler delete-schedule --name vqa-nightly --group-name default --region us-east-1
aws events delete-api-destination --name vqa-nightly-destination --region us-east-1
aws events delete-connection --name vqa-nightly-connection --region us-east-1
aws iam delete-role-policy --role-name VQASchedulerRole --policy-name VQASchedulerInvokeApiDestination
aws iam delete-role --role-name VQASchedulerRole
```

The SSM parameter `/vQA/slack/nightly_webhook_url` is not deleted by this sequence (it may be shared with other notifiers). Delete it explicitly if needed:

```bash
aws ssm delete-parameter --name /vQA/slack/nightly_webhook_url --region us-east-1
```

---

## Observability

### CloudWatch logs (backend)

All nightly invocations log to the existing `/ecs/vqa-backend` log group:

```bash
# Filter last 24 hours of nightly logs
aws logs filter-log-events \
  --log-group-name /ecs/vqa-backend \
  --filter-pattern '"[nightly]"' \
  --start-time $(python3 -c "import time; print(int((time.time() - 86400) * 1000))") \
  --region us-east-1 \
  --query "events[*].message" \
  --output text
```

Expected log sequence for a successful run:

```
[nightly] started suite_run_id=nightly-abc12345 test_ids=['qa-170-search.test', 'qa-172-production.test']
[nightly] Polling suite_run_id=nightly-abc12345 (timeout=1800s)
[nightly] Terminal status=completed passed=2 failed=0 — posting Slack
[nightly] Slack notification posted successfully (status=200)
```

### EventBridge Scheduler invocation history

EventBridge Scheduler does not emit invocation history to CloudWatch by default. To see recent invocations, check the Slack channel or filter the backend logs by `[nightly]` as above.

### Verifying the schedule is armed

```bash
aws scheduler get-schedule \
  --name vqa-nightly \
  --group-name default \
  --region us-east-1 \
  --query '{State: State, Expression: ScheduleExpression, Target: Target.Arn}'
```

---

## Slack Message Format

### Green (all pass)

```
✅ Nightly suite — 2/2 passed
✅ qa-170-search.test — 12.4s
✅ qa-172-production.test — 18.7s
[View Report]
```

### Red (one or more fail)

```
❌ Nightly suite — 1/2 passed
✅ qa-170-search.test — 12.4s
❌ qa-172-production.test — 18.7s
   Login failed: selector not found …
[View Report]
```

### Error (suite could not run)

```
❌ Nightly suite — could not start: suite run already in progress
```

```
❌ Nightly suite — poll timeout after 30 min (suite_run_id=nightly-abc12345)
```

---

## Configuration Reference

All nightly-specific settings live in `backend/config/__init__.py` and are overridable via environment variables. Current defaults:

| Setting | Default | Env var override |
|---------|---------|-----------------|
| `nightly_test_ids` | `["qa-170-search.test", "qa-172-production.test"]` | `NIGHTLY_TEST_IDS` (comma-separated) |
| `nightly_env` | `test` | `NIGHTLY_ENV` |
| `nightly_user` | `DemoProdDirector` | `NIGHTLY_USER` |
| `nightly_browser` | `chromium` | `NIGHTLY_BROWSER` |
| `nightly_slack_webhook_url` | `""` (loaded from SSM) | `NIGHTLY_SLACK_WEBHOOK_URL` |
| `nightly_poll_interval_seconds` | `5` | `NIGHTLY_POLL_INTERVAL_SECONDS` |
| `nightly_poll_timeout_seconds` | `1800` | `NIGHTLY_POLL_TIMEOUT_SECONDS` |

The Slack webhook URL is always loaded from SSM `/vQA/slack/nightly_webhook_url` at application startup. The env-var override is intended for smoke-testing only — do not commit it.
