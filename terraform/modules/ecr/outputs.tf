output "repository_url" {
  description = "Full URL of the ECR repository (account.dkr.ecr.region.amazonaws.com/name)"
  value       = aws_ecr_repository.main.repository_url
}

output "repository_arn" {
  description = "ARN of the ECR repository"
  value       = aws_ecr_repository.main.arn
}

output "registry_id" {
  description = "Registry ID (AWS account ID) that owns the repository"
  value       = aws_ecr_repository.main.registry_id
}
