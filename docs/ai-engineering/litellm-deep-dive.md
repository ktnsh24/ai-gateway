# LiteLLM Deep Dive — AI Gateway

> **What:** LiteLLM provides a unified interface to 100+ LLM providers using OpenAI-compatible format
>
> **Why:** Single integration point — switch providers by changing one env var
>
> **File:** `src/gateway/router.py`

---

## Table of Contents

1. [What LiteLLM Does](#1-what-litellm-does)
2. [Provider Model Mapping](#2-provider-model-mapping)
3. [Router Implementation](#3-router-implementation)
4. [Routing Strategies](#4-routing-strategies)
5. [Fallback Chains](#5-fallback-chains)
6. [Error Handling](#6-error-handling)
7. [Certification Relevance](#7-certification-relevance)
8. [Cross-References](#8-cross-references)

---

## 1. What LiteLLM Does

LiteLLM translates OpenAI-format API calls into provider-specific formats:

```
Your code: litellm.acompletion(model="bedrock/anthropic.claude-3-5-sonnet-v2", messages=[...])
 │
LiteLLM: ├── Translates to AWS Bedrock InvokeModel API
 ├── Signs with AWS SigV4
 ├── Handles streaming/non-streaming
 └── Translates response back to OpenAI format

Your code sees: {"choices": [{"message": {"content": "..."}}], "usage": {...}}
```

### Why Not Call Providers Directly?

| Without LiteLLM | With LiteLLM | 🚚 Courier |
|------------------|--------------|-----------|
| Import `boto3` for AWS, `openai` for Azure, `httpx` for Ollama | Import `litellm` | 🚚 Without the LiteLLM adapter each depot needs its own bespoke tack; LiteLLM provides a single API interface for every courier. |
| 3 different request formats | 1 format (OpenAI) | 🚚 Three depots use three different shipping manifest templates; the LiteLLM adapter converts everything into one standard form. |
| 3 different response parsers | 1 format (OpenAI) | 🚚 Each depot returns its receipt in its own layout; LiteLLM rewrites all three into the same OpenAI reply format. |
| 3 sets of auth logic | LiteLLM handles auth | 🚚 AWS SigV4, Azure API keys, and Ollama's open localhost — the LiteLLM adapter handles all three auth methods itself. |
| Provider switch = rewrite code | Provider switch = change model string | 🚚 Without the adapter swapping depots means rewriting the dispatch desk; LiteLLM needs only one model-string env var changed. |

---

## 2. Provider Model Mapping

LiteLLM uses a prefix convention to identify providers:

```python
MODEL_MAP = {
 "aws": {
 "chat": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
 "embedding": "bedrock/amazon.titan-embed-text-v2:0",
 },
 "azure": {
 "chat": "azure/gpt-4o",
 "embedding": "azure/text-embedding-3-small",
 },
 "local": {
 "chat": "ollama/llama3.2",
 "embedding": "ollama/nomic-embed-text",
 },
}
```

| Prefix | Provider | Auth Required | 🚚 Courier |
|--------|----------|--------------|-----------|
| `bedrock/` | AWS Bedrock | AWS credentials (IAM role or env vars) | 🚚 The `bedrock/` prefix points the LiteLLM adapter to the AWS depot where the Claude courier requires signed IAM credentials. |
| `azure/` | Azure OpenAI | `AZURE_API_KEY` + `AZURE_API_BASE` | 🚚 The `azure/` prefix steers the adapter to the Azure hub where the GPT-4o courier needs an API key and base URL pair. |
| `ollama/` | Ollama (local) | None (localhost:11434) | 🚚 The `ollama/` prefix routes to the local environment where the llama courier needs no API key — just a localhost port knock. |

### Environment Variables for Auth

```bash
# AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-west-1

# Azure OpenAI
AZURE_API_KEY=...
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-02-15-preview

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434 # default
```

---

## 3. Router Implementation

### Strategy Pattern

```python
class BaseLLMRouter(ABC):
 """Abstract interface for LLM routing."""

 @abstractmethod
 async def route_completion(
 self, request: ChatCompletionRequest
 ) -> ChatCompletionResponse: ...

 @abstractmethod
 async def route_embedding(
 self, request: EmbeddingRequest
 ) -> EmbeddingResponse: ...

 @abstractmethod
 async def list_models(self) -> list[ModelInfo]: ...
```

### LiteLLM Implementation

```python
class LiteLLMRouter(BaseLLMRouter):
 def __init__(self, settings: Settings) -> None:
 self.settings = settings
 self.provider = settings.cloud_provider.value
 self.models = MODEL_MAP[self.provider]

 async def route_completion(self, request):
 model = self.models["chat"]
 response = await litellm.acompletion(
 model=model,
 messages=[m.model_dump() for m in request.messages],
 temperature=request.temperature,
 max_tokens=request.max_tokens,
 )
 return self._to_response(response)
```

### Factory Function

```python
def create_router(settings: Settings) -> BaseLLMRouter:
 """Factory: create the appropriate LLM router."""
 return LiteLLMRouter(settings)
```

Why a factory even with one implementation? **Extensibility.** Adding a custom router (e.g., vLLM, TGI) requires zero changes to route code.

---

## 4. Routing Strategies

The gateway supports four routing strategies, configured via `ROUTING_STRATEGY`:

### Single (Default)

Route all requests to the configured `CLOUD_PROVIDER`:

```
CLOUD_PROVIDER=local + ROUTING_STRATEGY=single
→ All requests → ollama/llama3.2
```

### Fallback

Try providers in order, fall back on failure:

```
ROUTING_STRATEGY=fallback + FALLBACK_PROVIDERS=aws,azure,local
→ Try AWS Bedrock → if fails → Try Azure OpenAI → if fails → Try Ollama
```

### Cost-Optimised

Route to the cheapest available provider:

```
ROUTING_STRATEGY=cost
→ Sort providers by $/1K tokens → route to cheapest healthy provider
 local ($0) → aws ($0.003) → azure ($0.005)
```

### Round-Robin

Distribute requests across providers:

```
ROUTING_STRATEGY=round
→ Request 1 → AWS, Request 2 → Azure, Request 3 → Local, Request 4 → AWS...
```

---

## 5. Fallback Chains

The fallback implementation catches provider errors and retries:

```python
async def route_with_fallback(self, request, providers):
 last_error = None
 for provider in providers:
 try:
 model = MODEL_MAP[provider]["chat"]
 response = await litellm.acompletion(
 model=model,
 messages=[m.model_dump() for m in request.messages],
 )
 return self._to_response(response, provider=provider)
 except Exception as e:
 logger.warning(f"Provider {provider} failed: {e}")
 last_error = e
 raise HTTPException(
 status_code=503,
 detail=f"All providers failed. Last error: {last_error}"
 )
```

### Failure Scenarios

| Scenario | Behaviour | 🚚 Courier |
|----------|-----------|-----------|
| Primary healthy | Route to primary, ignore fallbacks | 🚚 When the first courier is awake and ready the dispatch desk sends the shipping manifests there and never peeks at the backup list. |
| Primary down | Try fallback 1, then fallback 2 | 🚚 When the primary courier is sick the dispatch desk immediately tries the first backup and then the second if that also fails. |
| All down | Return 503 with last error | 🚚 When every courier in the fallback chain is sick the dispatch desk returns a 503 and reports the last failure message. |
| Timeout | LiteLLM timeout → caught → try next | 🚚 When a courier takes too long the adapter catches the timeout and hands the shipping manifests to the next courier in line. |

---

## 6. Error Handling

LiteLLM raises specific exceptions mapped to HTTP status codes:

| LiteLLM Exception | HTTP Status | Gateway Response | 🚚 Courier |
|-------------------|-------------|------------------|-----------|
| `AuthenticationError` | 401 | Check provider credentials | 🚚 The far depot refused the courier at the gate — wrong API key on the provider's side, not the gateway's. |
| `RateLimitError` | 429 | Provider rate limit (not gateway) | 🚚 The provider depot's daily dispatch quota is exhausted — the courier was turned away at the depot door, not by our own quota enforcer. |
| `NotFoundError` | 404 | Model not found | 🚚 The dispatch desk asked for a model type that the depot doesn't stock — check the roster of available couriers. |
| `APIConnectionError` | 502 | Provider unreachable | 🚚 The far depot isn't answering the phone — the dispatch desk can't reach the depot's front door at all. |
| `Timeout` | 504 | Provider timeout | 🚚 The courier left but never came back within the allowed time — the dispatch desk gives up and tries the next in line. |
| Generic `Exception` | 500 | Internal gateway error | 🚚 Something broke inside the dispatch desk itself — not the depot's fault; the gateway hit an unexpected internal error. |

---

## 7. Certification Relevance

| Cert Topic | Connection | 🚚 Courier |
|------------|------------|-----------|
| **AWS SAA-C03: API Gateway patterns** | Gateway routing = API Gateway routing policies | 🚚 The dispatch desk's routing strategies map to AWS API Gateway routing policies tested on the SAA-C03 exam. |
| **AWS SAA-C03: High availability** | Fallback routing = multi-AZ/multi-region failover | 🚚 The fallback chain that tries backup couriers mirrors multi-AZ failover — if one depot burns down another takes the delivery. |
| **AZ-305: Load balancing** | Round-robin strategy = Azure Traffic Manager | 🚚 Round-robin delivery across AWS, Azure, and local environment matches Azure Traffic Manager's weighted round-robin routing policy. |
| **AZ-305: Cost management** | Cost-optimised routing = Azure Cost Management policies | 🚚 Steering shipping manifests to the cheapest available courier is the hands-on version of Azure Cost Management's budget routing. |

---

## 8. Cross-References

| Topic | Document | 🚚 Courier |
|-------|----------|-----------|
| Architecture overview | [Architecture](../architecture-and-design/architecture.md) | 🚚 The full system architecture showing where the LiteLLM adapter and dispatch desk sit in the overall gateway design. |
| API specification | [API Contract](../architecture-and-design/api-contract.md) | 🚚 The completions endpoint spec — the delivery window contract that callers use to hand shipping manifests to the dispatch desk. |
| Caching layer | [Caching Deep Dive](caching-deep-dive.md) | 🚚 The pickup locker that intercepts shipping manifests before the LiteLLM adapter even selects which courier to dispatch. |
| Rate limiting | [Rate Limiting Deep Dive](rate-limiting-deep-dive.md) | 🚚 The daily dispatch quota enforcer that checks a courier's API key before the adapter assigns them a courier. |
| Hands-on lab | [Labs Phase 1](../hands-on-labs/hands-on-labs-phase-1.md) | 🚚 Practical exercises that wire up the LiteLLM adapter to real depots and verify the dispatch desk routes correctly. |
