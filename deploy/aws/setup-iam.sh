#!/usr/bin/env bash
# Creates the IAM roles required for ECS Fargate and GitHub Actions OIDC.
# Run once before first deploy: bash deploy/aws/setup-iam.sh
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
GITHUB_ORG="jndumu"
GITHUB_REPO="Enhanced-Multimodel-Rag-Hackerton"

echo "Setting up IAM for account ${AWS_ACCOUNT_ID} in ${AWS_REGION}"

# ── ECS Task Execution Role ───────────────────────────────────
echo "▶ Creating ecsTaskExecutionRole..."
aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' 2>/dev/null || echo "  (already exists)"

aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

aws iam put-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name SecretsManagerRead \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":[\"secretsmanager:GetSecretValue\"],
      \"Resource\":\"arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:doc-intel-rag/*\"
    }]
  }"
echo "  ✓ ecsTaskExecutionRole ready"

# ── ECS Task Role (app permissions) ──────────────────────────
echo "▶ Creating ecsTaskRole..."
aws iam create-role \
  --role-name ecsTaskRole \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' 2>/dev/null || echo "  (already exists)"

aws iam put-role-policy \
  --role-name ecsTaskRole \
  --policy-name AppPermissions \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":[\"logs:CreateLogGroup\",\"logs:CreateLogStream\",\"logs:PutLogEvents\"],
      \"Resource\":\"arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:log-group:/ecs/doc-intel-rag:*\"
    }]
  }"
echo "  ✓ ecsTaskRole ready"

# ── GitHub Actions OIDC Deploy Role ──────────────────────────
echo "▶ Creating GitHub Actions OIDC provider..."
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  2>/dev/null || echo "  (already exists)"

echo "▶ Creating GitHubActionsDeployRole..."
aws iam create-role \
  --role-name GitHubActionsDeployRole \
  --assume-role-policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Principal\":{\"Federated\":\"arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com\"},
      \"Action\":\"sts:AssumeRoleWithWebIdentity\",
      \"Condition\":{
        \"StringLike\":{\"token.actions.githubusercontent.com:sub\":\"repo:${GITHUB_ORG}/${GITHUB_REPO}:*\"},
        \"StringEquals\":{\"token.actions.githubusercontent.com:aud\":\"sts.amazonaws.com\"}
      }
    }]
  }" 2>/dev/null || echo "  (already exists)"

aws iam attach-role-policy \
  --role-name GitHubActionsDeployRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

aws iam put-role-policy \
  --role-name GitHubActionsDeployRole \
  --policy-name ECSDeployPolicy \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[
      {\"Effect\":\"Allow\",\"Action\":[\"ecs:*\",\"ecr:*\"],\"Resource\":\"*\"},
      {\"Effect\":\"Allow\",\"Action\":[\"iam:PassRole\"],
       \"Resource\":[
         \"arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole\",
         \"arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskRole\"
       ]}
    ]
  }"

DEPLOY_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/GitHubActionsDeployRole"
echo "  ✓ GitHubActionsDeployRole ready"
echo ""
echo "=== IAM Setup Complete ==="
echo ""
echo "Add this secret to GitHub repo → Settings → Secrets → Actions:"
echo "  AWS_DEPLOY_ROLE_ARN = ${DEPLOY_ROLE_ARN}"
