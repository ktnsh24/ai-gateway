"""
AI Gateway — LLM Router

Routes requests to the correct LLM provider via LiteLLM.
Supports single provider, fallback chains, cost-optimised, and round-robin strategies.

LiteLLM provides a unified interface to 100+ LLM providers with an OpenAI-compatible API.
This module wraps LiteLLM to add our routing strategies and provider configuration.

See docs/ai-engineering/litellm-deep-dive.md for detailed explanation.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from loguru import logger

from src.config import CloudProvider, RoutingStrategy, Settings


class BaseLLMRouter(ABC):
    """Abstract base class for LLM routing.

    Strategy Pattern — same interface, different routing logic.
    The factory method picks the implementation based on config.
    """

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict],
        model: str = "default",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict:
        """Send a chat completion request to an LLM provider.

        Returns a dict matching the OpenAI response schema.
        """

    @abstractmethod
    async def embedding(
        self,
        input_text: str | list[str],
        model: str = "default",
        **kwargs,
    ) -> dict:
        """Generate embeddings for input text(s).

        Returns a dict matching the OpenAI embedding response schema.
        """

    @abstractmethod
    def list_models(self) -> list[dict]:
        """List available models from the configured provider(s)."""


class LiteLLMRouter(BaseLLMRouter):
    """Routes LLM requests via LiteLLM to AWS Bedrock, Azure OpenAI, or Local Ollama.

    LiteLLM normalises all providers to the OpenAI API format. This means:
    - Same request format for Bedrock, Azure OpenAI, and Ollama
    - Same response format regardless of provider
    - Automatic token counting and cost estimation
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = settings.cloud_provider
        self._routing = settings.routing_strategy
        self._call_count = 0  # For round-robin

        # Provider model mappings
        self._model_map: dict[CloudProvider, dict] = {
            CloudProvider.AWS: {
                "chat": f"bedrock/{settings.aws_bedrock_model_id}",
                "embed": f"bedrock/{settings.aws_bedrock_embed_model_id}",
                "display": settings.aws_bedrock_model_id,
                "owned_by": "aws-bedrock",
            },
            CloudProvider.AZURE: {
                "chat": f"azure/{settings.azure_openai_deployment}",
                "embed": f"azure/{settings.azure_openai_embed_deployment}",
                "display": settings.azure_openai_deployment,
                "owned_by": "azure-openai",
            },
            CloudProvider.LOCAL: {
                "chat": f"ollama/{settings.ollama_model}",
                "embed": f"ollama/{settings.ollama_embed_model}",
                "display": settings.ollama_model,
                "owned_by": "ollama-local",
            },
        }

        logger.info(
            f"LLM Router initialised: provider={self._provider.value}, "
            f"strategy={self._routing.value}"
        )

    def _resolve_provider(self, preferred: str | None = None) -> CloudProvider:
        """Resolve which provider to use based on routing strategy."""
        if preferred:
            try:
                return CloudProvider(preferred)
            except ValueError:
                logger.warning(f"Unknown preferred provider '{preferred}', using default")

        if self._routing == RoutingStrategy.SINGLE:
            return self._provider

        if self._routing == RoutingStrategy.ROUND_ROBIN:
            providers = list(CloudProvider)
            idx = self._call_count % len(providers)
            self._call_count += 1
            return providers[idx]

        # FALLBACK and COST strategies use primary first
        return self._provider

    def _get_model_id(self, provider: CloudProvider, model_type: str = "chat") -> str:
        """Get the LiteLLM model identifier for a provider."""
        return self._model_map[provider][model_type]

    def _get_litellm_kwargs(self, provider: CloudProvider) -> dict:
        """Get provider-specific kwargs for LiteLLM calls."""
        if provider == CloudProvider.AZURE:
            return {
                "api_base": self._settings.azure_openai_endpoint,
                "api_key": self._settings.azure_openai_api_key,
                "api_version": self._settings.azure_openai_api_version,
            }
        if provider == CloudProvider.LOCAL:
            return {
                "api_base": self._settings.ollama_base_url,
            }
        # AWS — LiteLLM uses boto3 credentials automatically
        return {}

    async def chat_completion(
        self,
        messages: list[dict],
        model: str = "default",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        **kwargs,
    ) -> dict:
        """Route a chat completion request to the appropriate provider.

        Supports fallback: if the primary provider fails, tries the fallback provider.
        """
        import litellm

        provider = self._resolve_provider(preferred_provider)
        model_id = self._get_model_id(provider, "chat")
        provider_kwargs = self._get_litellm_kwargs(provider)

        start = time.perf_counter()

        try:
            response = await litellm.acompletion(
                model=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **provider_kwargs,
                **kwargs,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                f"Chat completion: provider={provider.value}, "
                f"model={model_id}, latency={elapsed_ms:.0f}ms"
            )
            return {
                "response": response,
                "provider": provider.value,
                "model": model_id,
                "latency_ms": elapsed_ms,
            }

        except Exception as e:
            logger.error(f"Provider {provider.value} failed: {e}")

            # Attempt fallback
            if (
                self._routing in (RoutingStrategy.FALLBACK, RoutingStrategy.COST_OPTIMISED)
                and self._settings.fallback_provider != provider
            ):
                fb_provider = self._settings.fallback_provider
                fb_model = self._get_model_id(fb_provider, "chat")
                fb_kwargs = self._get_litellm_kwargs(fb_provider)

                logger.warning(f"Falling back to {fb_provider.value}")
                try:
                    response = await litellm.acompletion(
                        model=fb_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **fb_kwargs,
                        **kwargs,
                    )
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    return {
                        "response": response,
                        "provider": fb_provider.value,
                        "model": fb_model,
                        "latency_ms": elapsed_ms,
                        "fallback": True,
                    }
                except Exception as fb_err:
                    logger.error(f"Fallback {fb_provider.value} also failed: {fb_err}")
                    raise

            raise

    async def embedding(
        self,
        input_text: str | list[str],
        model: str = "default",
        preferred_provider: str | None = None,
        **kwargs,
    ) -> dict:
        """Route an embedding request to the appropriate provider."""
        import litellm

        provider = self._resolve_provider(preferred_provider)
        model_id = self._get_model_id(provider, "embed")
        provider_kwargs = self._get_litellm_kwargs(provider)

        start = time.perf_counter()

        response = await litellm.aembedding(
            model=model_id,
            input=input_text if isinstance(input_text, list) else [input_text],
            **provider_kwargs,
            **kwargs,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"Embedding: provider={provider.value}, model={model_id}, latency={elapsed_ms:.0f}ms"
        )
        return {
            "response": response,
            "provider": provider.value,
            "model": model_id,
            "latency_ms": elapsed_ms,
        }

    def list_models(self) -> list[dict]:
        """List available models from configured providers."""
        models = []
        for provider, mapping in self._model_map.items():
            models.append({
                "id": mapping["display"],
                "provider": provider.value,
                "owned_by": mapping["owned_by"],
                "capabilities": ["chat", "completions"],
            })
            models.append({
                "id": mapping["display"] + "-embed",
                "provider": provider.value,
                "owned_by": mapping["owned_by"],
                "capabilities": ["embeddings"],
            })
        return models


def create_router(settings: Settings) -> BaseLLMRouter:
    """Factory method — creates the LLM router based on settings.

    Same pattern as V1's RAGChain.create() — single entry point,
    returns the correct implementation.
    """
    return LiteLLMRouter(settings)
