locals {
  name_prefix = "${var.project}-${var.environment}"
  account_id  = var.aws_account_id

  ecr_image_url = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project}:${var.image_tag}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
    Owner       = "Josephine Ndumu"
  }
}
