# Getting Started — AI Gateway

> **Time to first request:** ~5 minutes (local) | ~30 minutes (Docker Compose with Redis + PostgreSQL)

---

## Table of Contents

- [What you need before starting](#what-you-need-before-starting)
- [Step 1 — Install Python 3.12](#step-1--install-python-312)
- [Step 2 — Install Poetry](#step-2--install-poetry)
- [Step 3 — Clone and install dependencies](#step-3--clone-and-install-dependencies)
- [Step 4 — Configure environment variables](#step-4--configure-environment-variables)
- [Step 5 — Start the gateway (local)](#step-5--start-the-gateway-local)
- [Step 6 — Test the API](#step-6--test-the-api)
- [Step 7 — Full Setup (Docker Compose — Redis + PostgreSQL)](#step-7--full-setup-docker-compose--redis--postgresql)
- [Step 8 — Run Labs Locally](#step-8--run-labs-locally)
- [Step 9 — Connect to AWS (and run on AWS)](#step-9--connect-to-aws-and-run-on-aws)
- [Step 10 — Connect to Azure (and run on Azure)](#step-10--connect-to-azure-and-run-on-azure)
- [Step 11 — Run the Tests](#step-11--run-the-tests)
- [Step 12 — Project Structure](#step-12--project-structure)
- [Troubleshooting](#troubleshooting)

---

## What you need before starting

| Tool | Version | Why you need it | 🫏 Donkey |
| --- | --- | --- | --- |
| **Python** | 3.12+ | The gateway is written in Python | 🫏 The stable floor itself — without Python 3.12 the whole dispatch desk refuses to stand up at all. |
| **Poetry** | 1.8+ | Package manager (manages dependencies + virtual environment) | 🫏 The tack-room organiser that rounds up every dependency harness so all donkeys are fitted before the first trip. |
| **Git** | 2.40+ | Version control | 🫏 The stable logbook that tracks every blueprint change so you can rewind to any working state if things go wrong. |
| **Ollama** | Latest | Local LLM and embeddings (for `CLOUD_PROVIDER=local`) | 🫏 The local barn housing the donkey and GPS-coordinate writer so no cloud depot is needed during development. |
| **Docker** | 24+ | For Redis + PostgreSQL (optional, for full setup) | 🫏 The portable mini-stable kit that spins up the pigeon-hole shelf and expense ledger containers with one command. |
| **AWS CLI** | 2.x | Connect to AWS services (optional) | 🫏 The command-line pass that authenticates you to the AWS depot so cloud donkeys can be dispatched from the terminal. |
| **Azure CLI** | 2.x | Connect to Azure services (optional) | 🫏 The command-line pass that authenticates you to the Azure hub so the Container Apps barn accepts your deploy commands. |
| **Terraform** | 1.5+ | Deploy cloud infrastructure (optional) | 🫏 The stable-blueprints tool that prints AWS or Azure barn infrastructure from code with a single apply command. |

### Check what is already installed

```bash
python3 --version      # Need 3.12+
poetry --version       # Need 1.8+
git --version          # Need 2.40+
ollama --version       # Need latest
docker --version       # Optional
aws --version          # Optional
az --version           # Optional
terraform --version    # Optional
```

---

## Step 1 — Install Python 3.12

```bash
# Ubuntu / WSL
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev

# Verify
python3.12 --version
```

---

## Step 2 — Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -

# Add to PATH (add to ~/.bashrc for persistence)
export PATH="$HOME/.local/bin:$PATH"

# Verify
poetry --version

# Configure Poetry to create virtualenvs inside the project
poetry config virtualenvs.in-project true
```

---

## Step 3 — Clone and install dependencies

```bash
cd repos/ai-gateway

# Install dependencies
poetry install

# Verify the virtual environment
poetry env info
```

---

## Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with these key settings:

| Variable | Default | Description | 🫏 Donkey |
| --- | --- | --- | --- |
| `CLOUD_PROVIDER` | `local` | LLM provider: `aws`, `azure`, `local` | 🫏 Tells the dispatch desk which stable a donkey works for — local barn, AWS depot, or Azure hub. |
| `PORT` | `8100` | Server port | 🫏 The front door number where the stable manager listens for incoming delivery note requests from every caller. |
| `ROUTING_STRATEGY` | `single` | Routing: `single`, `fallback`, `cost`, `round` | 🫏 Decides which donkey gets the next trip — same donkey always, cheapest first, round turns, or sick-donkey fallback. |
| `CACHE_ENABLED` | `true` | Enable semantic caching (in-memory or Redis) | 🫏 Turns the pigeon-hole of pre-written replies on or off so similar delivery notes skip the donkey entirely. |
| `CACHE_SIMILARITY_THRESHOLD` | `0.92` | Cosine similarity for cache hits | 🫏 The minimum GPS closeness score before the dispatch desk considers two delivery notes similar enough to reuse the reply. |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Max requests per API key per minute | 🫏 The trip quota enforced per courier — each API key may dispatch at most this many donkeys per fixed-window minute. |
| `COST_TRACKING_ENABLED` | `true` | Track per-request costs | 🫏 Switches the donkey expense ledger on or off so every cargo-unit charge is recorded per provider per request. |
| `API_KEYS_ENABLED` | `false` | Require API key authentication | 🫏 When enabled, the stable's front door demands a valid permission slip before any delivery note is accepted at all. |

**Local provider settings (default — works out of the box):**

```bash
CLOUD_PROVIDER=local
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text
```

**AWS provider settings:**

```bash
CLOUD_PROVIDER=aws
AWS_REGION=eu-west-1
AWS_BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
AWS_BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
```

**Azure provider settings:**

```bash
CLOUD_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_API_VERSION=2024-10-21
```

---

## Step 5 — Start the gateway (local)

### Install Ollama and pull models

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull required models
ollama pull llama3.2          # LLM (~2 GB)
ollama pull nomic-embed-text  # Embeddings (~275 MB)

# Verify
ollama list
```

### Start the gateway

```bash
poetry run start
# → Server running at http://localhost:8100
# → Swagger UI at http://localhost:8100/docs
```

---

## Step 6 — Test the API

### Health check

```bash
curl http://localhost:8100/health | jq
```

### Chat completion

```bash
curl -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Explain Docker Compose in one sentence."}
    ],
    "temperature": 0.5
  }' | jq
```

### Embeddings

```bash
curl -X POST http://localhost:8100/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world"}' | jq '.data[0].embedding[:5]'
```

### Models list

```bash
curl http://localhost:8100/v1/models | jq
```

### Usage dashboard

```bash
curl "http://localhost:8100/v1/usage?period=today" | jq
```

### Swagger UI

Open <http://localhost:8100/docs> in your browser for interactive API documentation.

---

## Step 7 — Full Setup (Docker Compose — Redis + PostgreSQL)

For the full experience with persistent caching (Redis) and cost tracking (PostgreSQL):

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# Watch logs
docker compose logs -f app

# Gateway: http://localhost:8100
# Redis:   localhost:6379
# PostgreSQL: localhost:5432
```

To run the app locally but use Docker Redis + PostgreSQL:

```bash
docker compose up -d redis pg
poetry run start
```

---

## Step 8 — Run Labs Locally

Once the gateway is running locally (see [Step 5](#step-5--start-the-gateway-local)), you can run all 8 hands-on labs.

**Cost: $0. No API keys needed. Runs entirely on your machine.**

### 8a. Automated (recommended)

```bash
# 1. Start the gateway (in one terminal)
poetry run start

# 2. Run all labs (in another terminal)
poetry run python scripts/run_all_labs.py --env local
```

This runs all 8 hands-on labs against Ollama and prints a pass/fail report.

No infrastructure to deploy or destroy — it's all local.

**Results are saved to:** `scripts/lab_results/local/`

### 8b. Or run manually (step by step)

```bash
# Start the gateway
poetry run start

# Then test manually through Swagger UI at http://localhost:8100/docs
```

**Results location:** `scripts/lab_results/local/`

> **Note:** `run_cloud_labs.sh` is for cloud deployments only (AWS/Azure). It wraps
> `terraform apply` → labs → `terraform destroy`. For local development, use
> `run_all_labs.py` directly as shown above.

### Hardware requirements

| Component | Minimum | Recommended | 🫏 Donkey |
| --- | --- | --- | --- |
| **RAM** | 8 GB | 16 GB | 🫏 The stable's working memory — 8 GB keeps the local donkey trotting; 16 GB lets it gallop without swapping to disk. |
| **Disk** | 5 GB (for models) | 10 GB | 🫏 Stores the donkey model files pulled from Ollama — the local barn needs at least 5 GB of clear floor space. |
| **GPU** | Not required (CPU works) | NVIDIA GPU (faster inference) | 🫏 A GPU saddles up the donkey's inference horsepower, slashing response time compared to CPU-only barn operations. |

---

## Step 9 — Connect to AWS (and run on AWS)

### 9a. Install AWS CLI

```bash
# Ubuntu / WSL
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws --version
```

### 9b. Configure AWS credentials

**Option A: Access keys (simplest for personal account)**

```bash
aws configure
# AWS Access Key ID: <paste your key>
# AWS Secret Access Key: <paste your secret>
# Default region name: eu-west-1
# Default output format: json
```

Get your access keys from: AWS Console → IAM → Users → Your User → Security credentials → Create access key.

**Option B: SSO (if your account uses AWS Organizations)**

```bash
aws configure sso --profile ai-gateway
# Follow the prompts for SSO start URL, region, account, role
```

### 9c. Enable Bedrock model access

Bedrock models are not enabled by default. You need to request access:

1. Go to AWS Console → Amazon Bedrock → Model access
2. Click "Manage model access"
3. Enable:
   - **Anthropic → Claude 3.5 Sonnet v2** (for LLM)
   - **Amazon → Titan Text Embeddings V2** (for embeddings)
4. Wait for approval (usually instant for personal accounts)

### 9d. Verify AWS connectivity

```bash
aws sts get-caller-identity
# Should show your account ID and ARN

aws bedrock list-foundation-models --region eu-west-1 \
  --query "modelSummaries[?contains(modelId, 'claude')].[modelId]" --output table
```

### Cost-saving tips for AWS

- **Bedrock**: Pay-per-token only. No idle costs. A typical development session costs < $1.
- **ElastiCache (Redis)**: ~$13/month for cache.t3.micro. Only deploy for cloud labs.
- **RDS (PostgreSQL)**: ~$15/month for db.t3.micro. Only deploy for cloud labs.
- **⚠️ Always destroy after labs** — the budget guard (€5 default) is your safety net.

### 9e. Deploy and run labs (automated)

```bash
./scripts/run_cloud_labs.sh --provider aws --email you@example.com
```

The script automatically:

1. `terraform apply` — deploys ECS, ElastiCache (Redis), RDS (PostgreSQL), and a budget guard
2. Starts the gateway with `CLOUD_PROVIDER=aws`
3. Runs all 8 hands-on labs against AWS
4. Prints a pass/fail completion report
5. `terraform destroy` — tears down ALL infrastructure (even on Ctrl+C or errors)

**Budget control:** The default budget limit is €5. To increase it:

```bash
./scripts/run_cloud_labs.sh --provider aws --email you@example.com --cost-limit 15
```

**Results are saved to:** `scripts/lab_results/aws/`

### 9f. Or deploy and run manually (step by step)

```bash
# 1. Deploy infrastructure
cd infra/aws
terraform init
terraform apply -var="cost_limit_eur=5" -var="alert_email=you@example.com"

# 2. Set CLOUD_PROVIDER=aws in .env (see Step 4)

# 3. Start the gateway
cd ../..  # back to repo root
poetry run start

# 4. Run labs automatically (in another terminal)
poetry run python scripts/run_all_labs.py --env aws

# OR — test manually through Swagger UI at http://localhost:8100/docs

# 5. ALWAYS destroy when done
cd infra/aws
terraform destroy -var="cost_limit_eur=5" -var="alert_email=you@example.com"
```

> ⚠️ **CAUTION — Manual mode means manual cleanup!** When running manually, there
> is no automatic `terraform destroy` on exit. Monitor your costs in the
> [AWS Billing Console](https://console.aws.amazon.com/billing/)
> and **always run `terraform destroy` when finished.**

**Results location:** `scripts/lab_results/aws/`

---

## Step 10 — Connect to Azure (and run on Azure)

### 10a. Install Azure CLI

```bash
# Ubuntu / WSL
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az --version
```

### 10b. Login to Azure

```bash
az login
# Opens a browser — sign in with your Azure account

# Set the active subscription (if you have multiple)
az account set --subscription "your-subscription-id"
```

### 10c. Create Azure OpenAI resource

1. Go to Azure Portal → Create a resource → "Azure OpenAI"
2. Select your subscription and resource group
3. Region: **West Europe** (cheapest in EU)
4. Pricing tier: **Standard S0**
5. After creation, go to the resource → Keys and Endpoint
6. Copy the **Endpoint** and **Key 1** to your `.env` file

### 10d. Deploy models in Azure OpenAI

1. Go to Azure AI Studio (<https://ai.azure.com>)
2. Select your Azure OpenAI resource
3. Go to Deployments → Create deployment
4. Deploy:
   - **gpt-4o** — deployment name: `gpt-4o`
   - **text-embedding-3-small** — deployment name: `text-embedding-3-small`

### 10e. Verify Azure connectivity

```bash
az account show
# Should show your subscription

curl -X POST "https://your-resource.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21" \
  -H "api-key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 10}'
```

### Cost-saving tips for Azure

- **Azure OpenAI**: Pay-per-token. Development costs < $1/day.
- **Redis Cache**: ~$16/month for C0 Basic. Only deploy for cloud labs.
- **PostgreSQL Flexible**: ~$15/month for Burstable B1ms. Only deploy for cloud labs.
- **⚠️ Always destroy after labs** — the budget guard (€5 default) is your safety net.

### 10f. Deploy and run labs (automated)

```bash
./scripts/run_cloud_labs.sh --provider azure --email you@example.com
```

The script automatically:

1. `terraform apply` — deploys Container Apps, Redis, PostgreSQL, and a budget guard
2. Starts the gateway with `CLOUD_PROVIDER=azure`
3. Runs all 8 hands-on labs against Azure
4. Prints a pass/fail completion report
5. `terraform destroy` — tears down ALL infrastructure (even on Ctrl+C or errors)

**Budget control:**

```bash
./scripts/run_cloud_labs.sh --provider azure --email you@example.com --cost-limit 15
```

**Results are saved to:** `scripts/lab_results/azure/`

### 10g. Or deploy and run manually (step by step)

```bash
# 1. Deploy infrastructure
cd infra/azure
terraform init
terraform apply -var="cost_limit_eur=5" -var="alert_email=you@example.com"

# 2. Set CLOUD_PROVIDER=azure in .env (see Step 4)

# 3. Start the gateway
cd ../..  # back to repo root
poetry run start

# 4. Run labs automatically (in another terminal)
poetry run python scripts/run_all_labs.py --env azure

# OR — test manually through Swagger UI at http://localhost:8100/docs

# 5. ALWAYS destroy when done
cd infra/azure
terraform destroy -var="cost_limit_eur=5" -var="alert_email=you@example.com"
```

> ⚠️ **CAUTION — Manual mode means manual cleanup!** When running manually, there
> is no automatic `terraform destroy` on exit. Monitor your costs in the
> [Azure Cost Management](https://portal.azure.com/#view/Microsoft_Azure_CostManagement)
> and **always run `terraform destroy` when finished.**

**Results location:** `scripts/lab_results/azure/`

---

## Step 11 — Run the Tests

```bash
# All tests
poetry run pytest tests/ -v

# With coverage
poetry run pytest tests/ -v --cov=src --cov-report=term-missing

# Specific test file
poetry run pytest tests/test_cache.py -v
```

Expected test files:

```text
tests/test_cache.py       - 7 tests (in-memory cache, TTL, stats)
tests/test_completions.py - 12 tests (API, rate limit, cache hit)
tests/test_cost_tracker.py - 6 tests (logging, aggregation, breakdown)
tests/test_health.py      - 8 tests (health, models, usage)
tests/test_rate_limiter.py - 7 tests (allow, reject, reset, per-key)
```

---

## Step 12 — Project Structure

```text
ai-gateway/
├── src/
│   ├── main.py              ← FastAPI app factory + lifespan
│   ├── config.py            ← Pydantic Settings (all env vars)
│   ├── models.py            ← Request/response Pydantic models
│   ├── gateway/
│   │   ├── router.py        ← LLM routing via LiteLLM (Strategy Pattern)
│   │   ├── cache.py         ← Semantic cache (Redis / in-memory / none)
│   │   ├── rate_limiter.py  ← Rate limiting (Redis / in-memory / none)
│   │   └── cost_tracker.py  ← Usage logging (PostgreSQL / in-memory / none)
│   ├── routes/
│   │   ├── health.py        ← GET /health
│   │   ├── completions.py   ← POST /v1/chat/completions
│   │   ├── embeddings.py    ← POST /v1/embeddings
│   │   ├── models.py        ← GET /v1/models
│   │   └── usage.py         ← GET /v1/usage
│   └── middleware/
│       ├── auth.py           ← API key authentication
│       └── logging.py        ← Request logging + timing
├── scripts/
│   ├── run_all_labs.py       ← 8 automated lab experiments
│   ├── run_cloud_labs.sh     ← One-command cloud deploy → run → destroy
│   └── lab_results/          ← Lab output (local/, aws/, azure/)
├── tests/                    ← pytest test suite
├── docs/                     ← Deep documentation
│   ├── ai-engineering/       ← Technical deep dives
│   ├── architecture-and-design/
│   ├── hands-on-labs/        ← 8 hands-on labs with measured results
│   ├── reference/
│   └── setup-and-tooling/
├── infra/
│   ├── aws/main.tf           ← ECS + ElastiCache + RDS
│   └── azure/main.tf         ← Container Apps + Redis + PostgreSQL
├── docker-compose.yml         ← Local dev: app + Redis + PostgreSQL
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## Troubleshooting

### Ollama not running

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags
# If not, start it:
ollama serve
```

### Port already in use

```bash
lsof -i :8100
kill -9 <PID>
poetry run start
```

### Redis connection refused (in-memory fallback)

If Redis is not running, the gateway automatically falls back to in-memory cache and rate limiting. No action needed for local development. For full Redis support:

```bash
docker compose up -d redis
```

### ModuleNotFoundError

```bash
poetry install
```

### Terraform errors

```bash
cd infra/aws   # or infra/azure
terraform init -upgrade
terraform plan -var="cost_limit_eur=5" -var="alert_email=you@example.com"
```
