variable "project" {
  description = "Project name — used to namespace secrets under project/*"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "mesh_api_key" {
  description = "Mesh API key"
  type        = string
  sensitive   = true
}

variable "qdrant_url" {
  description = "Qdrant vector database URL"
  type        = string
  sensitive   = true
}

variable "qdrant_api_key" {
  description = "Qdrant API key"
  type        = string
  sensitive   = true
}

variable "cohere_api_key" {
  description = "Cohere API key"
  type        = string
  sensitive   = true
}

variable "tavily_api_key" {
  description = "Tavily API key"
  type        = string
  sensitive   = true
}

variable "jina_api_key" {
  description = "Jina AI API key"
  type        = string
  sensitive   = true
}
