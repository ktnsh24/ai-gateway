# 📚 Documentation Reading Order

> A guided path through the ai-gateway documentation. Start at Level 1 and work down. Levels 1–3 give you a working mental model; Levels 4–7 are reference + practice.

---

## Table of Contents

- [Level 1 — Start Here (The Big Picture)](#level-1--start-here-the-big-picture)
- [Level 2 — Setup & Run It](#level-2--setup--run-it)
- [Level 3 — Core Components Deep Dives](#level-3--core-components-deep-dives)
- [Level 4 — Understand the API](#level-4--understand-the-api)
- [Level 5 — Cloud Infrastructure](#level-5--cloud-infrastructure)
- [Level 6 — Evaluation & Cost](#level-6--evaluation--cost)
- [Level 7 — Hands-On Labs](#level-7--hands-on-labs)
- [Quick Reference](#quick-reference)

---

## Level 1 — Start Here (The Big Picture)

Read these first to understand what an LLM gateway is and why this project exists.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 1 | [README.md](../README.md) | Project overview, features, tech stack, quick start | The depot's switchboard notice — what this dispatch desk does, which couriers it can call, and how to flip the lights on. |
| 2 | [Gateway Concepts](ai-engineering/gateway-concepts.md) | What is an LLM gateway? Routing, caching, rate limiting, cost tracking — the 4 pillars explained | The training manual for the dispatcher — why every delivery goes through one desk instead of each customer flagging down their own courier. |
| 3 | [Architecture Overview](architecture-and-design/architecture.md) | System diagram, component relationships, request lifecycle | The dispatch-desk floor plan — every door, every shelf, every courier stall, and the route a delivery slip travels through them. |

---

## Level 2 — Setup & Run It

Get the gateway running on your machine.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 4 | [Getting Started](setup-and-tooling/getting-started.md) | Install Python, Poetry, env vars, first request | Open the depot, hire the staff, set up the front-door sign — first delivery slip goes through in five minutes. |
| 5 | [Docker Compose Guide](setup-and-tooling/docker-compose-guide.md) | Run the full stack (gateway + Redis + PostgreSQL) in containers | Portable deployment kit — pop the lid, the pickup locker shelf and ledger book are already wired in. |
| 6 | [Debugging Guide](setup-and-tooling/debugging-guide.md) | Common errors and how to fix them | What to do when the dispatch desk jams — the usual sticks in the gears and how to clear them. |

---

## Level 3 — Core Components Deep Dives

The four pillars of the gateway, in the order a request meets them.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 7 | [LiteLLM Deep Dive](ai-engineering/litellm-deep-dive.md) | The universal harness — one OpenAI-format call, 100+ providers | The universal harness that fits any courier — same reins, whether the courier lives in AWS, Azure, or the local depot. |
| 8 | [Caching Deep Dive](ai-engineering/caching-deep-dive.md) | Semantic cache (cosine similarity in Redis), TTL, hit-rate tuning | The pickup locker of pre-written replies — if a near-identical question came in before, hand back the same note instantly, no delivery. |
| 9 | [Rate Limiting Deep Dive](ai-engineering/rate-limiting-deep-dive.md) | Fixed-window rate limit per API key, Redis vs in-memory | Trip quota per courier — each API key gets N deliveries per minute; on the (N+1)th the gate slams shut until the clock ticks over. |
| 10 | [Cost Tracking Deep Dive](ai-engineering/cost-tracking-deep-dive.md) | Per-request cost log, PostgreSQL schema, per-provider rollups | The leather-bound expense ledger — every delivery recorded with provider, tokens, and price, ready for the monthly invoice. |
| 11 | [Observability Deep Dive](ai-engineering/observability-deep-dive.md) | Structured logging, request IDs, latency histograms | The observability dashboard plus the tachograph on every courier — every step of every delivery is timestamped, tagged, and replayable. |

---

## Level 4 — Understand the API

The gateway exposes an OpenAI-compatible HTTP surface. Start with the contract, then dive into each endpoint.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 12 | [API Contract](architecture-and-design/api-contract.md) | All routes at a glance, request/response shapes, status codes | The full sign-board on the gateway's front door — every window, what slip goes in, what package comes out. |
| 13 | [Completions Endpoint](architecture-and-design/api-routes/completions-endpoint-explained.md) | `POST /v1/chat/completions` — the main RAG-style call | The main delivery window — hand in a question slip, get back a written answer carried by whichever courier was on duty. |
| 14 | [Embeddings Endpoint](architecture-and-design/api-routes/embeddings-endpoint-explained.md) | `POST /v1/embeddings` — turn text into vectors | The GPS-coordinate writer — text in, fixed-length coordinates out, ready to be shelved in the warehouse. |
| 15 | [Models Endpoint](architecture-and-design/api-routes/models-endpoint-explained.md) | `GET /v1/models` — list available providers | The roster pinned to the dispatcher's wall — every courier currently on shift and what they're certified to carry. |
| 16 | [Usage Endpoint](architecture-and-design/api-routes/usage-endpoint-explained.md) | `GET /v1/usage` — read the cost ledger | The expense-ledger window — open the leather book and read this week's totals by provider and API key. |
| 17 | [Health Endpoint](architecture-and-design/api-routes/health-endpoint-explained.md) | `GET /health` — combined liveness + readiness with Redis/Postgres probes | "Is the courier awake?" check — quick yes/no plus whether the pickup lockers and ledger are reachable. |
| 18 | [Pydantic Models](reference/pydantic-models.md) | Request/response schemas, validation rules | The parcel-size rules — the exact shape every slip and package must fit before the dispatcher will touch them. |

---

## Level 5 — Cloud Infrastructure

How the gateway deploys to AWS and Azure.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 19 | [Terraform Guide](setup-and-tooling/terraform-guide.md) | Run `terraform apply`/`destroy` for AWS and Azure stacks | How to use the infrastructure blueprints — one command builds the whole dispatch building, another tears it down safely. |
| 20 | [Infrastructure Explained](architecture-and-design/infra-explained.md) | Terraform modules, IAM roles, networking — what each resource is for | The blueprint annotations — every wall, wire, and gate, plus why it has to be exactly there. |
| 21 | [CI/CD Explained](architecture-and-design/cicd-explained.md) | GitHub Actions pipeline, eval gates, deployment flow | The automated pipeline — runs the report card on every push and only opens the gate to production if every courier passed. |

---

## Level 6 — Evaluation & Cost

Measure what the gateway costs you and how well it behaves.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 22 | [Cost Analysis](ai-engineering/cost-analysis.md) | Token cost per provider, monthly projections, cache savings | The accountant's view of the ledger — how much each provider charges per parcel unit and where the cache cuts the bill. |
| 23 | [Testing](ai-engineering/testing.md) | Unit + integration test inventory, the in-memory pattern that makes Redis/PostgreSQL optional in tests | Quality gates before each shift — every component checked alone, then the full pipeline run end to end. |
| 24 | [Monitoring](reference/monitoring.md) | Structured logs, cost rows, health probes, optional LangFuse — what we record and how to read it | The CCTV control room — four signal feeds wired into the wall (tachograph tape, leather ledger, porch lamp, optional CCTV) and how the operator reads them. |

---

## Level 7 — Hands-On Labs

**Read [How to Read the Labs](hands-on-labs/how-to-read-the-labs.md) FIRST.** Without that mental model the gateway labs feel repetitive — every lab reports the same metrics (latency, cache hit %, cost, error rate) because that's the *yardstick* every lab is measured against.

| # | Document | What you'll learn | 🚚 Courier |
|---|----------|-------------------|-----------|
| 25 | [How to Read the Labs](hands-on-labs/how-to-read-the-labs.md) | The yardstick vs knob mental model; 5-question method to read any gateway lab | The missing intro — explains why every lab grades the same 4 subjects so the report card stops looking redundant. |
| 26 | [Config Tuning Labs](hands-on-labs/hands-on-labs-config-tuning.md) | Sweep the env knobs (cache TTL, rate limit, temperature, model, max_tokens) | Sweep the dispatcher's dials one at a time — each lab moves one knob and re-reads the same yardstick. |
| 27 | [Phase 1 — Foundation Labs](hands-on-labs/hands-on-labs-phase-1.md) | First end-to-end gateway runs: cache hit rate, rate-limit behaviour, fallback under failure | First solo dispatch shifts — verify the pickup locker shelf hits, the gate slams at the quota, the backup courier kicks in. |
| 28 | [Phase 2 — Production Labs](hands-on-labs/hands-on-labs-phase-2.md) | Multi-provider routing, cost-optimised strategy under load, observability dashboards | Busy-day dispatch — three couriers on rotation, cheapest-first routing, watching the CCTV while it all runs. |

---

## Quick Reference

- **"I want to run it"** → Start at doc #4 (Getting Started)
- **"What's an LLM gateway?"** → Start at doc #2 (Gateway Concepts)
- **"I want to call the API"** → Read doc #12 (API Contract) then the relevant endpoint doc
- **"I want to deploy to AWS"** → Read docs #19–20
- **"I want to run the labs"** → Read doc #25 first, then #26–28
- **"How much will this cost?"** → Read doc #22 (Cost Analysis)
