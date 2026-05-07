output "vpc_id" {
  description = "ID of the VPC used for deployment"
  value       = data.aws_vpc.default.id
}

output "public_subnet_ids" {
  description = "Subnet IDs for ALB (default VPC subnets)"
  value       = data.aws_subnets.default.ids
}

output "private_subnet_ids" {
  description = "Subnet IDs for ECS tasks (default VPC subnets)"
  value       = data.aws_subnets.default.ids
}

output "alb_sg_id" {
  description = "Security group ID for the Application Load Balancer"
  value       = aws_security_group.alb.id
}

output "ecs_sg_id" {
  description = "Security group ID for ECS Fargate tasks"
  value       = aws_security_group.ecs.id
}
