output "log_group_name" {
  description = "Name of the CloudWatch log group for ECS container logs"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "log_group_arn" {
  description = "ARN of the CloudWatch log group"
  value       = aws_cloudwatch_log_group.ecs.arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS alarm topic (empty string if alarm_email not set)"
  value       = var.alarm_email != "" ? aws_sns_topic.alarms[0].arn : ""
}

output "dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}
