# =============================================================================
# Azure Cache for Redis — Caching & Rate Limiting
# =============================================================================
# Provides in-memory caching for LLM responses and sliding-window rate limiting.
# =============================================================================

resource "azurerm_redis_cache" "gateway" {
  name                = "${local.prefix}-redis"
  location            = azurerm_resource_group.gateway.location
  resource_group_name = azurerm_resource_group.gateway.name
  capacity            = 0
  family              = "C"
  sku_name            = "Basic"
  minimum_tls_version = "1.2"
}
