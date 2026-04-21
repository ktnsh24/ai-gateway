# =============================================================================
# Container App — Gateway Application
# =============================================================================
# Runs the AI Gateway container on Azure Container Apps.
# =============================================================================

resource "azurerm_container_app_environment" "gateway" {
  name                = "${local.prefix}-env"
  location            = azurerm_resource_group.gateway.location
  resource_group_name = azurerm_resource_group.gateway.name
}

resource "azurerm_container_app" "gateway" {
  name                         = local.prefix
  container_app_environment_id = azurerm_container_app_environment.gateway.id
  resource_group_name          = azurerm_resource_group.gateway.name
  revision_mode                = "Single"

  template {
    container {
      name   = "gateway"
      image  = "ghcr.io/ketan-sahu/ai-gateway:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "CLOUD_PROVIDER"
        value = "azure"
      }
      env {
        name  = "REDIS_URL"
        value = "rediss://:${azurerm_redis_cache.gateway.primary_access_key}@${azurerm_redis_cache.gateway.hostname}:${azurerm_redis_cache.gateway.ssl_port}/0"
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://gateway:GatewayDev2026!@${azurerm_postgresql_flexible_server.gateway.fqdn}:5432/ai_gateway"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8100
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}
