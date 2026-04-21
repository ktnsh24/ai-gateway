# =============================================================================
# CloudWatch — Logging
# =============================================================================
# Centralized logging for ECS tasks. Retention set to 30 days for dev.
# =============================================================================

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/ecs/${local.prefix}"
  retention_in_days = 30
}
