# vQA — Deployment Guide

> **Audience:** DevOps / Platform Engineering
>
> This guide covers everything needed to deploy vQA to production,
> configure it for CI/CD pipeline integration, and operate it day-to-day.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Variables Reference](#2-environment-variables-reference)
3. [Docker Architecture](#3-docker-architecture)
4. [Production Deployment (Docker Compose)](#4-production-deployment-docker-compose)
5. [CI/CD Pipeline Integration](#5-cicd-pipeline-integration)
6. [AWS IAM Permissions](#6-aws-iam-permissions)
7. [S3 Bucket Configuration](#7-s3-bucket-configuration)
8. [Bedrock Knowledge Base Setup](#8-bedrock-knowledge-base-setup)
9. [Health Checks & Monitoring](#9-health-checks--monitoring)
10. [Updating & Rolling Restarts](#10-updating--rolling-restarts)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Requirement | Minimum Version | Notes |
|---|---|---|
| Docker | 24.0+ | Engine and CLI |
| Docker Compose | 2.20+ | Plugin (`docker compose`, not `docker-compose`) |
| AWS CLI | 2.x | For ECR push + SSM parameter store |
| Git | 2.x | |
| Target host RAM | 4 GB | Chromium + Xvfb is memory-intensive |
| Target host CPU | 2 vCPU | 4 recommended for concurrent batch runs |
| Outbound HTTPS | Required | Jira API, AWS Bedrock, S3 |

---

## 2. Environment Variables Reference

> **Product Registry**: `backend/config/products.yaml` is the single source of truth for all products. It maps slugs to environments, Jira board IDs, roles, and (for cross-domain products) the `playwright_base_url` Playwright tests navigate to after login. Add a new product by adding a YAML entry — no Python changes needed.

All configuration is passed via environment variables. Copy `.env.example` to
`.env` and populate every value before deploying.

### Jira

| Variable | Required | Description |
|---|---|---|
| `JIRA_EMAIL` | ✅ | Service account email for Jira API auth |
| `JIRA_API_TOKEN` | ✅ | Jira REST API token (Base64 Basic Auth) |
| `JIRA_DOMAIN` | ✅ | Your Atlassian domain, e.g. `vcreative.atlassian.net` |

### AWS

| Variable | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | ✅ | IAM access key (or use instance role in EC2/ECS) |
| `AWS_SECRET_ACCESS_KEY` | ✅ | IAM secret key |
| `AWS_REGION` | ✅ | Primary region, e.g. `us-east-1` |
| `AWS_BEDROCK_REGION` | — | Bedrock region if different; defaults to `us-west-2` |

### LLM / Bedrock

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | ✅ | Must be `bedrock` |
| `BEDROCK_MODEL_ID` | ✅ | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| `BEDROCK_ROLES_KB_ID` | ✅ | Knowledge Base ID for role permissions: `JXMMTMTI06` |

### S3

| Variable | Required | Description |
|---|---|---|
| `S3_BUCKET` | ✅ | `vcreative-deployments` |
| `S3_PREFIX` | ✅ | `vSuitePlatform/Buildartif/vqa-results` |

### Role Credentials

| Variable | Required | Description |
|---|---|---|
| `ROLE_DEFAULT_PASSWORD` | ✅ | Shared password for all test accounts |
| `ROLE_EMAIL_AE` | ✅ | Account Executive test email |
| `ROLE_EMAIL_SALES_MANAGER` | ✅ | Sales Manager test email |
| `ROLE_EMAIL_SALES_ASSISTANT` | ✅ | Sales Assistant test email |
| `ROLE_EMAIL_PRODUCTION_MANAGER` | ✅ | Production Manager test email |
| `ROLE_EMAIL_PRODUCER` | ✅ | Producer test email |
| `ROLE_EMAIL_GM_GSM` | ✅ | GM / GSM test email |
| `ROLE_EMAIL_DUBBER` | ✅ | Dubber test email |
| `ROLE_EMAIL_DIGITAL_DIRECTOR` | ✅ | Digital Director test email |

#### Playwright Storage State Variables

| Variable | Description |
|----------|-------------|
| `SHARED_TEST_PASSWORD` | Shared password for all non-admin test users (`generateStorageStates.mjs`) |
| `ADMIN_TEST_PASSWORD` | Password for the admin test account (`doc+test_admin@vcreativeinc.com`) |
| `ROLE_DEFAULT_PASSWORD` | Fallback password if no role-specific credential is set in SSM |

Storage states live in `playwright/storage/<TEST_ENV>/storageState_<username>.json`. Regenerate with:
```bash
node playwright/utils/generateStorageStates.mjs
```

#### Cross-Domain Product Variables

For products on a separate domain from the Angular SSO gateway (vPPO, vPromotions):

| Variable | Description |
|----------|-------------|
| `VPPO_BASE_URL` | Override the vPPO PHP app URL (default: resolved from `products.yaml`) |

These products use `ghost_login_environments` in `products.yaml` — the system logs in at the SSO gateway and navigates to the product domain to capture cross-domain cookies.

### Application

| Variable | Required | Default | Description |
|---|---|---|---|
| `VQA_MODE` | — | `interactive` | `interactive` or `headless` |
| `VQA_HEADLESS` | — | `0` | `0` = headed (visible browser, local QA), `1` = headless (CI/ECS). See [§ Headful Mode](#headful-mode). |
| `VQA_SLOW_MO` | — | `500` | ms delay between Playwright actions. 0 in headless CI. |
| `TARGET_URL` | — | — | Default target URL if not passed per-request |
| `MAX_RETRIES` | — | `3` | Per-step self-heal retry limit |
| `MAX_PLANNER_ITERATIONS` | — | `500` | Safety cap on the see-think-act loop |
| `LOG_LEVEL` | — | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ACCEPTED_TESTS_DIR` | — | `memory/accepted_tests` | Directory for accepted test records (FEAT-043). Auto-created if absent. |
| `ENABLE_SMART_REPLAY` | — | `true` | Set `false` to disable deterministic replay and always use AI planning (FEAT-043). |

---

## Headful Mode

> **Since TASK-031 / FEAT-043** — _Headful Playwright Execution & Test Persistence_

By default, vQA opens a **visible Chromium window** on the local machine.
This lets QA engineers and product managers observe the automation live
and verify that the agent is interacting with the application correctly.

### Choosing the Right Mode

| Scenario | `VQA_HEADLESS` | `VQA_SLOW_MO` | Notes |
|---|---|---|---|
| Local QA / demo observation | `0` (default) | `500` | Visible browser, deliberate pacing. Use on workstations. |
| Local fast development cycle | `0` | `0` | Visible browser, maximum speed. |
| GitHub Actions / ECS CI | `1` | `0` | No display, no window. Full CI headless. |
| Docker on a server with Xvfb | `0` | `500` | Requires Xvfb to be running (interactive mode Docker image). |

### Local Headful Setup (macOS / Linux Desktop)

On any machine with a desktop environment, no extra setup is needed:

```bash
# .env — minimal local dev config
VQA_HEADLESS=0      # or omit entirely (0 is the default)
VQA_SLOW_MO=500     # deliberate 500ms pacing so actions are watchable
```

When the operator clicks "Run" in the vQA dashboard, Chromium opens a
visible window within ~1 second. The browser navigates in real time and
closes when the run is complete.

#### Windows (PowerShell)

On Windows, use `start.ps1` instead of `start.sh`:

```powershell
.\start.ps1        # Start backend :8000 + frontend :5173
.\start.ps1 -Stop  # Stop all processes
```

`start.ps1` automatically loads `.env`, activates `.venv\Scripts\python.exe`, kills port conflicts, polls health, and streams logs — no manual venv activation needed.

> **PowerShell note**: Use `$env:VAR = 'value'` for environment variables, not `export VAR=value`.

### CI / Docker Headless Setup

In any environment without a display (GitHub Actions, ECS, EC2 without
a GUI desktop):

```bash
# .env (or task definition environment)
VQA_HEADLESS=1      # no window; Playwright runs internally
VQA_SLOW_MO=0       # maximum speed in CI
```

### Linux Server with Xvfb (interactive Docker image)

If you want headed-like mode on a Linux server (e.g. for noVNC streaming
at `localhost:6080`), use the interactive Docker image which starts Xvfb
automatically. Set `VQA_HEADLESS=0` to let Chromium render into the
virtual framebuffer. See [§ Interactive Mode Container](#interactive-mode-container).

### Local Docker X11 Forwarding (Quartz on macOS / X11 on Linux)

If you run the interactive Docker image locally but want the browser window to pop up natively on your host computer screen (rather than streaming it inside a VNC/noVNC viewer), you can forward the container's GUI to your host's X11 server:
1. Ensure an X11 server (such as **XQuartz** on macOS) is installed, running, and configured to *"Allow connections from network clients"*.
2. Start the container while overriding the image-level default `DISPLAY=:99` environment variable by passing the host display at container run time (e.g., via `-e` or in your docker-compose environment):
   ```bash
   docker run -e DISPLAY=host.docker.internal:0 -p 8000:8000 -v .:/app vqa-backend
   ```
   *Note: Our `resolve_display` helper will automatically detect this override and respect it instead of defaulting to the internal `:99` display.*

### Safety Note

> **Never commit `VQA_HEADLESS=0` to a production Dockerfile or ECS task
> definition.** Production containers run on servers without a display;
> Playwright will fail to launch a headed browser in that environment.
> Always use `VQA_HEADLESS=1` in any Docker-based deployment.

---

## 3. Docker Architecture

### Interactive Mode Container

A single container runs four processes managed by **supervisord**:

```
┌─ vQA Container ──────────────────────────────────────────────────┐
│                                                                   │
│  [supervisord]                                                    │
│       │                                                           │
│       ├── [Xvfb :99]          Virtual framebuffer display        │
│       │       └── Playwright renders Chromium into :99           │
│       │                                                           │
│       ├── [x11vnc]            VNC server connected to :99        │
│       │       └── Listens on :5900 (internal)                    │
│       │                                                           │
│       ├── [websockify/noVNC]  Proxies VNC → WebSocket            │
│       │       └── Exposes :6080 (noVNC web client)               │
│       │                                                           │
│       └── [uvicorn/FastAPI]   REST + WebSocket API               │
│               └── Exposes :8000                                   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

Published ports:
  8000 → FastAPI (React frontend + CI/CD)
  6080 → noVNC WebSocket (browser streaming)
```

### Headless Mode Container

For CI/CD: only the FastAPI process runs. No Xvfb, no x11vnc, no noVNC.
Playwright runs in `headless=True` mode.

```
┌─ vQA Container (Headless) ───────────────────────────────────────┐
│                                                                   │
│  [uvicorn/FastAPI :8000]                                          │
│       └── Playwright (Chromium, headless)                        │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

Published ports:
  8000 → FastAPI only
```

---

## 4. Production Deployment (Docker Compose)

### Step 1 — Provision the Host

Recommended: **Amazon EC2 `t3.xlarge`** (4 vCPU, 16 GB RAM) running Amazon
Linux 2023 or Ubuntu 22.04 LTS. Or any Docker-capable VM.

```bash
# Install Docker on Amazon Linux 2023
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

### Step 2 — Clone the Repository

```bash
git clone <repo-url> /opt/vqa
cd /opt/vqa
```

### Step 3 — Populate Environment Variables

**Option A: Using `.env` file** (for single-server deployments)

```bash
cp .env.example .env
nano .env   # populate all values
chmod 600 .env   # restrict read access
```

**Option B: Using AWS Systems Manager Parameter Store** (recommended for
production — no secrets on disk)

```bash
# Store each secret in SSM
aws ssm put-parameter \
  --name "/vqa/prod/JIRA_API_TOKEN" \
  --value "YOUR_TOKEN" \
  --type "SecureString"

# Retrieve at deploy time and inject into .env
aws ssm get-parameters-by-path \
  --path "/vqa/prod/" \
  --with-decryption \
  --query "Parameters[*].{Name:Name,Value:Value}" \
  --output json | jq -r '.[] | "\(.Name | split("/") | last)=\(.Value)"' \
  > .env
```

### Step 4 — Build and Start

#### Interactive Mode (with live browser streaming)

```bash
docker compose up -d --build

# Verify all services are healthy
docker compose ps
# Expected:
#   vqa-backend   running   0.0.0.0:8000->8000/tcp, 0.0.0.0:6080->6080/tcp
```

#### Headless Mode (API-only, no virtual display)

```bash
docker compose \
  -f docker-compose.yml \
  -f docker/docker-compose.ci.yml \
  up -d --build

# Verify
docker compose ps
# Expected:
#   vqa-backend   running   0.0.0.0:8000->8000/tcp
```

### Step 5 — Configure Reverse Proxy (Nginx)

Place vQA behind Nginx for TLS termination and routing.

```nginx
# /etc/nginx/sites-available/vqa
server {
    listen 443 ssl;
    server_name vqa.vcreative.net;

    ssl_certificate     /etc/ssl/certs/vqa.crt;
    ssl_certificate_key /etc/ssl/private/vqa.key;

    # FastAPI (REST + WebSocket)
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;   # Long timeout for streaming runs
    }

    # noVNC live browser stream
    location /novnc/ {
        proxy_pass         http://127.0.0.1:6080/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
    }
}

server {
    listen 80;
    server_name vqa.vcreative.net;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/vqa /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Step 6 — Smoke Test

```bash
# Health check
curl -s http://localhost:8000/health | jq
# {"status": "ok", "mode": "interactive", "bedrock": "connected", "s3": "connected"}

# Single ticket test (headless)
curl -X POST https://vqa.vcreative.net/execute \
  -H "Content-Type: application/json" \
  -d '{"jira_ticket_id":"VC2-TEST","role":"account_executive","target_url":"https://two-test.vcreative.net","mode":"headless"}'
```

---

## 5. CI/CD Pipeline Integration

### How It Works

vQA exposes a `/execute-batch` endpoint designed specifically for pipeline
gating. Your CI/CD step:

1. Posts a JSON payload with a list of Jira ticket IDs + roles
2. Polls `/status/{run_id}` (or waits for WebSocket terminal event)
3. Exits `0` if all AC steps pass, `1` if any fail

### GitHub Actions Example

```yaml
# .github/workflows/regression.yml
name: vQA Regression Gate

on:
  deployment_status:
    # Trigger after a successful deploy to staging

jobs:
  regression:
    runs-on: ubuntu-latest
    if: github.event.deployment_status.state == 'success'

    steps:
      - name: Trigger batch regression
        id: batch
        run: |
          RESPONSE=$(curl -sf -X POST \
            "${{ vars.VQA_URL }}/execute-batch" \
            -H "Content-Type: application/json" \
            -d '{
              "tickets": ${{ vars.REGRESSION_TICKETS }},
              "target_url": "${{ github.event.deployment_status.environment_url }}"
            }')
          echo "batch_id=$(echo $RESPONSE | jq -r '.batch_id')" >> $GITHUB_OUTPUT

      - name: Poll for completion
        run: |
          BATCH_ID="${{ steps.batch.outputs.batch_id }}"
          MAX_WAIT=600    # 10 minutes
          ELAPSED=0

          while [ $ELAPSED -lt $MAX_WAIT ]; do
            STATUS=$(curl -sf \
              "${{ vars.VQA_URL }}/batch-status/$BATCH_ID" | \
              jq -r '.status')

            echo "[$ELAPSED s] Batch status: $STATUS"

            if [ "$STATUS" = "completed" ]; then
              FAILURES=$(curl -sf \
                "${{ vars.VQA_URL }}/batch-status/$BATCH_ID" | \
                jq '[.runs[] | select(.status=="failed")] | length')
              echo "Failed runs: $FAILURES"
              exit $FAILURES
            fi

            if [ "$STATUS" = "failed" ]; then
              echo "Batch execution error"
              exit 1
            fi

            sleep 15
            ELAPSED=$((ELAPSED + 15))
          done

          echo "Timed out waiting for regression results"
          exit 1

      - name: Post report link to PR
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const batchId = '${{ steps.batch.outputs.batch_id }}';
            const reportUrl = `${{ vars.VQA_URL }}/batch-report/${batchId}`;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `## 🔬 vQA Regression Report\n[View Full Audit Report](${reportUrl})`
            });
```

Set these GitHub variables:
- `vars.VQA_URL` — e.g. `https://vqa.vcreative.net`
- `vars.REGRESSION_TICKETS` — JSON array, e.g. `[{"jira_ticket_id":"VC2-8967","role":"account_executive"}]`

### Jenkins Pipeline Example

```groovy
// Jenkinsfile
pipeline {
    agent any

    stages {
        stage('Deploy') {
            steps {
                sh './deploy.sh'
            }
        }

        stage('vQA Regression Gate') {
            steps {
                script {
                    def response = sh(
                        script: """
                            curl -sf -X POST ${VQA_URL}/execute-batch \\
                              -H 'Content-Type: application/json' \\
                              -d @regression-tickets.json
                        """,
                        returnStdout: true
                    ).trim()

                    def batchId = readJSON(text: response).batch_id
                    echo "Batch started: ${batchId}"

                    timeout(time: 15, unit: 'MINUTES') {
                        waitUntil {
                            def status = sh(
                                script: "curl -sf ${VQA_URL}/batch-status/${batchId} | jq -r '.status'",
                                returnStdout: true
                            ).trim()
                            return status == 'completed' || status == 'failed'
                        }
                    }

                    def finalStatus = sh(
                        script: "curl -sf ${VQA_URL}/batch-status/${batchId} | jq -r '.status'",
                        returnStdout: true
                    ).trim()

                    if (finalStatus == 'failed') {
                        error("vQA regression gate FAILED")
                    }
                }
            }
        }
    }

    post {
        always {
            sh """
                REPORT=\$(curl -sf ${VQA_URL}/batch-status/${batchId} | jq -r '.report_url')
                echo "Audit Report: \$REPORT"
            """
        }
    }
}
```

### `regression-tickets.json` Template

```json
{
  "tickets": [
    {"jira_ticket_id": "VC2-8967", "role": "account_executive"},
    {"jira_ticket_id": "VC2-8968", "role": "producer"},
    {"jira_ticket_id": "VC2-8969", "role": "dubber"}
  ],
  "target_url": "https://staging.vcreative.net"
}
```

---

## 6. AWS IAM Permissions

vQA requires a dedicated IAM role or user with the following policy.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ]
    },
    {
      "Sid": "BedrockKnowledgeBase",
      "Effect": "Allow",
      "Action": [
        "bedrock-agent-runtime:Retrieve",
        "bedrock-agent-runtime:RetrieveAndGenerate"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1:ACCOUNT_ID:knowledge-base/JXMMTMTI06"
      ]
    },
    {
      "Sid": "S3Artifacts",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::vcreative-deployments/vSuitePlatform/Buildartif/vqa-results/*"
      ]
    },
    {
      "Sid": "S3List",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::vcreative-deployments"],
      "Condition": {
        "StringLike": {
          "s3:prefix": ["vSuitePlatform/Buildartif/vqa-results/*"]
        }
      }
    }
  ]
}
```

If deploying on EC2, attach this policy to the **EC2 Instance Profile** instead
of using access key / secret key environment variables.

---

## 7. S3 Bucket Configuration

vQA writes to the existing `vcreative-deployments` bucket under the
`vSuitePlatform/Buildartif/vqa-results/` prefix.

### Lifecycle Policy (Cost Management)

```json
{
  "Rules": [
    {
      "ID": "vqa-results-expiry",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "vSuitePlatform/Buildartif/vqa-results/"
      },
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "STANDARD_IA"
        }
      ],
      "Expiration": {
        "Days": 90
      }
    }
  ]
}
```

Apply via CLI:
```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket vcreative-deployments \
  --lifecycle-configuration file://s3-lifecycle.json
```

### CORS (if report HTML needs to load S3 assets cross-origin)

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET"],
    "AllowedOrigins": ["https://vqa.vcreative.net"],
    "MaxAgeSeconds": 3000
  }
]
```

---

## 8. Bedrock Knowledge Base Setup

vQA uses **one** Bedrock Knowledge Base:

| KB | ID | Status |
|---|---|---|
| vProMedia-Roles-KB | `JXMMTMTI06` | ✅ Active — queried for role permissions |
| vProMedia-History-KB | `RPORC9I3BU` | ❌ Deprecated — not queried |
| vProMedia-Code-KB | `Z2CRZIUUXL` | ❌ Deprecated — not queried |

The Roles KB must be in a **Synced** state before vQA can function.
Verify via AWS Console → Bedrock → Knowledge bases → `JXMMTMTI06` → Status.

To trigger a manual sync (if content was updated):
```bash
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id JXMMTMTI06 \
  --data-source-id <your-data-source-id> \
  --region us-east-1
```

---

## 9. Health Checks & Monitoring

### Built-in Health Endpoint

```bash
GET /health
```

```json
{
  "status"  : "ok",
  "mode"    : "interactive",
  "version" : "1.0.0",
  "checks"  : {
    "bedrock": "connected",
    "s3"     : "connected",
    "jira"   : "reachable"
  }
}
```

### Docker Compose Health Check

The `docker-compose.yml` configures a health check on the FastAPI container:

```yaml
healthcheck:
  test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

### Recommended CloudWatch Alarms (EC2/ECS)

| Metric | Threshold | Action |
|---|---|---|
| HTTP 5xx rate on `/execute` | > 10% over 5 min | Alert + PagerDuty |
| Container CPU utilization | > 85% over 10 min | Scale or alert |
| Container Memory utilization | > 90% | Alert immediately |
| S3 `PutObject` errors | Any | Alert |

### Log Output

```bash
# Tail live logs
docker compose logs -f vqa

# Filter to LangGraph engine only
docker compose logs -f vqa | grep '\[engine\]'

# Filter to Playwright actions only
docker compose logs -f vqa | grep '\[executor\]'
```

---

## 10. Updating & Rolling Restarts

### Pull Latest and Rebuild

```bash
cd /opt/vqa
git pull origin main
docker compose up -d --build --no-deps vqa
```

### Environment Variable Changes Only (No Rebuild Needed)

```bash
# Edit .env (or repopulate from SSM)
docker compose up -d --no-build
```

### Full Teardown and Clean Restart

```bash
docker compose down -v
docker compose up -d --build
```

---

## 11. Troubleshooting

### Container fails to start — port already in use

```bash
lsof -i :8000
# Kill the conflicting process, or change the port mapping in docker-compose.yml
```

### Playwright can't connect to Xvfb

```bash
# Check supervisord process status inside the container
docker exec vqa supervisorctl status

# Restart individual processes
docker exec vqa supervisorctl restart xvfb
docker exec vqa supervisorctl restart fastapi
```

### Bedrock InvokeModel: Access Denied

1. Verify the IAM policy is attached to the correct role/user
2. Check the model ID matches the region. Claude 3.5 Sonnet may use a
   cross-region inference profile:
   ```
   us.anthropic.claude-3-5-sonnet-20241022-v2:0   # us-east-1 cross-region
   anthropic.claude-3-5-sonnet-20241022-v2:0       # us-west-2 direct
   ```
3. Confirm model access is enabled: **AWS Console → Bedrock → Model access**

### Jira 401 Unauthorized

```bash
# Test credentials directly
curl -u "YOUR_EMAIL:YOUR_API_TOKEN" \
  "https://YOUR-DOMAIN.atlassian.net/rest/api/3/myself"
```

If 401, generate a new API token at:
`https://id.atlassian.com/manage-profile/security/api-tokens`

### S3 PutObject: Access Denied

```bash
# Test S3 write access
aws s3 cp /dev/null \
  s3://vcreative-deployments/vSuitePlatform/Buildartif/vqa-results/test.txt

# Check effective permissions
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT_ID:role/vqa-role \
  --action-names s3:PutObject \
  --resource-arns "arn:aws:s3:::vcreative-deployments/vSuitePlatform/*"
```

### Agent self-heals forever / hits max iterations

- **Symptom:** Run stays in `running` state and never completes
- **Cause:** The AC step cannot be satisfied (element doesn't exist on page)
- **Fix:** Check step screenshots in S3. The `detailed_execution_log` in
  `/status/{run_id}` shows the LLM's reasoning for every retry.
  Adjust the Jira AC to match the actual UI state.

### noVNC iframe shows blank / connection refused

```bash
# Confirm websockify is running
docker exec vqa supervisorctl status novnc

# Verify port 6080 is published
docker compose ps

# Test WebSocket connectivity
curl -i -N -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     http://localhost:6080/websockify
```

---

*vQA · Deployment Guide · vCreative Engineering*
