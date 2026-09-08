# -----------------------------------------------------------------------------
# vQA Service -- ECS Fargate Deploy Script (Part 1: Infrastructure)
# Run this from the vQA root directory:
#   .\deploy.ps1
#
# What it does (in order):
#   0. Validates configuration (catches placeholder values + AWS auth)
#   1. Builds Docker images and pushes to ECR
#   2. Creates IAM roles (execution + task with Bedrock/S3 access)
#   3. Creates security groups (ALB, ECS tasks, EFS)
#   4. Creates an EFS filesystem + mount targets for persistent state
# -----------------------------------------------------------------------------
param(
    [switch]$SkipImageBuild,  # Pass -SkipImageBuild to skip docker build+push
    [switch]$SkipEfs          # Pass -SkipEfs if EFS already exists (redeploying)
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# --- CONFIGURE THESE BEFORE RUNNING ------------------------------------------
$AWS_REGION       = "us-east-1"
$AWS_ACCOUNT_ID   = "404940539857"
$CLUSTER_NAME     = "vqa-cluster"
$SERVICE_NAME_BE  = "vqa-backend"
$SERVICE_NAME_FE  = "vqa-frontend"

# VPC + Subnets
$VPC_ID           = "vpc-289ec74d"
$SUBNET_IDS       = @("subnet-d31d77a4", "subnet-33a74156")
$TASK_SUBNET_IDS  = $SUBNET_IDS

# ACM Certificate for vqa.vcreative.net
$ACM_CERT_ARN     = "arn:aws:acm:us-east-1:404940539857:certificate/7a6ec408-7132-4d56-bec3-5ccc0cab6458"

# Optional: Route 53 (if you want the script to automate DNS later)
$ROUTE53_ZONE_ID  = "REPLACE_WITH_ROUTE53_ZONE_ID_LATER"
$DOMAIN_NAME      = "vqa.vcreative.net"

# vQA Secrets & Config (Fill these in before running!)
$JIRA_EMAIL          = "josh.schauer@vcreativeinc.com"
$JIRA_API_TOKEN      = "ATATT3xFfGF0EQ-lnMHA1y6RbCaJmRx1xWGSu_od2lBpbKf_Nm8S94_NoOY_aEcnRHX49vtSWCC
     iNToY6ebamYGFF5XkKic3GWParmGokCRpPRxVMjG0AXLd5z8A9vgXLx9OSNMMxmaWmsXjTqSSkk4
     _555sAoa0STjHRkMixRcfyPaw4KeZHbc=20A8A2AC"
$JIRA_DOMAIN         = "vcreative.atlassian.net"
$BEDROCK_ROLES_KB_ID = "JXMMTMTI06"
$S3_BUCKET           = "vcreative-deployments"
$API_KEY             = "vqa_prod_86f1f6a1e36c4b2789f2a24c58f9d0c2"
# -----------------------------------------------------------------------------

$ECR_REGISTRY = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
$SCRIPT_DIR   = Join-Path (Get-Location) "ecs"
$ROOT_DIR     = Get-Location

function Write-Step { param($n, $msg) Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg)     Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Info { param($msg)     Write-Host "  [..] $msg" -ForegroundColor Gray }
function Write-Warn { param($msg)     Write-Host "  [!!] $msg" -ForegroundColor Yellow }

function Invoke-AWS {
    $result = aws @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "AWS CLI error: $result" }
    return $result
}

# -- PRE-FLIGHT: Validate configuration ---------------------------------------
Write-Step 0 "Validating configuration"

$requiredReplacements = @{
    'VPC_ID'          = $VPC_ID
    'SUBNET_IDS[0]'   = $SUBNET_IDS[0]
    'SUBNET_IDS[1]'   = $SUBNET_IDS[1]
    'ACM_CERT_ARN'    = $ACM_CERT_ARN
}
$hasErrors = $false
foreach ($kv in $requiredReplacements.GetEnumerator()) {
    if ($kv.Value -match 'REPLACE_WITH') {
        Write-Warn "$($kv.Key) still has a placeholder value -- update it in the config section above."
        $hasErrors = $true
    }
}
if ($hasErrors) {
    Write-Host "`n  [FAIL] Fix the placeholder values above before running." -ForegroundColor Red
    exit 1
}

