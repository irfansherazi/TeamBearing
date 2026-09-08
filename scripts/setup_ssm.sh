#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# vQA — One-Time SSM Parameter Store Setup
# ─────────────────────────────────────────────────────────────────
#
# Run this ONCE to store all vQA secrets in AWS SSM Parameter Store.
# After this, the application loads credentials automatically at
# startup — no .env configuration required.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure)
#   - IAM permissions: ssm:PutParameter, kms:GenerateDataKey
#
# Usage:
#   chmod +x scripts/setup_ssm.sh
#   ./scripts/setup_ssm.sh
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
echo "Using AWS region: $REGION"
echo ""

# ── Jira Integration ─────────────────────────────────────────────
echo "Setting up Jira credentials..."

read -r -p "  Jira service account email: " JIRA_EMAIL
aws ssm put-parameter \
    --name "/vQA/jira/email" \
    --value "$JIRA_EMAIL" \
    --type "String" \
    --overwrite \
    --region "$REGION" \
    --description "vQA Jira service account email"
echo "  ✓ /vQA/jira/email"

read -r -s -p "  Jira API token: " JIRA_TOKEN
echo ""
aws ssm put-parameter \
    --name "/vQA/jira/api_token" \
    --value "$JIRA_TOKEN" \
    --type "SecureString" \
    --overwrite \
    --region "$REGION" \
    --description "vQA Jira API token (encrypted)"
echo "  ✓ /vQA/jira/api_token (SecureString)"

read -r -p "  Atlassian domain (e.g. vcreative.atlassian.net): " JIRA_DOMAIN
aws ssm put-parameter \
    --name "/vQA/jira/domain" \
    --value "$JIRA_DOMAIN" \
    --type "String" \
    --overwrite \
    --region "$REGION" \
    --description "vQA Atlassian domain"
echo "  ✓ /vQA/jira/domain"

echo ""
# ── Role Credentials ─────────────────────────────────────────────
echo "Setting up role credentials..."

read -r -s -p "  Default test account password: " ROLE_PASS
echo ""
aws ssm put-parameter \
    --name "/vQA/roles/default_password" \
    --value "$ROLE_PASS" \
    --type "SecureString" \
    --overwrite \
    --region "$REGION" \
    --description "vQA shared test account password (encrypted)"
echo "  ✓ /vQA/roles/default_password (SecureString)"

read -r -p "  Sales Manager email (KB gap — other roles auto-loaded from KB): " SM_EMAIL
aws ssm put-parameter \
    --name "/vQA/roles/sales_manager_email" \
    --value "$SM_EMAIL" \
    --type "String" \
    --overwrite \
    --region "$REGION" \
    --description "vQA Sales Manager test account email"
echo "  ✓ /vQA/roles/sales_manager_email"

echo ""
# ── Playwright Standard Library ──────────────────────────────────
echo "Setting up Playwright Standard Library credentials..."

read -r -s -p "  Shared test account password: " SHARED_PASS
echo ""
aws ssm put-parameter \
    --name "/vQA/playwright/shared_test_password" \
    --value "$SHARED_PASS" \
    --type "SecureString" \
    --overwrite \
    --region "$REGION" \
    --description "vQA shared Playwright test password (encrypted)"
echo "  ✓ /vQA/playwright/shared_test_password (SecureString)"

read -r -s -p "  Admin test account password: " ADMIN_PASS
echo ""
aws ssm put-parameter \
    --name "/vQA/playwright/admin_test_password" \
    --value "$ADMIN_PASS" \
    --type "SecureString" \
    --overwrite \
    --region "$REGION" \
    --description "vQA admin Playwright test password (encrypted)"
echo "  ✓ /vQA/playwright/admin_test_password (SecureString)"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✓  All vQA SSM parameters created in $REGION"
echo "✓  vQA will now load credentials automatically at startup"
echo "✓  No .env configuration needed for Jira or role credentials"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Verify ───────────────────────────────────────────────────────
echo "Verifying parameters..."
aws ssm get-parameters-by-path \
    --path "/vQA/" \
    --recursive \
    --region "$REGION" \
    --query "Parameters[*].{Name:Name,Type:Type}" \
    --no-cli-pager \
    --output table
