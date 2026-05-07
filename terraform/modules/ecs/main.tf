locals {
  name_prefix    = "${var.project}-${var.environment}"
  container_name = var.project
}

# ── ECS Cluster ───────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project}-cluster"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# ── Task Definition ───────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "main" {
  family                   = var.project
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = var.ecr_image_url
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      # Static configuration environment variables
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "APP_PORT", value = tostring(var.container_port) },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "WORKERS", value = "1" },
        { name = "MAX_UPLOAD_SIZE_MB", value = "50" },
        { name = "ENABLE_METRICS", value = "true" },
        { name = "CORS_ORIGINS", value = "*" },
        { name = "PROJECT_NAME", value = var.project },
      ]

      # Secrets injected from Secrets Manager at task startup
      secrets = [
        {
          name      = "MESH_API_KEY"
          valueFrom = var.secret_arns["MESH_API_KEY"]
        },
        {
          name      = "QDRANT_URL"
          valueFrom = var.secret_arns["QDRANT_URL"]
        },
        {
          name      = "QDRANT_API_KEY"
          valueFrom = var.secret_arns["QDRANT_API_KEY"]
        },
        {
          name      = "COHERE_API_KEY"
          valueFrom = var.secret_arns["COHERE_API_KEY"]
        },
        {
          name      = "TAVILY_API_KEY"
          valueFrom = var.secret_arns["TAVILY_API_KEY"]
        },
        {
          name      = "JINA_API_KEY"
          valueFrom = var.secret_arns["JINA_API_KEY"]
        },
      ]

      # Container-level health check (Fargate will mark the task unhealthy if this fails)
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      # Reasonable resource limits so one task cannot starve others
      ulimits = [
        {
          name      = "nofile"
          softLimit = 65536
          hardLimit = 65536
        }
      ]
    }
  ])

  tags = {
    Name = var.project
  }
}

# ── ECS Service ───────────────────────────────────────────────────────────────

resource "aws_ecs_service" "main" {
  name            = "${var.project}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.main.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Keep 100% healthy during deployments; allow up to 200% surge capacity
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Wait for the new tasks to pass the health check before marking the deployment done
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = local.container_name
    container_port   = var.container_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Ignore task_definition changes so CI/CD pipelines can deploy new images
  # without Terraform reverting them.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = {
    Name = "${var.project}-service"
  }
}

# ── Auto Scaling ──────────────────────────────────────────────────────────────

resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.main.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Scale out when average CPU exceeds 70%
resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name_prefix}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Scale out when average memory exceeds 80%
resource "aws_appautoscaling_policy" "memory" {
  name               = "${local.name_prefix}-memory-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 80.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