# Verify AWS CLI is authenticated
try {
    $callerArn = aws sts get-caller-identity --query "Arn" --output text 2>&1
    if ($LASTEXITCODE -ne 0) { throw $callerArn }
    Write-OK "AWS identity: $callerArn"
} catch {
    Write-Host "  [FAIL] AWS CLI not authenticated. Run 'aws configure' or set credentials." -ForegroundColor Red
    exit 1
}

# -- STEP 1: Build + Push Docker Images ---------------------------------------
Write-Step 1 "Building and pushing Docker images to ECR"

if (-not $SkipImageBuild) {
    # Authenticate Docker -> ECR
    aws ecr get-login-password --region $AWS_REGION |
        docker login --username AWS --password-stdin $ECR_REGISTRY

    # Create ECR repos (ignore error if already exists)
    foreach ($repo in @("vqa-backend", "vqa-frontend")) {
        try {
            aws ecr create-repository --repository-name $repo `
                --image-scanning-configuration scanOnPush=true `
                --region $AWS_REGION 2>&1 | Out-Null
        } catch {
            # Repo already exists -- that's fine
        }
        Write-Info "ECR repo: $repo"
    }

    # Build + tag + push backend
    Write-Info "Building backend..."
    docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${ECR_REGISTRY}/vqa-backend:latest" $ROOT_DIR
    docker push "${ECR_REGISTRY}/vqa-backend:latest"
    Write-OK "Backend image pushed"

    # Build + tag + push frontend 
    Write-Info "Building frontend..."
    docker build -f "${ROOT_DIR}/Dockerfile.frontend" -t "${ECR_REGISTRY}/vqa-frontend:latest" $ROOT_DIR
    docker push "${ECR_REGISTRY}/vqa-frontend:latest"
    Write-OK "Frontend image pushed"
} else {
    Write-Info "Skipping image build (-SkipImageBuild flag set)"
}

# -- STEP 2: IAM Roles ---------------------------------------------------------
Write-Step 2 "Creating IAM roles"

$trustPolicyFile = Join-Path $SCRIPT_DIR "trust-policy-ecs-tasks.json"
$taskPolicyFile  = Join-Path $SCRIPT_DIR "task-role-policy.json"

# Execution Role
$EXEC_ROLE_NAME = "VQAEcsExecutionRole"
$execRoleArn = aws iam get-role --role-name $EXEC_ROLE_NAME --query "Role.Arn" --output text 2>$null

if (-not $execRoleArn -or $execRoleArn -eq "None") {
    $execRoleArn = aws iam create-role --role-name $EXEC_ROLE_NAME `
        --assume-role-policy-document "file://${trustPolicyFile}" `
        --query "Role.Arn" --output text

    aws iam attach-role-policy --role-name $EXEC_ROLE_NAME `
        --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
    aws iam attach-role-policy --role-name $EXEC_ROLE_NAME `
        --policy-arn "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
    Write-OK "Created execution role: $execRoleArn"
} else {
    Write-Info "Execution role already exists: $execRoleArn"
}

# Task Role
$TASK_ROLE_NAME = "VQAEcsTaskRole"
$taskRoleArn = aws iam get-role --role-name $TASK_ROLE_NAME --query "Role.Arn" --output text 2>$null

