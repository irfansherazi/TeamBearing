#!/bin/bash

# -----------------------------------------------------------------------------
# vQA Service -- ECS Fargate Deploy Script (COMPLETE)
# Run this from the vQA root directory:
#   chmod +x deploy.sh
#   ./deploy.sh
# -----------------------------------------------------------------------------

# --- CONFIGURE THESE BEFORE RUNNING ------------------------------------------
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="404940539857"
CLUSTER_NAME="vqa-cluster"
SERVICE_NAME_BE="vqa-backend"
SERVICE_NAME_FE="vqa-frontend"

# VPC + Subnets
VPC_ID="vpc-289ec74d"
SUBNET_IDS=("subnet-d31d77a4" "subnet-33a74156")

# ACM Certificate for vqa.vcreative.net
ACM_CERT_ARN="arn:aws:acm:us-east-1:404940539857:certificate/7a6ec408-7132-4d56-bec3-5ccc0cab6458"

# Optional: Route 53
ROUTE53_ZONE_ID="Z10RTA7U8MOZ23"
DOMAIN_NAME="vqa.vcreative.net"

# vQA Secrets & Config
JIRA_EMAIL="josh.schauer@vcreativeinc.com"
JIRA_API_TOKEN="ATATT3xFfGF0EQ-lnMHA1y6RbCaJmRx1xWGSu_od2lBpbKf_Nm8S94_NoOY_aEcnRHX49vtSWCCiNToY6ebamYGFF5XkKic3GWParmGokCRpPRxVMjG0AXLd5z8A9vgXLx9OSNMMxmaWmsXjTqSSkk4_555sAoa0STjHRkMixRcfyPaw4KeZHbc=20A8A2AC"
JIRA_DOMAIN="vcreative.atlassian.net"
BEDROCK_ROLES_KB_ID="JXMMTMTI06"
S3_BUCKET="vcreative-deployments"
API_KEY="vqa_prod_86f1f6a1e36c4b2789f2a24c58f9d0c2"
SHARED_TEST_PASSWORD="Ep!cVCteam2026$"
# -----------------------------------------------------------------------------

set -e # Exit on error
export AWS_PAGER="" # Disable pager
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ROOT_DIR=$(pwd)
SCRIPT_DIR="${ROOT_DIR}/ecs"

# Colors for output
CYAN='\033[0;36m'
GREEN='\033[0;32m'
GRAY='\033[0;90m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

write_step() { echo -e "\n${CYAN}[$1] $2${NC}"; }
write_ok() { echo -e "  ${GREEN}[OK] $1${NC}"; }
write_info() { echo -e "  ${GRAY}[..] $1${NC}"; }
write_warn() { echo -e "  ${YELLOW}[!!] $1${NC}"; }

# -- STEP 0-4: Infrastructure (Already Done - Idempotent) ---------------------
write_step 0 "Checking Infrastructure..."

# Verify AWS CLI is authenticated
if ! caller_identity=$(aws sts get-caller-identity --query "Arn" --output text 2>/dev/null); then
    echo -e "  ${RED}[FAIL] AWS CLI not authenticated.${NC}"
    exit 1
fi

# Step 1: Repos & Images
write_info "Authenticating Docker to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

for repo in "vqa-backend" "vqa-frontend"; do
    aws ecr create-repository --repository-name "$repo" --region "$AWS_REGION" 2>/dev/null || true
done

if [ "$SKIP_IMAGE_BUILD" != "true" ]; then
    write_info "Building and pushing images (linux/amd64)..."
    
    # Backend
    docker build --platform linux/amd64 -f "${ROOT_DIR}/docker/Dockerfile" -t "${ECR_REGISTRY}/vqa-backend:latest" "$ROOT_DIR"
    docker push "${ECR_REGISTRY}/vqa-backend:latest"
    
    # Frontend
    docker build --platform linux/amd64 \
        --build-arg VITE_API_URL="/api" \
        --build-arg VITE_API_BASE_URL="/api" \
        --build-arg VITE_API_KEY="$API_KEY" \
        -f "${ROOT_DIR}/Dockerfile.frontend" \
        -t "${ECR_REGISTRY}/vqa-frontend:latest" "$ROOT_DIR"
    docker push "${ECR_REGISTRY}/vqa-frontend:latest"
    
    write_ok "Images pushed to ECR"
