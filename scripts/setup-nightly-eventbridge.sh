#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# vQA — Nightly Playwright Test Suite: EventBridge Scheduler Setup
# ─────────────────────────────────────────────────────────────────
#
# Creates (or updates) the AWS EventBridge Scheduler resources that
# invoke POST /api/playwright/nightly on the vQA Fargate service
# every night at 06:00 UTC (02:00 EDT / 01:00 EST).
#
# Architecture:
#   EventBridge Scheduler rule  →  Scheduler IAM role
#     → API destination (HTTPS POST to vqa.vcreative.net)
#       → Connection (X-VQA-API-Key header from SSM)
#
# This script is IDEMPOTENT — safe to re-run.  All resources use
# --overwrite / update-or-create semantics; existing resources are
# updated in place without changing their ARN or schedule history.
#
# Prerequisites:
#   - AWS CLI v2 installed and configured (aws configure OR IAM role)
#   - IAM permissions:
#       scheduler:CreateSchedule, scheduler:UpdateSchedule,
#       scheduler:GetSchedule, scheduler:CreateScheduleGroup,
#       scheduler:TagResource,
#       iam:CreateRole, iam:AttachRolePolicy, iam:PutRolePolicy,
#       iam:PassRole, iam:GetRole,
#       scheduler:CreateConnectionByIdempotencyToken (EventBridge Connections),
#       events:CreateApiDestination, events:UpdateApiDestination,
#       events:DescribeApiDestination,
#       ssm:GetParameter, ssm:PutParameter
#   - The vQA Fargate service must already be deployed and reachable
#     at https://vqa.vcreative.net/api/playwright/nightly
#   - SSM parameter /vQA/api_keys must exist (set during deploy.sh)
#
# Usage:
#   chmod +x scripts/setup-nightly-eventbridge.sh
#   ./scripts/setup-nightly-eventbridge.sh
#
# To override defaults:
#   VQA_PUBLIC_URL=https://staging.vqa.vcreative.net \
#   NIGHTLY_CRON="cron(0 8 * * ? *)" \
#   ./scripts/setup-nightly-eventbridge.sh
#
# To disable the schedule without deleting it:
#   aws scheduler update-schedule --name vqa-nightly \
#       --state DISABLED \
#       --schedule-expression "cron(0 6 * * ? *)" \
#       --flexible-time-window '{"Mode":"OFF"}' \
#       --target '...'  # unchanged
#
# Rollback (full teardown):
#   aws scheduler delete-schedule --name vqa-nightly
#   aws events delete-api-destination --name vqa-nightly-destination
#   aws events delete-connection --name vqa-nightly-connection
#   aws iam detach-role-policy --role-name VQASchedulerRole \
#       --policy-arn arn:aws:iam::aws:policy/AmazonEventBridgeSchedulerFullAccess
#   aws iam delete-role --role-name VQASchedulerRole
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration (override via environment) ─────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-404940539857}"
VQA_PUBLIC_URL="${VQA_PUBLIC_URL:-https://vqa.vcreative.net}"
NIGHTLY_CRON="${NIGHTLY_CRON:-cron(0 6 * * ? *)}"  # 06:00 UTC daily
SCHEDULE_NAME="vqa-nightly"
SCHEDULE_GROUP="${SCHEDULE_GROUP:-default}"
DESTINATION_NAME="vqa-nightly-destination"
CONNECTION_NAME="vqa-nightly-connection"
SCHEDULER_ROLE_NAME="VQASchedulerRole"
SSM_API_KEY_PATH="${SSM_API_KEY_PATH:-/vQA/api_keys}"
SSM_SLACK_PATH="${SSM_SLACK_PATH:-/vQA/slack/nightly_webhook_url}"

export AWS_PAGER=""
export AWS_DEFAULT_REGION="$AWS_REGION"

# ── Colours ───────────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; GRAY='\033[0;90m'
YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

step()  { echo -e "\n${CYAN}[SETUP] $1${NC}"; }
ok()    { echo -e "  ${GREEN}[OK]  $1${NC}"; }
info()  { echo -e "  ${GRAY}[..]  $1${NC}"; }
warn()  { echo -e "  ${YELLOW}[!!]  $1${NC}"; }
fail()  { echo -e "  ${RED}[FAIL] $1${NC}"; exit 1; }

# ── Pre-flight ────────────────────────────────────────────────────
step "Pre-flight checks"

if ! aws sts get-caller-identity --query "Arn" --output text > /dev/null 2>&1; then
    fail "AWS CLI not authenticated — run 'aws configure' or check IAM role."
fi
ok "AWS CLI authenticated (region: $AWS_REGION)"
info "Target endpoint: ${VQA_PUBLIC_URL}/api/playwright/nightly"
info "Schedule: $NIGHTLY_CRON (UTC)"

# ── Step 1: Read the vQA API key from SSM ─────────────────────────
step "Step 1: Reading API key from SSM ($SSM_API_KEY_PATH)"

