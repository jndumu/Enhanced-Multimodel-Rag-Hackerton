output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "alb_url" {
  description = "Full HTTP URL of the Application Load Balancer"
  value       = "http://${module.alb.alb_dns_name}"
}

output "swagger_url" {
  description = "URL to the FastAPI interactive docs (Swagger UI)"
  value       = "http://${module.alb.alb_dns_name}/docs"
}

output "health_url" {
  description = "URL to the application health check endpoint"
  value       = "http://${module.alb.alb_dns_name}/health"
}

output "ecr_repository_url" {
  description = "Full URL of the ECR repository"
  value       = module.ecr.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = module.ecs.service_name
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.networking.vpc_id
}

output "cloudwatch_log_group" {
  description = "Name of the CloudWatch log group for ECS container logs"
  value       = module.monitoring.log_group_name
}