else
    write_info "Skipping image build"
fi

# Step 2: Roles
TRUST_POLICY="file://${SCRIPT_DIR}/trust-policy-ecs-tasks.json"
TASK_POLICY="file://${SCRIPT_DIR}/task-role-policy.json"
EXEC_ROLE_NAME="VQAEcsExecutionRole"
TASK_ROLE_NAME="VQAEcsTaskRole"

if ! exec_role_arn=$(aws iam get-role --role-name "$EXEC_ROLE_NAME" --query "Role.Arn" --output text 2>/dev/null); then
    exec_role_arn=$(aws iam create-role --role-name "$EXEC_ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" --query "Role.Arn" --output text)
    aws iam attach-role-policy --role-name "$EXEC_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    aws iam attach-role-policy --role-name "$EXEC_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
fi

if ! task_role_arn=$(aws iam get-role --role-name "$TASK_ROLE_NAME" --query "Role.Arn" --output text 2>/dev/null); then
    task_role_arn=$(aws iam create-role --role-name "$TASK_ROLE_NAME" --assume-role-policy-document "$TRUST_POLICY" --query "Role.Arn" --output text)
fi
# Always update policies to ensure they are current
aws iam put-role-policy --role-name "$TASK_ROLE_NAME" --policy-name VQABedrockS3Access --policy-document "$TASK_POLICY"
aws iam attach-role-policy --role-name "$TASK_ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/AmazonElasticFileSystemClientFullAccess"

# Step 3: Security Groups
alb_sg_id=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=vqa-alb-sg" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text)
task_sg_id=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=vqa-task-sg" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text)

# Ensure Task SG has all required ports (80 for frontend, 8000 for backend, 6080 for noVNC)
aws ec2 authorize-security-group-ingress --group-id "$task_sg_id" --protocol tcp --port 80 --source-group "$alb_sg_id" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --group-id "$task_sg_id" --protocol tcp --port 8000 --source-group "$alb_sg_id" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --group-id "$task_sg_id" --protocol tcp --port 6080 --source-group "$alb_sg_id" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --group-id "$task_sg_id" --protocol tcp --port 3000 --source-group "$alb_sg_id" 2>/dev/null || true

# Step 4: EFS
efs_id=$(aws efs describe-file-systems --creation-token "vqa-data-v1" --query "FileSystems[0].FileSystemId" --output text)

# -- STEP 5: SSM Parameters --------------------------------------------------
write_step 5 "Storing Credentials in AWS SSM Parameter Store"
aws ssm put-parameter --name "/vQA/jira/email" --value "$JIRA_EMAIL" --type "String" --overwrite >/dev/null
aws ssm put-parameter --name "/vQA/jira/api_token" --value "$JIRA_API_TOKEN" --type "SecureString" --overwrite >/dev/null
aws ssm put-parameter --name "/vQA/jira/domain" --value "$JIRA_DOMAIN" --type "String" --overwrite >/dev/null
write_ok "Jira credentials stored in SSM (/vQA/jira/*)"

# -- STEP 6: CloudWatch Logs --------------------------------------------------
write_step 6 "Creating CloudWatch Log Groups"
for log_group in "/ecs/vqa-backend" "/ecs/vqa-frontend"; do
    aws logs create-log-group --log-group-name "$log_group" 2>/dev/null || true
done
write_ok "Log groups ready"

# -- STEP 7: ECS Cluster ------------------------------------------------------
write_step 7 "Creating ECS Cluster"
aws ecs create-cluster --cluster-name "$CLUSTER_NAME" >/dev/null 2>&1 || true
write_ok "Cluster $CLUSTER_NAME ready"

# -- STEP 8: Task Definitions -------------------------------------------------
write_step 8 "Registering Task Definitions"

# Resolve build number from Git revision count
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    COMMIT_COUNT=$(git rev-list --count HEAD)
    VQA_BUILD_NUMBER="1.0.${COMMIT_COUNT}"
else
    VQA_BUILD_NUMBER="1.0.0"