if (-not $taskRoleArn -or $taskRoleArn -eq "None") {
    $taskRoleArn = aws iam create-role --role-name $TASK_ROLE_NAME `
        --assume-role-policy-document "file://${trustPolicyFile}" `
        --query "Role.Arn" --output text

    aws iam put-role-policy --role-name $TASK_ROLE_NAME `
        --policy-name VQABedrockS3Access `
        --policy-document "file://${taskPolicyFile}"

    aws iam attach-role-policy --role-name $TASK_ROLE_NAME `
        --policy-arn "arn:aws:iam::aws:policy/AmazonElasticFileSystemClientFullAccess"
    Write-OK "Created task role: $taskRoleArn"
} else {
    Write-Info "Task role already exists: $taskRoleArn"
}

aws iam put-role-policy --role-name $TASK_ROLE_NAME `
    --policy-name VQABedrockS3Access `
    --policy-document "file://${taskPolicyFile}"
aws iam attach-role-policy --role-name $TASK_ROLE_NAME `
    --policy-arn "arn:aws:iam::aws:policy/AmazonElasticFileSystemClientFullAccess" 2>$null

# -- STEP 3: Security Groups ---------------------------------------------------
Write-Step 3 "Creating security groups"

$albSgId = aws ec2 describe-security-groups `
    --filters "Name=group-name,Values=vqa-alb-sg" "Name=vpc-id,Values=${VPC_ID}" `
    --query "SecurityGroups[0].GroupId" --output text 2>$null

if (-not $albSgId -or $albSgId -eq "None") {
    $albSgId = aws ec2 create-security-group `
        --group-name "vqa-alb-sg" `
        --description "vQA ALB -- allow HTTP+HTTPS from internet" `
        --vpc-id $VPC_ID `
        --query "GroupId" --output text

    aws ec2 authorize-security-group-ingress --group-id $albSgId --protocol tcp --port 80 --cidr 0.0.0.0/0
    aws ec2 authorize-security-group-ingress --group-id $albSgId --protocol tcp --port 443 --cidr 0.0.0.0/0
    Write-OK "ALB SG: $albSgId"
} else {
    Write-Info "ALB SG already exists: $albSgId"
}

$taskSgId = aws ec2 describe-security-groups `
    --filters "Name=group-name,Values=vqa-task-sg" "Name=vpc-id,Values=${VPC_ID}" `
    --query "SecurityGroups[0].GroupId" --output text 2>$null

if (-not $taskSgId -or $taskSgId -eq "None") {
    $taskSgId = aws ec2 create-security-group `
        --group-name "vqa-task-sg" `
        --description "vQA ECS tasks -- allow from ALB SG only" `
        --vpc-id $VPC_ID `
        --query "GroupId" --output text

    aws ec2 authorize-security-group-ingress --group-id $taskSgId --protocol tcp --port 8000 --source-group $albSgId
    aws ec2 authorize-security-group-ingress --group-id $taskSgId --protocol tcp --port 3000 --source-group $albSgId
    Write-OK "Task SG: $taskSgId"
} else {
    Write-Info "Task SG already exists: $taskSgId"
}

$efsSgId = aws ec2 describe-security-groups `
    --filters "Name=group-name,Values=vqa-efs-sg" "Name=vpc-id,Values=${VPC_ID}" `
    --query "SecurityGroups[0].GroupId" --output text 2>$null

if (-not $efsSgId -or $efsSgId -eq "None") {
    $efsSgId = aws ec2 create-security-group `
        --group-name "vqa-efs-sg" `
        --description "vQA EFS -- allow NFS from ECS tasks" `
        --vpc-id $VPC_ID `
        --query "GroupId" --output text

    aws ec2 authorize-security-group-ingress --group-id $efsSgId --protocol tcp --port 2049 --source-group $taskSgId
    Write-OK "EFS SG: $efsSgId"
} else {
    Write-Info "EFS SG already exists: $efsSgId"
}

# -- STEP 4: EFS Filesystem ---------------------------------------------------
Write-Step 4 "Setting up EFS filesystem"
if (-not $SkipEfs) {
    $efsId = aws efs describe-file-systems --creation-token "vqa-data-v1" --query "FileSystems[0].FileSystemId" --output text 2>$null
    if (-not $efsId -or $efsId -eq "None") {
        $efsId = aws efs create-file-system `
            --creation-token "vqa-data-v1" `
            --performance-mode generalPurpose `
            --throughput-mode bursting `
            --encrypted `
            --tags "Key=Name,Value=vqa-data" "Key=Service,Value=vqa" `
            --query "FileSystemId" --output text
        Write-OK "EFS created: $efsId"
    } else {
        Write-Info "EFS already exists: $efsId"
    }

    # Wait for EFS to be available
    Write-Info "Waiting for EFS to become available..."
    while ($true) {
        $status = aws efs describe-file-systems --file-system-id $efsId --query "FileSystems[0].LifeCycleState" --output text
        if ($status -eq "available") { break }
        Write-Info "Current status: $status (waiting 10s...)"
        Start-Sleep -Seconds 10
    }

    # Create mount targets in each subnet
    foreach ($subnetId in $SUBNET_IDS) {
        $targetId = aws efs describe-mount-targets --file-system-id $efsId --query "MountTargets[?SubnetId=='$subnetId'].MountTargetId" --output text 2>$null
        if (-not $targetId -or $targetId -eq "None") {
            aws efs create-mount-target --file-system-id $efsId --subnet-id $subnetId --security-groups $efsSgId | Out-Null
            Write-OK "Created mount target in $subnetId"
        } else {
            Write-Info "Mount target already exists in $subnetId"
        }
    }
} else {
    Write-Info "Skipping EFS setup (-SkipEfs flag set)"
}

Write-Step "DONE" "Infrastructure (Part 1) is ready."
