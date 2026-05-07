variable "project" {
  description = "Project name used to prefix all resource names"
  type        = string
  default     = "doc-intel-rag"
}

variable "environment" {
  description = "Deployment environment (e.g. production, staging)"
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region where resources will be deployed"
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "AWS account ID used for constructing ARNs and ECR image URLs"
  type        = string
  default     = "431445718054"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones to deploy subnets into"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "container_port" {
  description = "Port the FastAPI container listens on"
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "Number of CPU units for the ECS Fargate task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "memory" {
  description = "Amount of memory in MiB for the ECS Fargate task"
  type        = number
  default     = 2048
}

variable "desired_count" {
  description = "Desired number of ECS service tasks to run"
  type        = number
  default     = 1
}

variable "min_capacity" {
  description = "Minimum number of ECS tasks for auto-scaling"
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Maximum number of ECS tasks for auto-scaling"
  type        = number
  default     = 5
}

variable "image_tag" {
  description = "Docker image tag to deploy from ECR"
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 30
}

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications. Leave empty to skip SNS subscription."
  type        = string
  default     = ""
}

# Secrets — marked sensitive so they never appear in plan output
variable "mesh_api_key" {
  description = "Mesh API key for the application"
  type        = string
  sensitive   = true
  default     = ""
}

variable "qdrant_url" {
  description = "Qdrant vector database URL"
  type        = string
  sensitive   = true
  default     = ""
}

variable "qdrant_api_key" {
  description = "Qdrant API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "cohere_api_key" {
  description = "Cohere API key for reranking and embeddings"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tavily_api_key" {
  description = "Tavily API key for web search"
  type        = string
  sensitive   = true
  default     = ""
}

variable "jina_api_key" {
  description = "Jina AI API key"
  type        = string
  sensitive   = true
  default     = ""
}
