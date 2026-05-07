data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    sid     = "ECSTasksAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ── ECS Task Execution Role ──────────────────────────────────────────────────
# Used by the ECS agent to pull images and ship logs.

resource "aws_iam_role" "ecs_task_execution" {
  name               = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json

  tags = {
    Name = "ecsTaskExecutionRole"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Inline policy: allow the execution role to read secrets from Secrets Manager
data "aws_iam_policy_document" "secrets_access" {
  statement {
    sid    = "SecretsManagerReadAccess"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      "arn:aws:secretsmanager:*:${var.account_id}:secret:${var.project}/*",
    ]
  }
}

resource "aws_iam_role_policy" "secrets_access" {
  name   = "${var.project}-secrets-access"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.secrets_access.json
}

# ── ECS Task Role ────────────────────────────────────────────────────────────
# Granted to the application process itself. Grant only what the app needs.

resource "aws_iam_role" "ecs_task" {
  name               = "ecsTaskRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json

  tags = {
    Name = "ecsTaskRole"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Minimal permissions for the application container
data "aws_iam_policy_document" "ecs_task_permissions" {
  # Allow the app to read its own secrets at runtime (belt-and-suspenders)
  statement {
    sid    = "SecretsManagerRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.project}/*",
    ]
  }

  # Allow CloudWatch Logs write access for structured application logging
  statement {
    sid    = "CloudWatchLogsWrite"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/ecs/${var.project}:*",
    ]
  }
}

resource "aws_iam_role_policy" "ecs_task_permissions" {
  name   = "${var.project}-task-permissions"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task_permissions.json
}
