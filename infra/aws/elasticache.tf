# =============================================================================
# ElastiCache Redis — Caching & Rate Limiting
# =============================================================================
# Provides in-memory caching for LLM responses and sliding-window rate limiting.
# =============================================================================

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${local.prefix}-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  security_group_ids   = [aws_security_group.gateway.id]
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.prefix}-redis-subnet"
  subnet_ids = data.aws_subnets.default.ids
}
