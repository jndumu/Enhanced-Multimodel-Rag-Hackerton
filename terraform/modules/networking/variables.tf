variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "availability_zones" {
  description = "List of availability zones to spread subnets across"
  type        = list(string)
}

variable "container_port" {
  description = "Port the application container listens on (used in ECS security group ingress rule)"
  type        = number
}
