# =============================================================================
# Terraform & Provider Configuration
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment for remote state (recommended for team work):
  # backend "s3" {
  #   bucket         = "ai-gateway-terraform-state"
  #   key            = "aws/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "ai-gateway-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project     = var.app_name
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
