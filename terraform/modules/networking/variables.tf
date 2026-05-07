variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "container_port" {
  description = "Port the application container listens on"
  type        = number
}
