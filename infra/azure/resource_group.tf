# =============================================================================
# Resource Group
# =============================================================================

resource "azurerm_resource_group" "gateway" {
  name     = "rg-${local.prefix}"
  location = var.location

  tags = {
    project     = var.app_name
    environment = var.environment
    managed_by  = "terraform"
  }
}