if ! VQA_API_KEY=$(aws ssm get-parameter \
        --name "$SSM_API_KEY_PATH" \
        --with-decryption \
        --query "Parameter.Value" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null); then
    warn "SSM parameter $SSM_API_KEY_PATH not found — will read API_KEY from environment"
    if [ -z "${API_KEY:-}" ]; then
        fail "No API key available. Set API_KEY env var or ensure $SSM_API_KEY_PATH exists in SSM."
    fi
    VQA_API_KEY="$API_KEY"
fi
# Use the first key if comma-separated
VQA_API_KEY="${VQA_API_KEY%%,*}"
ok "API key loaded (${#VQA_API_KEY} chars)"

# ── Step 2: Ensure Slack webhook SSM placeholder exists ───────────
step "Step 2: Slack webhook SSM parameter ($SSM_SLACK_PATH)"

if aws ssm get-parameter \
        --name "$SSM_SLACK_PATH" \
        --query "Parameter.Value" \
        --output text \
        --region "$AWS_REGION" > /dev/null 2>&1; then
    ok "$SSM_SLACK_PATH already exists — skipping"
else
    warn "$SSM_SLACK_PATH not found — creating placeholder"
    warn "ACTION REQUIRED: After this script completes, update $SSM_SLACK_PATH"
    warn "  with the real Slack incoming webhook URL:"
    warn "  aws ssm put-parameter --name $SSM_SLACK_PATH \\"
    warn "    --value 'https://hooks.slack.com/services/XXX/YYY/ZZZ' \\"
    warn "    --type SecureString --overwrite"
    aws ssm put-parameter \
        --name "$SSM_SLACK_PATH" \
        --value "PLACEHOLDER_UPDATE_WITH_REAL_SLACK_WEBHOOK_URL" \
        --type "SecureString" \
        --description "Slack incoming webhook URL for vQA nightly regression Slack notifications" \
        --region "$AWS_REGION" \
        --overwrite
    ok "$SSM_SLACK_PATH placeholder created"
fi

# ── Step 3: IAM role for EventBridge Scheduler ───────────────────
step "Step 3: IAM role for EventBridge Scheduler ($SCHEDULER_ROLE_NAME)"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "scheduler.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

INVOKE_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "events:InvokeApiDestination"
    ],
    "Resource": "*"
  }]
}'

if SCHEDULER_ROLE_ARN=$(aws iam get-role \
        --role-name "$SCHEDULER_ROLE_NAME" \
        --query "Role.Arn" \
        --output text 2>/dev/null); then
    ok "IAM role exists: $SCHEDULER_ROLE_ARN"
else
    SCHEDULER_ROLE_ARN=$(aws iam create-role \
        --role-name "$SCHEDULER_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "EventBridge Scheduler role for vQA nightly Playwright invocations" \
        --query "Role.Arn" \
        --output text)
    ok "IAM role created: $SCHEDULER_ROLE_ARN"
fi

# Always apply/update inline policy (idempotent)
aws iam put-role-policy \
    --role-name "$SCHEDULER_ROLE_NAME" \
    --policy-name "VQASchedulerInvokeApiDestination" \
    --policy-document "$INVOKE_POLICY"
ok "Inline policy applied (InvokeApiDestination)"

# ── Step 4: EventBridge Connection (stores API key header) ────────
step "Step 4: EventBridge Connection ($CONNECTION_NAME)"

# Check if connection already exists
if CONNECTION_ARN=$(aws events describe-connection \
        --name "$CONNECTION_NAME" \
        --query "ConnectionArn" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null); then
    ok "Connection exists: $CONNECTION_ARN"
    # Update auth to keep API key current
    aws events update-connection \
        --name "$CONNECTION_NAME" \
        --authorization-type "API_KEY" \
        --auth-parameters "{
          \"ApiKeyAuthParameters\": {
            \"ApiKeyName\": \"X-VQA-API-Key\",
            \"ApiKeyValue\": \"${VQA_API_KEY}\"
          }
        }" \
        --region "$AWS_REGION" > /dev/null
    ok "Connection auth refreshed"
else
    CONNECTION_ARN=$(aws events create-connection \
        --name "$CONNECTION_NAME" \
        --description "API key connection for vQA nightly EventBridge Scheduler" \
        --authorization-type "API_KEY" \
        --auth-parameters "{
          \"ApiKeyAuthParameters\": {
            \"ApiKeyName\": \"X-VQA-API-Key\",
            \"ApiKeyValue\": \"${VQA_API_KEY}\"
          }
        }" \
        --region "$AWS_REGION" \
        --query "ConnectionArn" \
        --output text)
    ok "Connection created: $CONNECTION_ARN"
fi

# ── Step 5: EventBridge API Destination ──────────────────────────
step "Step 5: EventBridge API Destination ($DESTINATION_NAME)"

