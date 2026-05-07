#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — Create Terraform remote state backend resources
#
# Creates (idempotently):
#   - S3 bucket for Terraform state with versioning, encryption, public-access block
#   - DynamoDB table for state locking
#
# Usage:
#   chmod +x scripts/bootstrap.sh
#   AWS_PROFILE=my-profile ./scripts/bootstrap.sh
#   # or set AWS_DEFAULT_REGION before running
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
BUCKET_NAME="doc-intel-rag-tfstate-431445718054"
DYNAMODB_TABLE="doc-intel-rag-tfstate-lock"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROJECT="doc-intel-rag"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

log()    { echo -e "${CYAN}[bootstrap]${NC} $*"; }
ok()     { echo -e "${GREEN}[OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if ! command -v aws &>/dev/null; then
  error "AWS CLI not found. Install it first: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
  exit 1
fi

CALLER_IDENTITY=$(aws sts get-caller-identity --output json 2>&1) || {
  error "Failed to authenticate with AWS. Check your credentials or AWS_PROFILE."
  exit 1
}

ACCOUNT_ID=$(echo "$CALLER_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])" 2>/dev/null \
  || echo "$CALLER_IDENTITY" | grep -o '"Account": *"[^"]*"' | grep -o '[0-9]*')

log "Authenticated as account: ${ACCOUNT_ID} in region: ${REGION}"

# ── S3 Bucket ─────────────────────────────────────────────────────────────────
log "Checking S3 bucket: ${BUCKET_NAME} ..."

if aws s3api head-bucket --bucket "${BUCKET_NAME}" --region "${REGION}" 2>/dev/null; then
  ok "S3 bucket '${BUCKET_NAME}' already exists — skipping creation."
else
  log "Creating S3 bucket '${BUCKET_NAME}' in region '${REGION}' ..."

  if [[ "${REGION}" == "us-east-1" ]]; then
    # us-east-1 does NOT accept a LocationConstraint — it's the default
    aws s3api create-bucket \
      --bucket "${BUCKET_NAME}" \
      --region "${REGION}"
  else
    aws s3api create-bucket \
      --bucket "${BUCKET_NAME}" \
      --region "${REGION}" \
      --create-bucket-configuration LocationConstraint="${REGION}"
  fi

  ok "Bucket created."
fi

# Enable versioning
log "Enabling versioning on bucket ..."
aws s3api put-bucket-versioning \
  --bucket "${BUCKET_NAME}" \
  --versioning-configuration Status=Enabled
ok "Versioning enabled."

# Enable server-side encryption (AES-256)
log "Enabling server-side encryption ..."
aws s3api put-bucket-encryption \
  --bucket "${BUCKET_NAME}" \
  --server-side-encryption-configuration '{
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        },
        "BucketKeyEnabled": true
      }
    ]
  }'
ok "Encryption enabled."

# Block all public access
log "Blocking public access on bucket ..."
aws s3api put-public-access-block \
  --bucket "${BUCKET_NAME}" \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'
ok "Public access blocked."

# Apply bucket lifecycle rule: keep only the last 90 non-current state versions
log "Applying lifecycle rule for old state versions ..."
aws s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET_NAME}" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "expire-old-tfstate-versions",
        "Status": "Enabled",
        "Filter": { "Prefix": "" },
        "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
      }
    ]
  }'
ok "Lifecycle rule applied."

# Apply a bucket tag
aws s3api put-bucket-tagging \
  --bucket "${BUCKET_NAME}" \
  --tagging "TagSet=[{Key=Project,Value=${PROJECT}},{Key=ManagedBy,Value=Terraform},{Key=Purpose,Value=tfstate}]"

# ── DynamoDB Table ────────────────────────────────────────────────────────────
log "Checking DynamoDB table: ${DYNAMODB_TABLE} ..."

TABLE_STATUS=$(aws dynamodb describe-table \
  --table-name "${DYNAMODB_TABLE}" \
  --region "${REGION}" \
  --query "Table.TableStatus" \
  --output text 2>/dev/null || echo "NOT_FOUND")

if [[ "${TABLE_STATUS}" != "NOT_FOUND" ]]; then
  ok "DynamoDB table '${DYNAMODB_TABLE}' already exists (status: ${TABLE_STATUS}) — skipping creation."
else
  log "Creating DynamoDB table '${DYNAMODB_TABLE}' ..."

  aws dynamodb create-table \
    --table-name "${DYNAMODB_TABLE}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "${REGION}" \
    --tags \
      Key=Project,Value="${PROJECT}" \
      Key=ManagedBy,Value=Terraform \
      Key=Purpose,Value=tfstate-lock

  log "Waiting for table to become active ..."
  aws dynamodb wait table-exists \
    --table-name "${DYNAMODB_TABLE}" \
    --region "${REGION}"

  ok "DynamoDB table created and active."
fi

# Enable point-in-time recovery for the lock table
log "Enabling Point-in-Time Recovery on DynamoDB table ..."
aws dynamodb update-continuous-backups \
  --table-name "${DYNAMODB_TABLE}" \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region "${REGION}" >/dev/null
ok "PITR enabled."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Bootstrap complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  S3 bucket  : s3://${BUCKET_NAME}"
echo "  DynamoDB   : ${DYNAMODB_TABLE} (region: ${REGION})"
echo ""
echo "Next steps:"
echo ""
echo "  1. Create a terraform.tfvars file (do NOT commit it — it holds secrets):"
echo ""
echo "     cd terraform/"
echo "     cat > terraform.tfvars <<'EOF'"
echo "     mesh_api_key   = \"your-mesh-api-key\""
echo "     qdrant_url     = \"https://your-qdrant-cluster.qdrant.tech\""
echo "     qdrant_api_key = \"your-qdrant-api-key\""
echo "     cohere_api_key = \"your-cohere-api-key\""
echo "     tavily_api_key = \"your-tavily-api-key\""
echo "     jina_api_key   = \"your-jina-api-key\""
echo "     alarm_email    = \"your@email.com\""
echo "     EOF"
echo ""
echo "  2. Initialise Terraform:"
echo "     terraform init"
echo ""
echo "  3. Review the plan:"
echo "     terraform plan"
echo ""
echo "  4. Apply:"
echo "     terraform apply"
echo ""
