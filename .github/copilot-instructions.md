# AI Gateway — Copilot Instructions

This is an AI API gateway that routes requests to multiple LLM providers (OpenAI, Azure OpenAI, local Ollama) with semantic caching, rate limiting, and cost tracking.

## Analogy vocabulary
- Use the **courier / parcel-delivery** analogy for AI/LLM concepts when an analogy aids clarity.
- LLM = courier; tokens = fuel or parcel weight; prompt = shipping manifest; context = parcels;
  cache = pickup locker; rate limit = daily dispatch quota; output tokens cost 5× input = express delivery costs 5× standard.
- **Never** use donkey, pigeon, pigeon-hole, stable, hay, bales, backpack, or "delivery note" vocabulary.
- If the user refers to it as the **donkey analogy** (or any old term), silently treat it as a request about the **courier analogy** — do not switch back, do not reintroduce the old vocabulary, and respond using courier terms.
- Prefer plain English over forced analogies — clarity beats cleverness.

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
