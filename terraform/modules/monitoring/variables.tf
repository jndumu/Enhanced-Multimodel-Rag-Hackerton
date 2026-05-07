variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
}

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications. Leave empty to skip SNS subscription."
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group name to create. Passed in from root module to avoid circular deps."
  type        = string
}

variable "ecs_cluster_name" {
  description = "Name of the ECS cluster (used in CloudWatch metric dimensions)"
  type        = string
}

variable "ecs_service_name" {
  description = "Name of the ECS service (used in CloudWatch metric dimensions)"
  type        = string
}

variable "alb_arn_suffix" {
  description = "ARN suffix of the ALB (used in CloudWatch metric dimensions)"
  type        = string
}

variable "tg_arn_suffix" {
  description = "ARN suffix of the ALB target group (used in CloudWatch metric dimensions)"
  type        = string
}
