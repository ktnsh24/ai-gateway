# =============================================================================
# Variables
# =============================================================================

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "environment" {
  description = "Deployment environment (dev, stg, prd)"
  type        = string
  default     = "dev"
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "ai-gateway"
}

variable "image_tag" {
  description = "Docker image tag to deploy (defaults to latest)"
  type        = string
  default     = "latest"
}

# --- Cost Controller ---

variable "cost_limit_eur" {
  description = "Monthly budget limit in EUR — resources are killed when exceeded"
  type        = number
  default     = 5
}

variable "alert_email" {
  description = "Email address for budget alerts (80% warning + 100% kill notification)"
  type        = string
}

variable "db_admin_password" {
  description = "Azure PostgreSQL admin password (set via TF_VAR_db_admin_password env var; never commit a real value)"
  type        = string
  sensitive   = true
}
