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

variable "ecr_image_url" {
  description = "Full ECR image URL including tag (account.dkr.ecr.region.amazonaws.com/repo:tag)"
  type        = string
}

variable "container_port" {
  description = "Port the application container listens on"
  type        = number
}

variable "cpu" {
  description = "CPU units for the Fargate task (1024 = 1 vCPU)"
  type        = number
}

variable "memory" {
  description = "Memory in MiB for the Fargate task"
  type        = number
}

variable "desired_count" {
  description = "Desired number of running ECS tasks"
  type        = number
}

variable "min_capacity" {
  description = "Minimum number of tasks for auto-scaling"
  type        = number
}

variable "max_capacity" {
  description = "Maximum number of tasks for auto-scaling"
  type        = number
}

variable "execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  type        = string
}

variable "task_role_arn" {
  description = "ARN of the ECS task IAM role"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS task placement"
  type        = list(string)
}

variable "ecs_sg_id" {
  description = "Security group ID for ECS tasks"
  type        = string
}

variable "target_group_arn" {
  description = "ARN of the ALB target group"
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group name for container logs"
  type        = string
}

variable "secret_arns" {
  description = "Map of secret names to ARNs from Secrets Manager"
  type        = map(string)
}
