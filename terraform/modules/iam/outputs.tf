output "execution_role_arn" {
  description = "ARN of the ECS task execution IAM role"
  value       = aws_iam_role.ecs_task_execution.arn
}

output "task_role_arn" {
  description = "ARN of the ECS task IAM role"
  value       = aws_iam_role.ecs_task.arn
}

output "execution_role_name" {
  description = "Name of the ECS task execution IAM role"
  value       = aws_iam_role.ecs_task_execution.name
}

output "task_role_name" {
  description = "Name of the ECS task IAM role"
  value       = aws_iam_role.ecs_task.name
}
