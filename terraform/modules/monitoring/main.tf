locals {
  name_prefix  = "${var.project}-${var.environment}"
  alarm_prefix = "${var.project}-${var.environment}"
  # Create SNS resources only when an alarm email is provided
  create_sns = var.alarm_email != ""
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "ecs" {
  name              = var.log_group_name
  retention_in_days = var.log_retention_days

  tags = {
    Name = var.log_group_name
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ── SNS Topic for Alarm Notifications ────────────────────────────────────────

resource "aws_sns_topic" "alarms" {
  count = local.create_sns ? 1 : 0
  name  = "${local.name_prefix}-alarms"

  tags = {
    Name = "${local.name_prefix}-alarms"
  }
}

resource "aws_sns_topic_subscription" "email" {
  count     = local.create_sns ? 1 : 0
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ── CloudWatch Alarms ─────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "${local.alarm_prefix}-cpu-high"
  alarm_description   = "ECS service CPU utilization exceeded 85% for 5 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300 # 5 minutes
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  alarm_actions = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []
  ok_actions    = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []

  tags = {
    Name = "${local.alarm_prefix}-cpu-high"
  }
}

resource "aws_cloudwatch_metric_alarm" "memory_high" {
  alarm_name          = "${local.alarm_prefix}-memory-high"
  alarm_description   = "ECS service memory utilization exceeded 85% for 5 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  alarm_actions = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []
  ok_actions    = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []

  tags = {
    Name = "${local.alarm_prefix}-memory-high"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  alarm_name          = "${local.alarm_prefix}-alb-5xx"
  alarm_description   = "ALB returned more than 10 HTTP 5xx errors in 5 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_actions = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []
  ok_actions    = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []

  tags = {
    Name = "${local.alarm_prefix}-alb-5xx"
  }
}

resource "aws_cloudwatch_metric_alarm" "healthy_hosts_low" {
  alarm_name          = "${local.alarm_prefix}-healthy-hosts"
  alarm_description   = "ALB target group has fewer than 1 healthy host"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "breaching" # No data = no healthy hosts = alarm

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.tg_arn_suffix
  }

  alarm_actions = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []
  ok_actions    = local.create_sns ? [aws_sns_topic.alarms[0].arn] : []

  tags = {
    Name = "${local.alarm_prefix}-healthy-hosts"
  }
}

# ── CloudWatch Dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name_prefix

  dashboard_body = jsonencode({
    widgets = [
      # Widget 1: CPU Utilization
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU Utilization"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name, { label = "CPU %" }]
          ]
          view    = "timeSeries"
          stacked = false
          period  = 60
          stat    = "Average"
          yAxis = {
            left = { min = 0, max = 100, label = "Percent" }
          }
          annotations = {
            horizontal = [{ value = 85, label = "Alarm threshold", color = "#ff0000" }]
          }
        }
      },
      # Widget 2: Memory Utilization
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS Memory Utilization"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name, { label = "Memory %" }]
          ]
          view    = "timeSeries"
          stacked = false
          period  = 60
          stat    = "Average"
          yAxis = {
            left = { min = 0, max = 100, label = "Percent" }
          }
          annotations = {
            horizontal = [{ value = 85, label = "Alarm threshold", color = "#ff0000" }]
          }
        }
      },
      # Widget 3: ALB Request Count
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ALB Request Count"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, { label = "Requests", color = "#2ca02c" }]
          ]
          view    = "timeSeries"
          stacked = false
          period  = 60
          stat    = "Sum"
          yAxis = {
            left = { min = 0, label = "Count" }
          }
        }
      },
      # Widget 4: ALB 5xx Count
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ALB 5xx Errors"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { label = "5xx Errors", color = "#d62728" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, { label = "Target 5xx", color = "#ff7f0e" }]
          ]
          view    = "timeSeries"
          stacked = false
          period  = 60
          stat    = "Sum"
          yAxis = {
            left = { min = 0, label = "Count" }
          }
          annotations = {
            horizontal = [{ value = 10, label = "Alarm threshold", color = "#ff0000" }]
          }
        }
      }
    ]
  })
}
