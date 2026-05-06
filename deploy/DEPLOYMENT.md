# doc-intel-rag — ECS Fargate Deployment Guide

## Prerequisites Checklist

Before starting, confirm you have:

- [ ] AWS account with admin access
- [ ] AWS CLI installed (`aws --version`)
- [ ] Docker Desktop running (`docker info`)
- [ ] Git repo pushed to GitHub (`git log --oneline -1`)
- [ ] `.env` file with all API keys filled in

---

## Phase 1 — AWS CLI Configuration

### Step 1.1 — Create AWS Access Keys

1. Log into **console.aws.amazon.com**
2. Click your username (top right) → **Security credentials**
3. Scroll to **Access keys** → **Create access key**
4. Select **Command Line Interface (CLI)** → Next → Create
5. **Save the Access Key ID and Secret Access Key** — you won't see the secret again

### Step 1.2 — Configure AWS CLI

Run in terminal:
```bash
aws configure
```

Enter:
```
AWS Access Key ID:     AKIA...your key...
AWS Secret Access Key: your secret key
Default region name:   us-east-1
Default output format: json
```

### Step 1.3 — Verify

```bash
aws sts get-caller-identity
```

Expected output:
```json
{
    "UserId": "AIDA...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/yourname"
}
```

---

## Phase 2 — IAM Setup (Run Once)

### Step 2.1 — Run the IAM setup script

```bash
cd doc-intel-rag
export AWS_REGION=us-east-1
bash deploy/aws/setup-iam.sh
```

This creates:
- `ecsTaskExecutionRole` — allows ECS to pull images and read secrets
- `ecsTaskRole` — allows the app to write CloudWatch logs
- `GitHubActionsDeployRole` — allows GitHub Actions to deploy via OIDC (no static keys)

### Step 2.2 — Copy the deploy role ARN

The script prints something like:
```
AWS_DEPLOY_ROLE_ARN = arn:aws:iam::123456789012:role/GitHubActionsDeployRole
```

### Step 2.3 — Add secret to GitHub

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `AWS_DEPLOY_ROLE_ARN`
4. Value: paste the ARN from Step 2.2
5. Click **Add secret**

---

## Phase 3 — Store API Keys in AWS Secrets Manager

The deploy script reads from your `.env` and stores secrets automatically.
But you can also store them manually:

```bash
export AWS_REGION=us-east-1

# Store each secret
aws secretsmanager create-secret \
  --name doc-intel-rag/MESH_API_KEY \
  --secret-string "your-mesh-api-key"

aws secretsmanager create-secret \
  --name doc-intel-rag/QDRANT_URL \
  --secret-string "https://your-cluster.qdrant.io"

aws secretsmanager create-secret \
  --name doc-intel-rag/QDRANT_API_KEY \
  --secret-string "your-qdrant-api-key"

aws secretsmanager create-secret \
  --name doc-intel-rag/REDIS_URL \
  --secret-string "redis://localhost:6379"

aws secretsmanager create-secret \
  --name doc-intel-rag/COHERE_API_KEY \
  --secret-string "your-cohere-api-key"

aws secretsmanager create-secret \
  --name doc-intel-rag/TAVILY_API_KEY \
  --secret-string "your-tavily-api-key"
```

Verify secrets exist:
```bash
aws secretsmanager list-secrets --query 'SecretList[?contains(Name,`doc-intel-rag`)].Name'
```

---

## Phase 4 — Build & Deploy to ECS

### Step 4.1 — Run the deploy script

```bash
cd doc-intel-rag
export AWS_REGION=us-east-1
bash deploy/aws/deploy.sh
```

What this does automatically:
1. Creates ECR repository `doc-intel-rag`
2. Builds Docker image from `docker/Dockerfile`
3. Pushes image to ECR with your git commit SHA as tag
4. Stores your `.env` secrets in Secrets Manager
5. Creates ECS cluster `doc-intel-rag-cluster`
6. Registers task definition (1 vCPU, 2GB RAM)
7. Creates ECS service with 1 running task
8. Waits for the service to stabilise
9. Prints the public IP

Expected output:
```
=== doc-intel-rag ECS Fargate Deploy ===
Account : 123456789012
Region  : us-east-1
Tag     : a1b2c3d

▶ Step 1: Ensuring ECR repository...
  ✓ ECR: 123456789012.dkr.ecr.us-east-1.amazonaws.com/doc-intel-rag
▶ Step 2: Building and pushing Docker image...
  ✓ Image pushed
▶ Step 3: Storing secrets in Secrets Manager...
▶ Step 4: Ensuring ECS cluster...
▶ Step 5: Registering task definition...
▶ Step 6: Deploying ECS service...
▶ Step 7: Waiting for service to stabilise...
  ✓ Service stable

=== Deployment Complete ===
App URL  : http://54.x.x.x:8000
API Docs : http://54.x.x.x:8000/docs
Health   : http://54.x.x.x:8000/health
```

