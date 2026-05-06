#!/usr/bin/env bash
# ============================================================
#  doc-intel-rag — ECS Fargate deployment script
#  Usage: ./deploy.sh [--region us-east-1] [--env prod]
# ============================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="doc-intel-rag"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
ECS_CLUSTER="doc-intel-rag-cluster"
ECS_SERVICE="doc-intel-rag-service"
TASK_FAMILY="doc-intel-rag"
IMAGE_TAG="${GITHUB_SHA:-$(git rev-parse --short HEAD)}"

echo "=== doc-intel-rag ECS Fargate Deploy ==="
echo "Account : ${AWS_ACCOUNT_ID}"
echo "Region  : ${AWS_REGION}"
echo "Tag     : ${IMAGE_TAG}"
echo ""

# ── Step 1: Create ECR repository (idempotent) ────────────────
echo "▶ Step 1: Ensuring ECR repository..."
aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${AWS_REGION}" \
  > /dev/null 2>&1 || \
  aws ecr create-repository \
    --repository-name "${ECR_REPO}" \
    --region "${AWS_REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --output text > /dev/null
echo "  ✓ ECR: ${ECR_URI}"

# ── Step 2: Build and push Docker image ───────────────────────
echo "▶ Step 2: Building and pushing Docker image..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build \
  --file "${REPO_ROOT}/docker/Dockerfile" \
  --tag "${ECR_URI}:${IMAGE_TAG}" \
  --tag "${ECR_URI}:latest" \
  "${REPO_ROOT}"

docker push "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:latest"
echo "  ✓ Image pushed: ${ECR_URI}:${IMAGE_TAG}"

# ── Step 3: Store secrets in AWS Secrets Manager ──────────────
echo "▶ Step 3: Storing secrets in Secrets Manager..."

store_secret() {
  local name="$1"
  local value="$2"
  local arn="arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:doc-intel-rag/${name}"
  aws secretsmanager describe-secret --secret-id "doc-intel-rag/${name}" \
    --region "${AWS_REGION}" > /dev/null 2>&1 && \
    aws secretsmanager put-secret-value \
      --secret-id "doc-intel-rag/${name}" \
      --secret-string "${value}" \
      --region "${AWS_REGION}" > /dev/null || \
    aws secretsmanager create-secret \
      --name "doc-intel-rag/${name}" \
      --secret-string "${value}" \
      --region "${AWS_REGION}" > /dev/null
  echo "  ✓ Secret stored: doc-intel-rag/${name}"
}

# Load from .env if it exists
if [[ -f "${REPO_ROOT}/.env" ]]; then
  source <(grep -v '^#' "${REPO_ROOT}/.env" | grep -v '^$' | sed 's/ #.*//')
fi

store_secret "MESH_API_KEY"    "${MESH_API_KEY:-}"
store_secret "QDRANT_URL"      "${QDRANT_URL:-}"
store_secret "QDRANT_API_KEY"  "${QDRANT_API_KEY:-}"
store_secret "REDIS_URL"       "${REDIS_URL:-redis://localhost:6379}"
store_secret "COHERE_API_KEY"  "${COHERE_API_KEY:-}"
store_secret "TAVILY_API_KEY"  "${TAVILY_API_KEY:-}"

# ── Step 4: Create ECS cluster (idempotent) ───────────────────
echo "▶ Step 4: Ensuring ECS cluster..."
aws ecs describe-clusters --clusters "${ECS_CLUSTER}" \
  --region "${AWS_REGION}" --query 'clusters[0].status' --output text \
  | grep -q "ACTIVE" || \
  aws ecs create-cluster \
    --cluster-name "${ECS_CLUSTER}" \
    --capacity-providers FARGATE FARGATE_SPOT \
    --region "${AWS_REGION}" > /dev/null
echo "  ✓ Cluster: ${ECS_CLUSTER}"

# ── Step 5: Register task definition ─────────────────────────
echo "▶ Step 5: Registering task definition..."
TASK_DEF=$(cat "${SCRIPT_DIR}/task-definition.json" | \
  sed "s|ACCOUNT_ID|${AWS_ACCOUNT_ID}|g" | \
  sed "s|AWS_REGION|${AWS_REGION}|g" | \
  sed "s|:latest|:${IMAGE_TAG}|g")

TASK_ARN=$(aws ecs register-task-definition \
  --cli-input-json "${TASK_DEF}" \
  --region "${AWS_REGION}" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)
echo "  ✓ Task definition: ${TASK_ARN}"

# ── Step 6: Create or update ECS service ─────────────────────
echo "▶ Step 6: Deploying ECS service..."

SERVICE_EXISTS=$(aws ecs describe-services \
  --cluster "${ECS_CLUSTER}" \
  --services "${ECS_SERVICE}" \
  --region "${AWS_REGION}" \
  --query 'services[0].status' \
  --output text 2>/dev/null || echo "MISSING")

if [[ "${SERVICE_EXISTS}" == "ACTIVE" ]]; then
  aws ecs update-service \
    --cluster "${ECS_CLUSTER}" \
    --service "${ECS_SERVICE}" \
    --task-definition "${TASK_ARN}" \
    --force-new-deployment \
    --region "${AWS_REGION}" > /dev/null
  echo "  ✓ Service updated: ${ECS_SERVICE}"
else
  # Get default VPC subnets and security group
  VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
    --query 'Vpcs[0].VpcId' --output text --region "${AWS_REGION}")
  SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" \
    --query 'Subnets[*].SubnetId' \
    --output text --region "${AWS_REGION}" | tr '\t' ',')
  SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=default" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${AWS_REGION}")

  aws ecs create-service \
    --cluster "${ECS_CLUSTER}" \
    --service-name "${ECS_SERVICE}" \
    --task-definition "${TASK_ARN}" \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
    --region "${AWS_REGION}" > /dev/null
  echo "  ✓ Service created: ${ECS_SERVICE}"
fi

# ── Step 7: Wait for deployment to stabilise ─────────────────
echo "▶ Step 7: Waiting for service to stabilise (up to 5 min)..."
aws ecs wait services-stable \
  --cluster "${ECS_CLUSTER}" \
  --services "${ECS_SERVICE}" \
  --region "${AWS_REGION}"
echo "  ✓ Service stable"

# ── Done ──────────────────────────────────────────────────────
PUBLIC_IP=$(aws ecs list-tasks \
  --cluster "${ECS_CLUSTER}" --service-name "${ECS_SERVICE}" \
  --region "${AWS_REGION}" --query 'taskArns[0]' --output text | \
  xargs -I{} aws ecs describe-tasks --cluster "${ECS_CLUSTER}" \
    --tasks {} --region "${AWS_REGION}" \
    --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
    --output text | \
  xargs -I{} aws ec2 describe-network-interfaces \
    --network-interface-ids {} --region "${AWS_REGION}" \
    --query 'NetworkInterfaces[0].Association.PublicIp' --output text 2>/dev/null || echo "check-console")

echo ""
echo "=== Deployment Complete ==="
echo "App URL  : http://${PUBLIC_IP}:8000"
echo "API Docs : http://${PUBLIC_IP}:8000/docs"
echo "Health   : http://${PUBLIC_IP}:8000/health"
