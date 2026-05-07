output "secret_arns" {
  description = "Map of secret names to their Secrets Manager ARNs"
  value = {
    MESH_API_KEY   = aws_secretsmanager_secret.secrets["MESH_API_KEY"].arn
    QDRANT_URL     = aws_secretsmanager_secret.secrets["QDRANT_URL"].arn
    QDRANT_API_KEY = aws_secretsmanager_secret.secrets["QDRANT_API_KEY"].arn
    COHERE_API_KEY = aws_secretsmanager_secret.secrets["COHERE_API_KEY"].arn
    TAVILY_API_KEY = aws_secretsmanager_secret.secrets["TAVILY_API_KEY"].arn
    JINA_API_KEY   = aws_secretsmanager_secret.secrets["JINA_API_KEY"].arn
  }
}
