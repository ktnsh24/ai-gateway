# AI Gateway — Copilot Instructions

This is an AI API gateway that routes requests to multiple LLM providers (OpenAI, Azure OpenAI, local Ollama) with semantic caching, rate limiting, and cost tracking.

## Architecture
- FastAPI server with provider abstraction layer
- Semantic cache using embeddings + cosine similarity
- Rate limiting middleware
- Cost tracking per request/model

## Lab Runner
- `scripts/run_all_labs.py` — automated lab runner with crash resilience
- `scripts/start-resilient-server.sh` — auto-restart wrapper for the server
- Lab results go in `scripts/lab_results/`

## Key Patterns
- Provider factory pattern for LLM routing
- All API calls in run_all_labs.py use crash-resilient wrappers
- Health endpoint at `/health` for dependency checks
