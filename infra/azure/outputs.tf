# =============================================================================
# Outputs
# =============================================================================

output "container_app_url" {
  description = "Public URL of the Container App"
  value       = "https://${azurerm_container_app.gateway.ingress[0].fqdn}"
}

output "redis_hostname" {
  description = "Azure Redis Cache hostname"
  value       = azurerm_redis_cache.gateway.hostname
}

output "postgres_fqdn" {
  description = "Azure PostgreSQL Flexible Server FQDN"
  value       = azurerm_postgresql_flexible_server.gateway.fqdn
}