fi
write_info "Resolved VQA_BUILD_NUMBER to: ${VQA_BUILD_NUMBER}"

# Backend Task (4GB Memory, 2vCPU for Playwright)
write_info "Registering Backend Task Definition..."
cat <<EOF > ecs-vqa-backend-task.json
{
  "family": "vqa-backend",
  "taskRoleArn": "$task_role_arn",
  "executionRoleArn": "$exec_role_arn",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "6144",
  "containerDefinitions": [
    {
      "name": "vqa-backend",
      "image": "$ECR_REGISTRY/vqa-backend:latest",
      "portMappings": [
        { "containerPort": 8000, "hostPort": 8000, "protocol": "tcp" },
        { "containerPort": 6080, "hostPort": 6080, "protocol": "tcp" }
      ],
      "environment": [
        { "name": "VQA_MODE", "value": "interactive" },
        { "name": "DISPLAY", "value": ":99" },
        { "name": "VQA_HEADLESS", "value": "0" },
        { "name": "BROWSER_HEADLESS", "value": "false" },
        { "name": "BEDROCK_ROLES_KB_ID", "value": "$BEDROCK_ROLES_KB_ID" },
        { "name": "DISABLE_BEDROCK_ROLES_KB", "value": "true" },
        { "name": "S3_BUCKET", "value": "$S3_BUCKET" },
        { "name": "AWS_REGION", "value": "$AWS_REGION" },
        { "name": "API_KEYS", "value": "$API_KEY" },
        { "name": "API_AUTH_ENABLED", "value": "true" },
        { "name": "EXTERNAL_HOST", "value": "$DOMAIN_NAME" },
        { "name": "EXTERNAL_PROTOCOL", "value": "https" },
        { "name": "VQA_BUILD_NUMBER", "value": "$VQA_BUILD_NUMBER" },
        { "name": "SHARED_TEST_PASSWORD", "value": "$SHARED_TEST_PASSWORD" },
        { "name": "SSO_PUBLIC_KEY", "value": "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCrtF1/vtK6y+kz6k9sfXyR3hM8\n2oNTZEU/6skRiFZLH9vpSIrP3WKFvajIDSfKrMZz/14PG3VegR+P/fEZEPKa5Tyd\nOAzWAhjt/lwFFkUetm1Fd29nruXak21A1lkQztesXryzoXAxzJ4Pw6n9qzvfdIL4\ndmY5zd1ctt53OvnzNQIDAQAB\n-----END PUBLIC KEY-----" }
      ],
      "mountPoints": [
        { "sourceVolume": "vqa-data", "containerPath": "/app/memory", "readOnly": false }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/vqa-backend",
          "awslogs-region": "$AWS_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ],
  "volumes": [
    {
      "name": "vqa-data",
      "efsVolumeConfiguration": {
        "fileSystemId": "$efs_id",
        "transitEncryption": "ENABLED"
      }
    }
  ]
}
EOF

BACKEND_TASK_DEF_ARN=$(aws ecs register-task-definition --cli-input-json file://ecs-vqa-backend-task.json --query "taskDefinition.taskDefinitionArn" --output text)
write_ok "Backend Task Registered"

# Frontend Task
write_info "Registering Frontend Task Definition..."
cat <<EOF > ecs-vqa-frontend-task.json
{
  "family": "vqa-frontend",
  "taskRoleArn": "$task_role_arn",
  "executionRoleArn": "$exec_role_arn",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "containerDefinitions": [
    {
      "name": "vqa-frontend",
      "image": "$ECR_REGISTRY/vqa-frontend:latest",
      "portMappings": [
        { "containerPort": 80, "hostPort": 80, "protocol": "tcp" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/vqa-frontend",
          "awslogs-region": "$AWS_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
EOF

FRONTEND_TASK_DEF_ARN=$(aws ecs register-task-definition --cli-input-json file://ecs-vqa-frontend-task.json --query "taskDefinition.taskDefinitionArn" --output text)
write_ok "Frontend Task Registered"

# -- STEP 9: Load Balancer ----------------------------------------------------
write_step 9 "Setting up Application Load Balancer"

# Create ALB
if ! alb_arn=$(aws elbv2 describe-load-balancers --names "vqa-alb" --query "LoadBalancers[0].LoadBalancerArn" --output text 2>/dev/null); then
    alb_arn=$(aws elbv2 create-load-balancer --name "vqa-alb" \
        --subnets "${SUBNET_IDS[@]}" --security-groups "$alb_sg_id" \
        --query "LoadBalancers[0].LoadBalancerArn" --output text)
    write_ok "ALB Created: $alb_arn"
else
    write_info "ALB already exists: $alb_arn"
fi

# Target Groups (Backend 8000, Backend 6080, Frontend 80)
if ! tg_be_arn=$(aws elbv2 describe-target-groups --names "vqa-be-tg" --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null); then
    tg_be_arn=$(aws elbv2 create-target-group --name "vqa-be-tg" --protocol HTTP --port 8000 --vpc-id "$VPC_ID" \
        --target-type ip --health-check-path "/health" --query "TargetGroups[0].TargetGroupArn" --output text)
    write_ok "Backend TG Created"
else
    tg_be_arn=$(aws elbv2 describe-target-groups --names "vqa-be-tg" --query "TargetGroups[0].TargetGroupArn" --output text)
fi

if ! tg_vnc_arn=$(aws elbv2 describe-target-groups --names "vqa-vnc-tg" --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null); then
    tg_vnc_arn=$(aws elbv2 create-target-group --name "vqa-vnc-tg" --protocol HTTP --port 6080 --vpc-id "$VPC_ID" \
        --target-type ip --health-check-path "/" --query "TargetGroups[0].TargetGroupArn" --output text)
    write_ok "VNC TG Created"
else
    tg_vnc_arn=$(aws elbv2 describe-target-groups --names "vqa-vnc-tg" --query "TargetGroups[0].TargetGroupArn" --output text)
fi

if ! tg_fe_arn=$(aws elbv2 describe-target-groups --names "vqa-fe-tg" --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null); then
    tg_fe_arn=$(aws elbv2 create-target-group --name "vqa-fe-tg" --protocol HTTP --port 80 --vpc-id "$VPC_ID" \
        --target-type ip --health-check-path "/" --query "TargetGroups[0].TargetGroupArn" --output text)
    write_ok "Frontend TG Created"
else
    tg_fe_arn=$(aws elbv2 describe-target-groups --names "vqa-fe-tg" --query "TargetGroups[0].TargetGroupArn" --output text)
fi

# HTTPS Listener
listener_arn=$(aws elbv2 describe-listeners --load-balancer-arn "$alb_arn" --query "Listeners[?Port==\`443\`].ListenerArn" --output text 2>/dev/null || echo "None")
if [ "$listener_arn" == "None" ] || [ -z "$listener_arn" ]; then
    write_info "Creating HTTPS Listener..."
    listener_arn=$(aws elbv2 create-listener --load-balancer-arn "$alb_arn" \
        --protocol HTTPS --port 443 --certificates "CertificateArn=$ACM_CERT_ARN" \
        --default-actions "Type=forward,TargetGroupArn=$tg_fe_arn" \
        --query "Listeners[0].ListenerArn" --output text)
    write_ok "HTTPS Listener Created"
else
    write_info "HTTPS Listener already exists: $listener_arn"
fi

# HTTP Redirect Listener
http_listener_arn=$(aws elbv2 describe-listeners --load-balancer-arn "$alb_arn" --query "Listeners[?Port==\`80\`].ListenerArn" --output text 2>/dev/null || echo "None")
if [ "$http_listener_arn" == "None" ] || [ -z "$http_listener_arn" ]; then
    write_info "Creating HTTP Redirect Listener..."
    aws elbv2 create-listener --load-balancer-arn "$alb_arn" --protocol HTTP --port 80 \
        --default-actions "Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}" >/dev/null
    write_ok "HTTP Redirect Listener Created"
else
    write_info "HTTP Redirect Listener already exists"
fi

# ALB idle timeout — must be >= storage generation duration (~3-5 min for 17 users × 3 envs)
aws elbv2 modify-load-balancer-attributes \
    --load-balancer-arn "$alb_arn" \
    --attributes Key=idle_timeout.timeout_seconds,Value=300 >/dev/null
write_ok "ALB idle timeout set to 300s"

# Routing Rules
write_info "Configuring routing rules..."
# API Rule
if ! aws elbv2 describe-rules --listener-arn "$listener_arn" --query "Rules[?Priority=='10']" --output text | grep -q "10"; then
    aws elbv2 create-rule --listener-arn "$listener_arn" --priority 10 \
        --conditions "Field=path-pattern,Values='/api/*','/docs','/openapi.json'" \
        --actions "Type=forward,TargetGroupArn=$tg_be_arn" >/dev/null
    write_ok "API Rule Created"
else
    write_info "API Rule already exists"
fi

# WebSocket Rule
if ! aws elbv2 describe-rules --listener-arn "$listener_arn" --query "Rules[?Priority=='20']" --output text | grep -q "20"; then
    aws elbv2 create-rule --listener-arn "$listener_arn" --priority 20 \
        --conditions "Field=path-pattern,Values='/ws/*'" \
        --actions "Type=forward,TargetGroupArn=$tg_be_arn" >/dev/null
    write_ok "WebSocket Rule Created"
else
    write_info "WebSocket Rule already exists"
fi

# noVNC Rule (Priority 30) — path-prefix routing for per-session VNC traffic.
# Phase 3 (per-user-session-isolation): changed from individual asset paths
# (/vnc.html, /core/*, …) to a single /vnc/* prefix.  The nginx sidecar inside
# the container multiplexes /vnc/<session_id>/* to the correct per-session
# websockify port by reading /var/run/vqa/sessions.map (ADR-3, ADR-14).
# NOTE: If this rule already exists with the old single-asset paths, update it
# manually in the AWS console or delete it (aws elbv2 delete-rule) and let
# this script recreate it with the new path-prefix pattern.
if ! aws elbv2 describe-rules --listener-arn "$listener_arn" --query "Rules[?Priority=='30']" --output text | grep -q "30"; then
    aws elbv2 create-rule --listener-arn "$listener_arn" --priority 30 \
        --conditions "Field=path-pattern,Values='/vnc/*'" \
        --actions "Type=forward,TargetGroupArn=$tg_vnc_arn" >/dev/null
    write_ok "noVNC Path-Prefix Rule Created (priority 30, /vnc/*)"
else
    write_info "noVNC Path-Prefix Rule already exists (priority 30)"
fi

# noVNC WebSocket Rule (Priority 31) — /websockify/* path-prefix for per-session
# websockify WebSocket connections.  The nginx sidecar routes
# /websockify/<session_id> to the correct per-session websockify port.
# Phase 3: changed from exact-match /websockify to prefix /websockify/*.
if ! aws elbv2 describe-rules --listener-arn "$listener_arn" --query "Rules[?Priority=='31']" --output text | grep -q "31"; then
    aws elbv2 create-rule --listener-arn "$listener_arn" --priority 31 \
        --conditions "Field=path-pattern,Values='/websockify/*'" \
        --actions "Type=forward,TargetGroupArn=$tg_vnc_arn" >/dev/null
    write_ok "noVNC WebSocket Path-Prefix Rule Created (priority 31, /websockify/*)"
else
    write_info "noVNC WebSocket Path-Prefix Rule already exists (priority 31)"
fi

# -- STEP 10: ECS Services ----------------------------------------------------
write_step 10 "Launching ECS Services"

# Backend Service
# Register BOTH the API (8000) and VNC (6080) target groups.
# The container exposes both ports; the ALB routes /api/* to 8000 and /vnc* to 6080.
if ! aws ecs describe-services --cluster "$CLUSTER_NAME" --services "vqa-backend" --query "services[0].status" --output text 2>/dev/null | grep -q "ACTIVE"; then
    aws ecs create-service --cluster "$CLUSTER_NAME" --service-name "vqa-backend" \
        --task-definition "vqa-backend" --desired-count 1 --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$(IFS=,; echo "${SUBNET_IDS[*]}")],securityGroups=[$task_sg_id],assignPublicIp=ENABLED}" \
        --load-balancers \
            "targetGroupArn=$tg_be_arn,containerName=vqa-backend,containerPort=8000" \
            "targetGroupArn=$tg_vnc_arn,containerName=vqa-backend,containerPort=6080" \
        >/dev/null
    write_ok "Backend Service Started"
else
    # Check if the VNC target group is already registered.
    # update-service cannot add new load-balancer registrations — must recreate.
    existing_tgs=$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "vqa-backend" \
        --query "services[0].loadBalancers[*].targetGroupArn" --output text 2>/dev/null || echo "")
    if echo "$existing_tgs" | grep -q "vqa-vnc-tg"; then
        aws ecs update-service --cluster "$CLUSTER_NAME" --service "vqa-backend" --task-definition "$BACKEND_TASK_DEF_ARN" --force-new-deployment >/dev/null
        write_info "Backend Service Updated"
    else
        write_info "Adding VNC target group — must recreate service..."
        aws ecs update-service --cluster "$CLUSTER_NAME" --service "vqa-backend" --desired-count 0 >/dev/null
        aws ecs delete-service --cluster "$CLUSTER_NAME" --service "vqa-backend" --force >/dev/null
        # Wait for service to fully drain (can take 30-60s)
        write_info "Waiting for old service to drain..."
        for i in $(seq 1 24); do
            svc_status=$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "vqa-backend" \
                --query "services[0].status" --output text 2>/dev/null || echo "GONE")
            if [ "$svc_status" == "INACTIVE" ] || [ "$svc_status" == "GONE" ] || [ "$svc_status" == "None" ]; then
                break
            fi
            sleep 5
        done
        aws ecs create-service --cluster "$CLUSTER_NAME" --service-name "vqa-backend" \
            --task-definition "vqa-backend" --desired-count 1 --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[$(IFS=,; echo "${SUBNET_IDS[*]}")],securityGroups=[$task_sg_id],assignPublicIp=ENABLED}" \
            --load-balancers \
                "targetGroupArn=$tg_be_arn,containerName=vqa-backend,containerPort=8000" \
                "targetGroupArn=$tg_vnc_arn,containerName=vqa-backend,containerPort=6080" \
            >/dev/null
        write_ok "Backend Service Recreated with VNC target group"
    fi
fi

# Frontend Service
if ! aws ecs describe-services --cluster "$CLUSTER_NAME" --services "vqa-frontend" --query "services[0].status" --output text 2>/dev/null | grep -q "ACTIVE"; then
    aws ecs create-service --cluster "$CLUSTER_NAME" --service-name "vqa-frontend" \
        --task-definition "vqa-frontend" --desired-count 1 --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$(IFS=,; echo "${SUBNET_IDS[*]}")],securityGroups=[$task_sg_id],assignPublicIp=ENABLED}" \
        --load-balancers "targetGroupArn=$tg_fe_arn,containerName=vqa-frontend,containerPort=80" >/dev/null
    write_ok "Frontend Service Started"
else
    aws ecs update-service --cluster "$CLUSTER_NAME" --service "vqa-frontend" --task-definition "$FRONTEND_TASK_DEF_ARN" --force-new-deployment >/dev/null
    write_info "Frontend Service Updated"
fi

# -- STEP 11: Route 53 DNS ----------------------------------------------------
write_step 11 "Updating Route 53 DNS Record"

ALB_DNS=$(aws elbv2 describe-load-balancers --names "vqa-alb" --query "LoadBalancers[0].DNSName" --output text)
ALB_ZONE_ID=$(aws elbv2 describe-load-balancers --names "vqa-alb" --query "LoadBalancers[0].CanonicalHostedZoneId" --output text)

# Create JSON for Route 53 change
cat <<EOF > route53-change.json
{
  "Comment": "Update vQA Alias Record",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "$DOMAIN_NAME",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "$ALB_ZONE_ID",
          "DNSName": "$ALB_DNS",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}
EOF

aws route53 change-resource-record-sets --hosted-zone-id "$ROUTE53_ZONE_ID" --change-batch file://route53-change.json >/dev/null
write_ok "DNS Record updated: $DOMAIN_NAME -> $ALB_DNS"

write_step "SUCCESS" "vQA Deployment Complete!"
write_info "Access your app at: https://$DOMAIN_NAME"
