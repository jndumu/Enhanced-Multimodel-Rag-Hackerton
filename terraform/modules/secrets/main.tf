locals {
  # Map of secret name → plaintext value, used with for_each
  secret_values = {
    MESH_API_KEY   = var.mesh_api_key
    QDRANT_URL     = var.qdrant_url
    QDRANT_API_KEY = var.qdrant_api_key
    COHERE_API_KEY = var.cohere_api_key
    TAVILY_API_KEY = var.tavily_api_key
    JINA_API_KEY   = var.jina_api_key
  }
}

# ── Secrets Manager secrets ──────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "secrets" {
  for_each = local.secret_values

  # Namespace: project/ENV_VAR_NAME  e.g. doc-intel-rag/MESH_API_KEY
  name        = "${var.project}/${each.key}"
  description = "Secret ${each.key} for the ${var.project} application (${var.environment})"

  # Keep 7-day recovery window so accidental deletes can be recovered
  recovery_window_in_days = 7

  tags = {
    Name        = "${var.project}/${each.key}"
    SecretScope = var.project
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "secrets" {
  for_each = local.secret_values

  secret_id     = aws_secretsmanager_secret.secrets[each.key].id
  secret_string = each.value

  lifecycle {
    # Prevent Terraform from re-writing secrets that have been rotated externally
    ignore_changes = [secret_string]
  }
}