NIGHTLY_ENDPOINT="${VQA_PUBLIC_URL}/api/playwright/nightly"

if DESTINATION_ARN=$(aws events describe-api-destination \
        --name "$DESTINATION_NAME" \
        --query "ApiDestinationArn" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null); then
    ok "API destination exists: $DESTINATION_ARN"
    aws events update-api-destination \
        --name "$DESTINATION_NAME" \
        --connection-arn "$CONNECTION_ARN" \
        --invocation-endpoint "$NIGHTLY_ENDPOINT" \
        --http-method "POST" \
        --region "$AWS_REGION" > /dev/null
    ok "API destination updated (endpoint: $NIGHTLY_ENDPOINT)"
else
    DESTINATION_ARN=$(aws events create-api-destination \
        --name "$DESTINATION_NAME" \
        --description "POST /api/playwright/nightly on the vQA Fargate service" \
        --connection-arn "$CONNECTION_ARN" \
        --invocation-endpoint "$NIGHTLY_ENDPOINT" \
        --http-method "POST" \
        --region "$AWS_REGION" \
        --query "ApiDestinationArn" \
        --output text)
    ok "API destination created: $DESTINATION_ARN"
fi

# ── Step 6: EventBridge Scheduler Schedule ────────────────────────
step "Step 6: EventBridge Scheduler rule ($SCHEDULE_NAME)"

# Build target JSON — minimal, no input transformer needed (nightly endpoint ignores body)
TARGET_JSON=$(cat <<TARGETEOF
{
  "Arn": "${DESTINATION_ARN}",
  "RoleArn": "${SCHEDULER_ROLE_ARN}",
  "Input": "{}"
}
TARGETEOF
)

FLEXIBLE_WINDOW='{"Mode":"OFF"}'

if aws scheduler get-schedule \
        --name "$SCHEDULE_NAME" \
        --group-name "$SCHEDULE_GROUP" \
        --region "$AWS_REGION" > /dev/null 2>&1; then
    ok "Schedule exists — updating"
    aws scheduler update-schedule \
        --name "$SCHEDULE_NAME" \
        --group-name "$SCHEDULE_GROUP" \
        --schedule-expression "$NIGHTLY_CRON" \
        --schedule-expression-timezone "UTC" \
        --flexible-time-window "$FLEXIBLE_WINDOW" \
        --target "$TARGET_JSON" \
        --state "ENABLED" \
        --region "$AWS_REGION" > /dev/null
    ok "Schedule updated: $NIGHTLY_CRON (ENABLED)"
else
    aws scheduler create-schedule \
        --name "$SCHEDULE_NAME" \
        --group-name "$SCHEDULE_GROUP" \
        --schedule-expression "$NIGHTLY_CRON" \
        --schedule-expression-timezone "UTC" \
        --flexible-time-window "$FLEXIBLE_WINDOW" \
        --target "$TARGET_JSON" \
        --state "ENABLED" \
        --region "$AWS_REGION" > /dev/null
    ok "Schedule created: $NIGHTLY_CRON (ENABLED)"
fi

# ── Step 7: Verify ───────────────────────────────────────────────
step "Step 7: Verification"

SCHEDULE_STATE=$(aws scheduler get-schedule \
    --name "$SCHEDULE_NAME" \
    --group-name "$SCHEDULE_GROUP" \
    --region "$AWS_REGION" \
    --query "State" \
    --output text)
ok "Schedule state: $SCHEDULE_STATE"

DEST_STATE=$(aws events describe-api-destination \
    --name "$DESTINATION_NAME" \
    --query "ApiDestinationState" \
    --output text \
    --region "$AWS_REGION")
ok "API destination state: $DEST_STATE"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} vQA Nightly Schedule Setup Complete${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Schedule:    $NIGHTLY_CRON UTC (06:00 UTC = 02:00 EDT)"
echo "  Endpoint:    $NIGHTLY_ENDPOINT"
echo "  Auth:        X-VQA-API-Key (from EventBridge Connection)"
echo ""

if aws ssm get-parameter \
        --name "$SSM_SLACK_PATH" \
        --query "Parameter.Value" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null | grep -q "PLACEHOLDER"; then
    echo -e "${YELLOW}  ACTION REQUIRED: Update $SSM_SLACK_PATH with the real Slack webhook URL:${NC}"
    echo "  aws ssm put-parameter \\"
    echo "    --name $SSM_SLACK_PATH \\"
    echo "    --value 'https://hooks.slack.com/services/XXX/YYY/ZZZ' \\"
    echo "    --type SecureString --overwrite --region $AWS_REGION"
    echo ""
fi

echo "  To verify after first fire (06:00 UTC):"
echo "  aws scheduler get-schedule --name $SCHEDULE_NAME"
echo "  aws logs filter-log-events --log-group-name /ecs/vqa-backend \\"
echo "    --filter-pattern '[nightly]' --start-time \$(date -u +%s)000"
echo ""
