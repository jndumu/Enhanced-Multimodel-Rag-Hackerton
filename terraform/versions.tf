terraform {
  required_version = ">= 1.2"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "doc-intel-rag-tfstate-431445718054"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "doc-intel-rag-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
