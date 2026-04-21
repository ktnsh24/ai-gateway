"""
AI Gateway — Application Configuration

Uses Pydantic Settings to load configuration from environment variables.
Every setting has a default for local development with Docker Compose.

See docs/reference/pydantic-models.md for detailed explanation of every field.
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudProvider(str, Enum):
    """Which cloud provider to use for LLM routing."""

    AWS = "aws"
    AZURE = "azure"
    LOCAL = "local"


class AppEnvironment(str, Enum):
    """Deployment environment. Affects log verbosity and feature flags."""

    DEV = "dev"
    STG = "stg"
    PRD = "prd"


class RoutingStrategy(str, Enum):
    """How to select the LLM provider for a request."""

    SINGLE = "single"          # Always use CLOUD_PROVIDER
    FALLBACK = "fallback"      # Try primary, fall back to secondary
    COST_OPTIMISED = "cost"    # Choose cheapest model that fits the task
    ROUND_ROBIN = "round"      # Rotate across providers


class Settings(BaseSettings):
    """
    Central configuration for the AI Gateway.

    Every setting comes from an environment variable (or .env file).
    Pydantic Settings automatically reads them — you never need to call os.getenv().
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = Field(default="ai-gateway", description="Service name used in logs and monitoring")
    environment: AppEnvironment = Field(default=AppEnvironment.DEV, description="Deployment environment")
    debug: bool = Field(default=True, description="Enable debug mode (verbose logging)")
    port: int = Field(default=8100, description="HTTP port (8100 to avoid conflict with rag-chatbot on 8000)")

    # --- Cloud Provider ---
    cloud_provider: CloudProvider = Field(
        default=CloudProvider.LOCAL,
        description="Primary LLM provider: aws, azure, or local (Ollama)",
    )
    routing_strategy: RoutingStrategy = Field(
        default=RoutingStrategy.SINGLE,
        description="How to select the LLM provider per request",
    )

    # --- AWS Bedrock ---
    aws_region: str = Field(default="eu-west-1", description="AWS region for Bedrock")
    aws_bedrock_model_id: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0",
        description="Default Bedrock model ID",
    )
    aws_bedrock_embed_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        description="Bedrock embedding model ID",
    )

    # --- Azure OpenAI ---
    azure_openai_endpoint: str = Field(default="", description="Azure OpenAI endpoint URL")
    azure_openai_api_key: str = Field(default="", description="Azure OpenAI API key")
    azure_openai_api_version: str = Field(default="2024-10-21", description="Azure OpenAI API version")
    azure_openai_deployment: str = Field(default="gpt-4o", description="Azure OpenAI deployment name")
    azure_openai_embed_deployment: str = Field(
        default="text-embedding-3-small",
        description="Azure OpenAI embedding deployment",
    )

    # --- Local (Ollama) ---
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    ollama_model: str = Field(default="llama3.2", description="Default Ollama model")
    ollama_embed_model: str = Field(default="nomic-embed-text", description="Ollama embedding model")

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (cache + rate limiting)",
    )
    cache_enabled: bool = Field(default=True, description="Enable semantic cache")
    cache_ttl_seconds: int = Field(default=3600, description="Cache TTL in seconds (1 hour)")
    cache_similarity_threshold: float = Field(
        default=0.92,
        description="Cosine similarity threshold for cache hits (0.92 = very similar)",
    )
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests_per_minute: int = Field(
        default=60, description="Max requests per API key per minute"
    )

    # --- PostgreSQL ---
    database_url: str = Field(
        default="postgresql+asyncpg://gateway:gateway@localhost:5432/ai_gateway",
        description="PostgreSQL connection URL for usage tracking",
    )

    # --- API Keys ---
    api_keys_enabled: bool = Field(default=False, description="Require API key authentication")
    master_api_key: str = Field(
        default="gw-dev-key-12345",
        description="Master API key for development (overridden in production)",
    )

    # --- LangFuse Observability ---
    langfuse_enabled: bool = Field(default=False, description="Enable LangFuse tracing")
    langfuse_public_key: str = Field(default="", description="LangFuse public key")
    langfuse_secret_key: str = Field(default="", description="LangFuse secret key")
    langfuse_host: str = Field(default="http://localhost:3000", description="LangFuse server URL")

    # --- Cost Tracking ---
    cost_tracking_enabled: bool = Field(default=True, description="Track per-request cost estimates")

    # --- Fallback ---
    fallback_provider: CloudProvider = Field(
        default=CloudProvider.LOCAL,
        description="Fallback provider when primary fails",
    )
    fallback_max_retries: int = Field(default=2, description="Max retries before falling back")
    fallback_timeout_seconds: float = Field(default=30.0, description="Timeout per provider attempt")


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — settings are loaded once and reused."""
    return Settings()
