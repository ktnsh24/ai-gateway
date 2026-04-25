# Terraform Guide — AI Gateway

> **Platforms:** AWS (ECS + ElastiCache + RDS) and Azure (Container Apps + Redis + PostgreSQL)
>
> **Files:** `infra/aws/main.tf`, `infra/azure/main.tf`

---

## Table of Contents

1. [Infrastructure Overview](#1-infrastructure-overview)
2. [AWS Architecture](#2-aws-architecture)
3. [Azure Architecture](#3-azure-architecture)
4. [Deployment](#4-deployment)
5. [Variables](#5-variables)
6. [Outputs](#6-outputs)
7. [Cost Estimates](#7-cost-estimates)
8. [Cross-References](#8-cross-references)

---

## 1. Infrastructure Overview

Both platforms deploy the same application with equivalent infrastructure:

| Component | AWS Service | Azure Service | 🫏 Donkey |
|-----------|------------|---------------|-----------|
| Container runtime | ECS Fargate | Container Apps | 🫏 The hired-by-the-hour stable plot — AWS Fargate or Azure Container Apps puts up the barn so you don't own a server. |
| Container registry | ECR | Container Apps (built-in) | 🫏 The image tack room where the packaged donkey container is stored before being pulled into the live cloud barn. |
| Cache | ElastiCache Redis | Azure Cache for Redis | 🫏 The cloud pigeon-hole shelf that stores pre-written replies and enforces trip quotas across all containerised donkeys. |
| Database | RDS PostgreSQL 16 | PostgreSQL Flexible Server | 🫏 The cloud leather-bound expense ledger that permanently records every cargo-unit cost per provider per request. |
| Networking | VPC + Subnets + ALB | VNet + Container App Environment | 🫏 The stable's fenced paddock and signposted lanes that safely channel cart traffic from the internet to the dispatch desk. |
| Logging | CloudWatch Logs | Azure Monitor | 🫏 The cloud stable CCTV that captures every donkey journey log line for debugging and tachograph review. |
| IAM | IAM Roles + Policies | Managed Identity | 🫏 The stable's permission ledger deciding which donkey container can call which AWS or Azure depot service. |

---

## 2. AWS Architecture

### Resources Created

```
VPC (10.0.0.0/16)
├── Public Subnet A (10.0.1.0/24)
│   └── ALB
├── Public Subnet B (10.0.2.0/24)
│   └── ALB (redundancy)
├── Private Subnet A (10.0.10.0/24)
│   ├── ECS Fargate Tasks
│   ├── ElastiCache Redis
│   └── RDS PostgreSQL
└── Private Subnet B (10.0.11.0/24)
    └── RDS (multi-AZ standby)
```

### Key Resources

| Resource | Type | Size | Purpose | 🫏 Donkey |
|----------|------|------|---------|-----------|
| ECS Cluster | Fargate | 512 CPU / 1024 MiB | Run gateway container | 🫏 The serverless paddock that launches the dispatch-desk container with 512 CPU units and 1 GiB of working memory. |
| ECR Repository | — | — | Store Docker images | 🫏 The cloud tack room where freshly built donkey images are stored until ECS Fargate pulls them into service. |
| ElastiCache | Redis | `cache.t3.micro` | Semantic cache + rate limit | 🫏 The t3.micro fast pigeon-hole shelf that caches pre-written replies and enforces per-key trip quotas in memory. |
| RDS Instance | PostgreSQL 16 | `db.t3.micro` | Cost tracking | 🫏 The t3.micro leather-bound expense ledger that durably records cargo-unit costs for every dispatched donkey request. |
| ALB | Application LB | — | HTTPS termination, routing | 🫏 The stable's front-gate guard that terminates HTTPS and routes incoming carts to the dispatch-desk container. |
| CloudWatch Logs | — | 30d retention | Application logging | 🫏 The 30-day CCTV archive where every dispatch-desk log line is stored for debugging slow or sick donkey trips. |

### IAM Permissions

The ECS task role includes:
```hcl
# Bedrock access for LLM calls
{
  Effect   = "Allow"
  Action   = [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:ListFoundationModels"
  ]
  Resource = "*"
}
```

### Security Groups

| SG | Inbound | From | 🫏 Donkey |
|----|---------|------|-----------|
| ALB SG | 80, 443 | 0.0.0.0/0 | 🫏 The public paddock gate accepting HTTP and HTTPS carts from any courier before forwarding them to the dispatch desk. |
| ECS SG | 8100 | ALB SG | 🫏 The dispatch-desk stable door on port 8100 that only opens for carts already cleared through the front-gate guard. |
| Redis SG | 6379 | ECS SG | 🫏 The pigeon-hole shelf access hatch on port 6379 restricted to the dispatch-desk container so no outsider can tamper. |
| RDS SG | 5432 | ECS SG | 🫏 The expense-ledger vault door on port 5432 that accepts writes only from the trusted dispatch-desk container. |

---

## 3. Azure Architecture

### Resources Created

```
Resource Group (rg-ai-gateway-{env})
├── Container App Environment
│   └── Container App (ai-gateway)
├── Azure Cache for Redis (Basic C0)
├── PostgreSQL Flexible Server (B1ms)
└── VNet + Subnets
```

### Key Resources

| Resource | SKU | Purpose | 🫏 Donkey |
|----------|-----|---------|-----------|
| Container App | 0.5 vCPU / 1Gi | Run gateway container | 🫏 The Azure Container Apps paddock running the dispatch desk on half a vCPU and 1 GiB — right-sized for dev traffic. |
| Azure Cache for Redis | Basic C0 (250MB) | Cache + rate limit | 🫏 The Basic-tier cloud pigeon-hole shelf with 250 MB of fast in-memory space for pre-written replies and trip quotas. |
| PostgreSQL Flexible | B1ms (1 vCore, 2 GiB) | Cost tracking | 🫏 The burstable B1ms expense ledger with 1 vCore and 2 GiB recording every donkey cargo-unit charge in the Azure hub. |

---

## 4. Deployment

### AWS Deployment

```bash
cd infra/aws

# Initialise
terraform init

# Plan
terraform plan \
  -var="environment=dev" \
  -var="project_name=ai-gateway" \
  -var="aws_region=eu-west-1"

# Apply
terraform apply \
  -var="environment=dev" \
  -var="project_name=ai-gateway" \
  -var="aws_region=eu-west-1"

# Build and push Docker image
aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.eu-west-1.amazonaws.com
docker build -t ai-gateway .
docker tag ai-gateway:latest <account>.dkr.ecr.eu-west-1.amazonaws.com/ai-gateway-dev:latest
docker push <account>.dkr.ecr.eu-west-1.amazonaws.com/ai-gateway-dev:latest

# Force new deployment
aws ecs update-service --cluster ai-gateway-dev --service ai-gateway-dev --force-new-deployment
```

### Azure Deployment

```bash
cd infra/azure

# Initialise
terraform init

# Plan
terraform plan \
  -var="environment=dev" \
  -var="project_name=ai-gateway" \
  -var="location=westeurope"

# Apply
terraform apply \
  -var="environment=dev" \
  -var="project_name=ai-gateway" \
  -var="location=westeurope"
```

---

## 5. Variables

### AWS Variables

| Variable | Type | Default | Description | 🫏 Donkey |
|----------|------|---------|-------------|-----------|
| `project_name` | string | — | Project name for resource naming | 🫏 The stable nameplate stamped onto every AWS resource so the ECS barn, Redis shelf, and RDS ledger are grouped together. |
| `environment` | string | — | Environment (dev/stg/prd) | 🫏 The paddock label — dev, stg, or prd — that gates which stable blueprints Terraform stamps into the AWS depot. |
| `aws_region` | string | `eu-west-1` | AWS region | 🫏 The AWS depot location where the barn is erected — eu-west-1 keeps European donkey trips close to the stables. |
| `ecs_cpu` | number | `512` | ECS task CPU units | 🫏 The number of CPU cargo units reserved for each ECS Fargate task running the dispatch-desk container on AWS. |
| `ecs_memory` | number | `1024` | ECS task memory (MiB) | 🫏 The working-memory allocation in MiB for the Fargate dispatch-desk task — 1024 MiB handles typical donkey workloads. |
| `redis_node_type` | string | `cache.t3.micro` | ElastiCache node type | 🫏 The size of the cloud pigeon-hole shelf node — t3.micro is sufficient for dev-level caching and rate-limit counters. |
| `rds_instance_class` | string | `db.t3.micro` | RDS instance class | 🫏 The expense-ledger database size — db.t3.micro stores usage logs for dev traffic without incurring large monthly costs. |

### Azure Variables

| Variable | Type | Default | Description | 🫏 Donkey |
|----------|------|---------|-------------|-----------|
| `project_name` | string | — | Project name for resource naming | 🫏 The stable nameplate used to tag every Azure resource so the Container App, Redis shelf, and PostgreSQL ledger are grouped. |
| `environment` | string | — | Environment (dev/stg/prd) | 🫏 The paddock label — dev, stg, or prd — applied to every Azure hub resource so environments stay cleanly separated. |
| `location` | string | `westeurope` | Azure region | 🫏 The Azure hub datacenter where the barn is erected — westeurope keeps EU donkey trips short and latency low. |
| `container_cpu` | number | `0.5` | Container App CPU | 🫏 The fractional vCPU share allocated to the Container Apps dispatch-desk — 0.5 keeps costs low for development runs. |
| `container_memory` | string | `1Gi` | Container App memory | 🫏 The memory saddle-bag size for the Container Apps dispatch-desk — 1 GiB comfortably handles typical donkey routing workloads. |
| `redis_sku` | string | `Basic` | Azure Redis SKU | 🫏 The tier of the Azure cloud pigeon-hole shelf — Basic SKU gives a single in-memory node for development-grade caching. |
| `postgresql_sku` | string | `B_Standard_B1ms` | PostgreSQL SKU | 🫏 The burstable B1ms SKU for the Azure expense ledger — a single vCore that handles dev-scale cost-tracking writes affordably. |

---

## 6. Outputs

### AWS Outputs

| Output | Description | 🫏 Donkey |
|--------|-------------|-----------|
| `alb_dns_name` | ALB URL to access the gateway | 🫏 The public front-gate address handed back after apply so you can curl the dispatch desk from anywhere on the internet. |
| `ecr_repository_url` | ECR URL for Docker push | 🫏 The tack-room URL where you push the freshly built donkey image so ECS Fargate can pull it into the live barn. |
| `redis_endpoint` | ElastiCache endpoint | 🫏 The connection string pointing to the cloud pigeon-hole shelf so the dispatch desk can read and write cache entries. |
| `rds_endpoint` | RDS endpoint | 🫏 The hostname of the leather-bound expense ledger database so the gateway can log every cargo-unit cost durably. |

### Azure Outputs

| Output | Description | 🫏 Donkey |
|--------|-------------|-----------|
| `container_app_url` | Container App URL | 🫏 The public Container Apps front-gate address returned after apply so you can immediately curl the dispatch desk. |
| `redis_hostname` | Redis hostname | 🫏 The Azure cloud pigeon-hole shelf address so the dispatch desk can store pre-written replies and quota counters. |
| `postgresql_fqdn` | PostgreSQL FQDN | 🫏 The fully-qualified hostname of the Azure expense ledger so every donkey cargo-unit cost is durably recorded. |

---

## 7. Cost Estimates

### AWS (eu-west-1, dev environment)

| Resource | Monthly Cost | Notes | 🫏 Donkey |
|----------|-------------|-------|-----------|
| ECS Fargate (1 task) | ~$12 | 512 CPU, 1024 MiB | 🫏 The monthly hire fee for the serverless barn plot running one dispatch-desk container at 512 CPU units and 1 GiB. |
| ElastiCache t3.micro | ~$12 | Single node | 🫏 The monthly shelf-rental for the cloud pigeon-hole running as a single t3.micro node storing replies and quota counters. |
| RDS t3.micro | ~$15 | Single AZ | 🫏 The monthly storage fee for the single-AZ leather-bound expense ledger recording all donkey cargo-unit costs. |
| ALB | ~$16 | Fixed + LCU hours | 🫏 The monthly gate-keeper charge for the load-balancer front gate routing incoming cart traffic to the dispatch desk. |
| CloudWatch Logs | ~$1 | 1GB/month | 🫏 The monthly CCTV storage bill for shipping 1 GB of stable log lines into the 30-day CloudWatch archive. |
| ECR | ~$1 | Storage | 🫏 The monthly tack-room rental for storing the Docker donkey image in ECR until the next ECS deployment pull. |
| **Total** | **~$57/month** | Dev environment | 🫏 The full monthly stable bill for running a dev dispatch desk, pigeon-hole shelf, expense ledger, and front gate on AWS. |

### Azure (West Europe, dev environment)

| Resource | Monthly Cost | Notes | 🫏 Donkey |
|----------|-------------|-------|-----------|
| Container App | ~$10 | 0.5 vCPU, 1 GiB | 🫏 The monthly paddock rent for the Container Apps dispatch-desk running at 0.5 vCPU with 1 GiB of working memory. |
| Azure Redis Basic C0 | ~$15 | 250 MB | 🫏 The monthly shelf-rental for the Basic C0 Azure cloud pigeon-hole holding 250 MB of pre-written replies in memory. |
| PostgreSQL B1ms | ~$13 | 1 vCore | 🫏 The monthly ledger-storage charge for the burstable B1ms Azure expense log recording all donkey cargo-unit costs. |
| **Total** | **~$38/month** | Dev environment | 🫏 The combined monthly Azure stable bill for the Container Apps barn, cloud pigeon-hole shelf, and expense ledger in dev. |

---

## 8. Cross-References

| Topic | Document | 🫏 Donkey |
|-------|----------|-----------|
| Architecture | [Architecture](../architecture-and-design/architecture.md) | 🫏 The master stable blueprint mapping every component, donkey path, and data flow from front door to expense ledger. |
| Docker (local) | [Docker Compose Guide](docker-compose-guide.md) | 🫏 The portable mini-stable kit guide for spinning up a local dispatch desk, pigeon-hole shelf, and expense ledger fast. |
| Getting started | [Getting Started](getting-started.md) | 🫏 The stable hand's orientation guide from installing Python all the way to dispatching your first donkey request. |
| CI/CD pipeline | `.github/workflows/ci.yml` | 🫏 The automated stable runner that builds, tests, and pushes the donkey container image on every code change. |
