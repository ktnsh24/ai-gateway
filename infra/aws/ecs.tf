# =============================================================================
# ECS Fargate — Gateway Application
# =============================================================================
# Runs the AI Gateway container on ECS Fargate with environment-specific config.
# =============================================================================

resource "aws_ecs_cluster" "gateway" {
  name = local.prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "gateway" {
  family                   = local.prefix
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "gateway"
      image     = "${aws_ecr_repository.gateway.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8100
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "CLOUD_PROVIDER", value = "aws" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
        { name = "DATABASE_URL", value = "postgresql+asyncpg://gateway:gateway-dev-password@${aws_db_instance.postgres.endpoint}/ai_gateway" },
        { name = "CACHE_ENABLED", value = "true" },
        { name = "RATE_LIMIT_ENABLED", value = "true" },
        { name = "COST_TRACKING_ENABLED", value = "true" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.gateway.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "gateway"
        }
      }
    }
  ])
}
