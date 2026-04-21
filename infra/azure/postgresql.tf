# =============================================================================
# Azure Database for PostgreSQL — Usage & Cost Tracking
# =============================================================================
# Stores LLM usage logs, cost tracking, and API key management.
# =============================================================================

resource "azurerm_postgresql_flexible_server" "gateway" {
  name                   = "${local.prefix}-pg"
  resource_group_name    = azurerm_resource_group.gateway.name
  location               = azurerm_resource_group.gateway.location
  version                = "16"
  administrator_login    = "gateway"
  administrator_password = "GatewayDev2026!" # Use Key Vault in production
  sku_name               = "B_Standard_B1ms"
  storage_mb             = 32768
  zone                   = "1"
}

resource "azurerm_postgresql_flexible_server_database" "gateway" {
  name      = "ai_gateway"
  server_id = azurerm_postgresql_flexible_server.gateway.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