---

## Phase 5 — Add Application Load Balancer (Clean Public URL)

Without an ALB the app is accessible directly by task IP, which changes on restart.
An ALB gives you a stable DNS name.

### Step 5.1 — Run the ALB setup script

```bash
bash deploy/aws/setup-alb.sh
```

This creates:
- ALB security group (allows 80/443 from internet)
- ECS task security group (allows 8000 from ALB only)
- Application Load Balancer with DNS name
- Target group pointing to ECS tasks on port 8000
- HTTP listener on port 80
- Updates ECS service network config

Expected output:
```
=== ALB Setup Complete ===
App URL  : http://doc-intel-rag-alb-123456789.us-east-1.elb.amazonaws.com
API Docs : http://doc-intel-rag-alb-123456789.us-east-1.elb.amazonaws.com/docs
Health   : http://doc-intel-rag-alb-123456789.us-east-1.elb.amazonaws.com/health
```

This is your permanent deployed app URL.

---

## Phase 6 — GitHub Actions CI/CD (Auto-deploy on Push)

Every push to `main` automatically:
1. Runs unit tests
2. Builds and pushes new Docker image to ECR
3. Deploys new task definition to ECS
4. Waits for rollout to complete

### Step 6.1 — Get a PAT with workflow scope

Your current PAT needs the `workflow` scope:
1. GitHub → Settings → Developer settings → **Tokens (classic)**
2. **Generate new token (classic)**
3. Check `repo` ✅ and `workflow` ✅
4. Copy token

### Step 6.2 — Update remote and push

```bash
git remote set-url origin https://jndumu:<NEW_TOKEN>@github.com/jndumu/Enhanced-Multimodel-Rag-Hackerton.git
git push origin main
```

### Step 6.3 — Verify workflow runs

Go to your GitHub repo → **Actions** tab → you should see the workflow running.

---

## Phase 7 — Verify Deployment

### Health check
```bash
curl http://YOUR-ALB-URL/health
```

Expected:
```json
{
  "status": "ok",
  "components": {
    "qdrant": {"status": "ok", "latency_ms": 45.2},
    "redis":  {"status": "ok", "latency_ms": 1.1},
    "mesh_api": {"status": "ok", "latency_ms": 210.0}
  }
}
```

### Ingest a document
```bash
curl -X POST http://YOUR-ALB-URL/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://arxiv.org/pdf/1706.03762", "enrich": true}'
```

### Ask a question
```bash
curl -X POST http://YOUR-ALB-URL/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the attention mechanism?", "streaming": false}'
```

### Open interactive API docs
```
http://YOUR-ALB-URL/docs
```

---

## Monitoring & Logs

### View ECS logs in CloudWatch
```bash
aws logs tail /ecs/doc-intel-rag --follow --region us-east-1
```

### Check ECS service status
```bash
aws ecs describe-services \
  --cluster doc-intel-rag-cluster \
  --services doc-intel-rag-service \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount}' \
  --region us-east-1
```

### View Prometheus metrics
```
http://YOUR-ALB-URL/metrics
```

---

## Tear Down (if needed)

```bash
# Stop ECS service
aws ecs update-service --cluster doc-intel-rag-cluster \
  --service doc-intel-rag-service --desired-count 0 --region us-east-1

# Delete service
aws ecs delete-service --cluster doc-intel-rag-cluster \
  --service doc-intel-rag-service --force --region us-east-1

# Delete cluster
aws ecs delete-cluster --cluster doc-intel-rag-cluster --region us-east-1

# Delete ECR images
aws ecr delete-repository --repository-name doc-intel-rag --force --region us-east-1
```

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| Task keeps stopping | Out of memory | Increase task memory to 4096 in task-definition.json |
| Health check failing | App not starting | Check CloudWatch logs: `aws logs tail /ecs/doc-intel-rag` |
| Secrets not found | Wrong ARN region | Ensure AWS_REGION matches where secrets were created |
| 403 on API calls | No API key set | Add `API_KEYS` env var or leave empty for open access |
| Qdrant timeout | Cloud cluster URL wrong | Verify QDRANT_URL in Secrets Manager |
| Image pull error | ECR login expired | Re-run `aws ecr get-login-password` step |

---

## Deployment Summary

| Phase | Script / Command | Duration |
|---|---|---|
| 1. AWS CLI setup | `aws configure` | 2 min |
| 2. IAM setup | `bash deploy/aws/setup-iam.sh` | 1 min |
| 3. Secrets storage | automatic in deploy.sh | 30 sec |
| 4. ECS deploy | `bash deploy/aws/deploy.sh` | 8-12 min |
| 5. ALB setup | `bash deploy/aws/setup-alb.sh` | 2 min |
| 6. CI/CD | push to main → auto | ongoing |

**Total first-time setup: ~15 minutes**
