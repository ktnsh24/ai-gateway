# =============================================================================
# ECR — Container Registry
# =============================================================================
# Stores Docker images built by CI/CD for deployment to ECS Fargate.
# =============================================================================

resource "aws_ecr_repository" "gateway" {
  name                 = local.prefix
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Auto-delete untagged images after 14 days to save storage costs
resource "aws_ecr_lifecycle_policy" "gateway" {
  repository = aws_ecr_repository.gateway.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged images after 14 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 14
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
