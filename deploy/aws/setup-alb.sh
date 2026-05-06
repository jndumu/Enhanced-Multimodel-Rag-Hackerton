#!/usr/bin/env bash
# Creates an Application Load Balancer for the ECS service.
# Run once after setup-iam.sh: bash deploy/aws/setup-alb.sh
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECS_CLUSTER="doc-intel-rag-cluster"
ECS_SERVICE="doc-intel-rag-service"
ALB_NAME="doc-intel-rag-alb"
TG_NAME="doc-intel-rag-tg"

echo "=== Setting up ALB for doc-intel-rag ==="

# Get default VPC
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=isDefault,Values=true" \
  --query 'Vpcs[0].VpcId' --output text --region "${AWS_REGION}")

SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=${VPC_ID}" \
  --query 'Subnets[*].SubnetId' \
  --output json --region "${AWS_REGION}" | tr -d '[]"' | tr ',' ' ')

echo "VPC     : ${VPC_ID}"
echo "Subnets : ${SUBNETS}"

# ── Security Group for ALB ────────────────────────────────────
echo "▶ Creating ALB security group..."
ALB_SG=$(aws ec2 create-security-group \
  --group-name "doc-intel-rag-alb-sg" \
  --description "doc-intel-rag ALB" \
  --vpc-id "${VPC_ID}" \
  --region "${AWS_REGION}" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=doc-intel-rag-alb-sg" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${AWS_REGION}")

aws ec2 authorize-security-group-ingress \
  --group-id "${ALB_SG}" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 \
  --region "${AWS_REGION}" 2>/dev/null || true

aws ec2 authorize-security-group-ingress \
  --group-id "${ALB_SG}" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 \
  --region "${AWS_REGION}" 2>/dev/null || true
echo "  ✓ ALB SG: ${ALB_SG}"

# ── Security Group for ECS tasks ─────────────────────────────
echo "▶ Creating ECS task security group..."
ECS_SG=$(aws ec2 create-security-group \
  --group-name "doc-intel-rag-ecs-sg" \
  --description "doc-intel-rag ECS tasks" \
  --vpc-id "${VPC_ID}" \
  --region "${AWS_REGION}" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=doc-intel-rag-ecs-sg" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${AWS_REGION}")

aws ec2 authorize-security-group-ingress \
  --group-id "${ECS_SG}" \
  --protocol tcp --port 8000 \
  --source-group "${ALB_SG}" \
  --region "${AWS_REGION}" 2>/dev/null || true
echo "  ✓ ECS SG: ${ECS_SG}"

# ── Create ALB ────────────────────────────────────────────────
echo "▶ Creating Application Load Balancer..."
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name "${ALB_NAME}" \
  --subnets ${SUBNETS} \
  --security-groups "${ALB_SG}" \
  --region "${AWS_REGION}" \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text 2>/dev/null || \
  aws elbv2 describe-load-balancers \
    --names "${ALB_NAME}" \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text --region "${AWS_REGION}")

ALB_DNS=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns "${ALB_ARN}" \
  --query 'LoadBalancers[0].DNSName' \
  --output text --region "${AWS_REGION}")
echo "  ✓ ALB: ${ALB_DNS}"

# ── Create Target Group ───────────────────────────────────────
echo "▶ Creating target group..."
TG_ARN=$(aws elbv2 create-target-group \
  --name "${TG_NAME}" \
  --protocol HTTP \
  --port 8000 \
  --vpc-id "${VPC_ID}" \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --region "${AWS_REGION}" \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text 2>/dev/null || \
  aws elbv2 describe-target-groups \
    --names "${TG_NAME}" \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text --region "${AWS_REGION}")
echo "  ✓ Target Group: ${TG_ARN}"

# ── Create Listener ───────────────────────────────────────────
echo "▶ Creating HTTP listener..."
aws elbv2 create-listener \
  --load-balancer-arn "${ALB_ARN}" \
  --protocol HTTP \
  --port 80 \
  --default-actions "Type=forward,TargetGroupArn=${TG_ARN}" \
  --region "${AWS_REGION}" > /dev/null 2>/dev/null || true
echo "  ✓ Listener on port 80"

# ── Update ECS service to use ALB ────────────────────────────
echo "▶ Updating ECS service with load balancer..."
SUBNET_LIST=$(echo "${SUBNETS}" | tr ' ' ',')
aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_LIST}],securityGroups=[${ECS_SG}],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=${TG_ARN},containerName=doc-intel-rag,containerPort=8000" \
  --region "${AWS_REGION}" > /dev/null 2>/dev/null || true

echo ""
echo "=== ALB Setup Complete ==="
echo "App URL  : http://${ALB_DNS}"
echo "API Docs : http://${ALB_DNS}/docs"
echo "Health   : http://${ALB_DNS}/health"
echo ""
echo "Add this to your hackathon submission as the deployed URL."
