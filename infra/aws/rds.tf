# =============================================================================
# RDS PostgreSQL — Usage & Cost Tracking
# =============================================================================
# Stores LLM usage logs, cost tracking, and API key management.
# =============================================================================

resource "aws_db_instance" "postgres" {
  identifier             = "${local.prefix}-pg"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  db_name                = "ai_gateway"
  username               = "gateway"
  password               = var.db_password # Set via TF_VAR_db_password env var; rotate via Secrets Manager in production
  skip_final_snapshot    = true
  publicly_accessible    = false
  vpc_security_group_ids = [aws_security_group.gateway.id]
}
