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

| Component | AWS Service | Azure Service |
|-----------|------------|---------------|
| Container runtime | ECS Fargate | Container Apps |
| Container registry | ECR | Container Apps (built-in) |
| Cache | ElastiCache Redis | Azure Cache for Redis |
| Database | RDS PostgreSQL 16 | PostgreSQL Flexible Server |
| Networking | VPC + Subnets + ALB | VNet + Container App Environment |
| Logging | CloudWatch Logs | Azure Monitor |
| IAM | IAM Roles + Policies | Managed Identity |

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

| Resource | Type | Size | Purpose |
|----------|------|------|---------|
| ECS Cluster | Fargate | 512 CPU / 1024 MiB | Run gateway container |
| ECR Repository | — | — | Store Docker images |
| ElastiCache | Redis | `cache.t3.micro` | Semantic cache + rate limit |
| RDS Instance | PostgreSQL 16 | `db.t3.micro` | Cost tracking |
| ALB | Application LB | — | HTTPS termination, routing |
| CloudWatch Logs | — | 30d retention | Application logging |

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

| SG | Inbound | From |
|----|---------|------|
| ALB SG | 80, 443 | 0.0.0.0/0 |
| ECS SG | 8100 | ALB SG |
| Redis SG | 6379 | ECS SG |
| RDS SG | 5432 | ECS SG |

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

| Resource | SKU | Purpose |
|----------|-----|---------|
| Container App | 0.5 vCPU / 1Gi | Run gateway container |
| Azure Cache for Redis | Basic C0 (250MB) | Cache + rate limit |
| PostgreSQL Flexible | B1ms (1 vCore, 2 GiB) | Cost tracking |

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

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `project_name` | string | — | Project name for resource naming |
| `environment` | string | — | Environment (dev/stg/prd) |
| `aws_region` | string | `eu-west-1` | AWS region |
| `ecs_cpu` | number | `512` | ECS task CPU units |
| `ecs_memory` | number | `1024` | ECS task memory (MiB) |
| `redis_node_type` | string | `cache.t3.micro` | ElastiCache node type |
| `rds_instance_class` | string | `db.t3.micro` | RDS instance class |

### Azure Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `project_name` | string | — | Project name for resource naming |
| `environment` | string | — | Environment (dev/stg/prd) |
| `location` | string | `westeurope` | Azure region |
| `container_cpu` | number | `0.5` | Container App CPU |
| `container_memory` | string | `1Gi` | Container App memory |
| `redis_sku` | string | `Basic` | Azure Redis SKU |
| `postgresql_sku` | string | `B_Standard_B1ms` | PostgreSQL SKU |

---

## 6. Outputs

### AWS Outputs

| Output | Description |
|--------|-------------|
| `alb_dns_name` | ALB URL to access the gateway |
| `ecr_repository_url` | ECR URL for Docker push |
| `redis_endpoint` | ElastiCache endpoint |
| `rds_endpoint` | RDS endpoint |

### Azure Outputs

| Output | Description |
|--------|-------------|
| `container_app_url` | Container App URL |
| `redis_hostname` | Redis hostname |
| `postgresql_fqdn` | PostgreSQL FQDN |

---

## 7. Cost Estimates

### AWS (eu-west-1, dev environment)

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| ECS Fargate (1 task) | ~$12 | 512 CPU, 1024 MiB |
| ElastiCache t3.micro | ~$12 | Single node |
| RDS t3.micro | ~$15 | Single AZ |
| ALB | ~$16 | Fixed + LCU hours |
| CloudWatch Logs | ~$1 | 1GB/month |
| ECR | ~$1 | Storage |
| **Total** | **~$57/month** | Dev environment |

### Azure (West Europe, dev environment)

| Resource | Monthly Cost | Notes |
|----------|-------------|-------|
| Container App | ~$10 | 0.5 vCPU, 1 GiB |
| Azure Redis Basic C0 | ~$15 | 250 MB |
| PostgreSQL B1ms | ~$13 | 1 vCore |
| **Total** | **~$38/month** | Dev environment |

---

## 8. Cross-References

| Topic | Document |
|-------|----------|
| Architecture | [Architecture](../architecture-and-design/architecture.md) |
| Docker (local) | [Docker Compose Guide](docker-compose-guide.md) |
| Getting started | [Getting Started](getting-started.md) |
| CI/CD pipeline | `.github/workflows/ci.yml` |
