# Infrastructure (Terraform) — Deep Dive

> `infra/aws/` and `infra/azure/` — every cloud resource the gateway needs, defined as Terraform HCL. Two parallel module trees (one per cloud) plus a shared "kill switch" pattern that destroys everything when a budget cap is breached.

> **Related docs:**
>
> - [Terraform Guide](../setup-and-tooling/terraform-guide.md) — `terraform init/plan/apply/destroy` runbook
> - [CI/CD Explained](cicd-explained.md) — the GitHub Actions pipelines that drive these modules
> - [Architecture Overview](architecture.md) — what the application expects from the infra
> - [Cost Analysis](../ai-engineering/cost-analysis.md) — projected unit pricing per resource
> - [Monitoring](../reference/monitoring.md) — what observability runs on top of these resources

---

## Table of Contents

- [What's in infra/](#whats-in-infra)
- [Terraform Layout](#terraform-layout)
- [AWS Resources](#aws-resources)
- [Azure Resources](#azure-resources)
- [Apply / Destroy Flow](#apply--destroy-flow)
- [Cost Guardrails](#cost-guardrails)
- [Drift Detection](#drift-detection)
- [Courier Explainer](#courier-explainer)

---

## What's in infra/

```
infra/
├── aws/                       # AWS module — applied with `cd infra/aws && terraform apply`
│   ├── terraform.tf           # Required version + AWS provider + (commented) S3 backend
│   ├── variables.tf           # aws_region, environment, app_name, image_tag, cost_limit_eur, alert_email
│   ├── locals.tf              # prefix = "${app_name}-${environment}"
│   ├── networking.tf          # default VPC + subnets data sources, security group on port 8100
│   ├── ecr.tf                 # ECR repo + lifecycle policy (untagged → expire in 14 days)
│   ├── ecs.tf                 # ECS cluster, Fargate task definition (512 CPU / 1024 MB)
│   ├── iam.tf                 # ECS execution role + ECS task role + Bedrock InvokeModel policy
│   ├── elasticache.tf         # ElastiCache Redis (cache.t3.micro, single node, redis7)
│   ├── rds.tf                 # RDS PostgreSQL 16 (db.t3.micro, 20 GB, in default VPC)
│   ├── cloudwatch.tf          # CloudWatch log group `/ecs/${prefix}`, 30-day retention
│   ├── budget.tf              # AWS Budget + SNS + Lambda budget killer
│   ├── budget_killer_lambda/  # Python 3.11 Lambda that destroys all tagged resources
│   └── outputs.tf             # ecs_cluster_name, ecr_repository_url, redis_endpoint, postgres_endpoint
│
└── azure/                     # Azure module — applied with `cd infra/azure && terraform apply`
    ├── terraform.tf           # Required version + azurerm provider
    ├── variables.tf           # location, environment, app_name, image_tag, cost_limit_eur, alert_email
    ├── locals.tf              # prefix = "${app_name}-${environment}"
    ├── resource_group.tf      # rg-${prefix}
    ├── container_app.tf       # Container App Environment + Container App (0.5 vCPU / 1 GiB)
    ├── postgresql.tf          # Flexible Server B_Standard_B1ms + database `ai_gateway`
    ├── redis.tf               # Azure Cache for Redis (Basic C0, TLS 1.2 minimum)
    ├── budget.tf              # Consumption Budget + Automation Account runbook killer
    └── outputs.tf
```

The two trees deliberately mirror each other: a container runtime, a managed Redis, a managed Postgres, a budget guard, and a kill-switch automation. Either cloud can be applied or destroyed independently.

- 🚚 **Courier:** Two parallel sets of infrastructure blueprints — one for the AWS depot, one for the Azure hub — drawn so closely that any new wing on the AWS side has a matching wing on the Azure side.

---

## Terraform Layout

| File | Purpose | 🚚 Courier |
|------|---------|-----------|
| `terraform.tf` | Pin Terraform version + provider; backend block is commented (default = local state for the lab) | The blueprint cover sheet — fixes which version of the drafting tools and which printer to use. |
| `variables.tf` | Inputs the operator overrides per environment | Adjustment dials at the top of the blueprint — region, environment tag, image to deploy, monthly fuel budget. |
| `locals.tf` | Computes `prefix = "${app_name}-${environment}"` so every resource is named consistently | Master stencil that names every door, wing, and cable with the same prefix so nothing collides between dev and stg. |
| `outputs.tf` | Exposes endpoints (Redis address, Postgres FQDN, container app URL, ECR registry) | Index card pinned at the door listing the new addresses for every cable and pipe the dispatch desk needs. |
| Per-resource files | One concern per file (`ecs.tf`, `rds.tf`, …) so reviewers see only what changed | One blueprint sheet per depot wing, kept separate so a renovation in one wing doesn't churn the whole depot. |

Modules are intentionally *not* split into reusable child modules — the gateway has exactly two deployment targets and the per-cloud root module is small enough to read end-to-end. Reusability is provided by mirroring the two trees, not by abstraction.

---

## AWS Resources

| Resource | Type | Sizing | Purpose | 🚚 Courier |
|----------|------|--------|---------|-----------|
| `aws_ecs_cluster.gateway` | ECS cluster | Container Insights enabled | Hosts the Fargate task running the gateway image | Front-yard plot where the dispatch shed actually stands and the couriers start their shifts. |
| `aws_ecs_task_definition.gateway` | Fargate task | 512 CPU, 1024 MB, port 8100 | Pulls the container, injects `CLOUD_PROVIDER=aws`, Redis URL, Postgres URL | Hiring contract for the dispatch crew — staff size, shift length, and the front door they answer at. |
| `aws_ecr_repository.gateway` | ECR repo | `MUTABLE` tags + scan-on-push + 14-day untagged GC | Stores Docker images pushed by CI | Locker room where every new dispatch-desk uniform is hung; old unused ones are tossed after two weeks. |
| `aws_elasticache_cluster.redis` | ElastiCache | `cache.t3.micro`, single node, redis7 | Powers semantic cache + rate limiter | The pickup locker shelf and the daily-dispatch-quota tally board, both stored in fast in-memory cubbies. |
| `aws_db_instance.postgres` | RDS PostgreSQL 16 | `db.t3.micro`, 20 GB, private | Stores the cost-tracking row log | The leather-bound expense ledger kept in a locked back office, written to on every delivery. |
| `aws_security_group.gateway` | SG | Inbound `0.0.0.0/0:8100`, all egress | Front-door firewall on the gateway container | Front-door bouncer rules — open the dispatch window to the world, let couriers roam to any remote depot. |
| `aws_iam_role.ecs_execution` | IAM role | `AmazonECSTaskExecutionRolePolicy` attached | Lets ECS pull from ECR + ship logs to CloudWatch | Janitor's keys — opens the locker room and the log shed, nothing more. |
| `aws_iam_role.ecs_task` | IAM role | Inline `bedrock:InvokeModel*` policy | Lets the running container call AWS Bedrock | Courier's parcel pass — the only badge that actually grants access to the AWS Bedrock remote depot. |
| `aws_cloudwatch_log_group.gateway` | Log group | 30-day retention | Container stdout/stderr destination | The log shed — every dispatcher's voice memo is filed here for thirty days then shredded automatically. |
| `aws_budgets_budget.cost_limit` | Budget | EUR limit (default `5`), tag-filtered | Triggers SNS at 80% + 100% of the cap | Budget owner's monthly fuel-budget alarm — quietly chimes at 80%, screams at 100%. |
| `aws_lambda_function.budget_killer` | Lambda | Python 3.11, 128 MB, 5-minute timeout | Subscribed to the SNS topic; tears down ECS, RDS, ElastiCache, ECR, S3 when triggered | Emergency shutdown process on a pager — once paged, walks the corridors and unplugs every wing the project owns. |

The IAM split between `ecs_execution` (platform plumbing) and `ecs_task` (application secrets, Bedrock) is the standard ECS pattern; the application never holds AWS keys at rest.

---

## Azure Resources

| Resource | Type | Sizing | Purpose | 🚚 Courier |
|----------|------|--------|---------|-----------|
| `azurerm_resource_group.gateway` | Resource group | `rg-${prefix}` | Container for every other Azure resource | Plot of land the Azure depot is built on — every wing must sit inside this fenced area. |
| `azurerm_container_app_environment.gateway` | Container Apps env | Default | Multi-tenant runtime for the container app | Shared dispatch-shed compound where multiple stables can co-exist on the same yard. |
| `azurerm_container_app.gateway` | Container App | 0.5 vCPU, 1 GiB, ingress on 8100 | Runs the gateway image, single revision mode | Hiring contract for the Azure-side dispatch crew, with a single live shift schedule per deploy. |
| `azurerm_redis_cache.gateway` | Azure Cache for Redis | Basic C0, TLS 1.2 | Powers semantic cache + rate limiter | The Azure-side pickup locker shelf and daily-dispatch-quota board, served over an encrypted internal cable. |
| `azurerm_postgresql_flexible_server.gateway` | Postgres Flexible Server | `B_Standard_B1ms`, 32 GB | Cost ledger storage | The Azure-side leather expense ledger, locked in a back office in zone 1. |
| `azurerm_postgresql_flexible_server_database.gateway` | Database | `ai_gateway`, UTF8 | Application schema container | Index tab inside the ledger reserved for the gateway's own rows. |
| `azurerm_consumption_budget_resource_group` *(in `budget.tf`)* | Consumption budget | EUR limit (default `5`) | Watches the resource group's spend | Azure-side fuel-budget alarm scoped to this single fenced plot. |
| `azurerm_automation_account.budget_killer` | Automation account | Basic SKU | Hosts the kill-switch runbook | Pager on the wall outside the office — wakes the emergency shutdown process when the budget alarm fires. |
| `azurerm_automation_runbook.kill_resources` | PowerShell runbook | `Remove-AzResource` on every resource in the group | Deletes everything in the resource group when paged | The exact destruction checklist — every wing of the resource-group plot is unplugged in dependency order. |

---

## Apply / Destroy Flow

```
Operator clones repo, picks a cloud, exports vars
    │
    ▼
cd infra/aws    (or infra/azure)
    │
    ▼
terraform init                 (downloads provider + state)
terraform plan -out plan.bin   (reads current state → diff vs HCL)
terraform apply plan.bin       (creates/updates resources)
    │
    ▼
outputs printed — gateway is reachable on the container app's URL
    │
    ▼ (when the lab is over OR the budget killer fires)
terraform destroy              (deletes everything the module owns)
```

The CI pipelines (`deploy-aws.yml`, `deploy-azure.yml`) run the same three commands inside a short-lived runner, with credentials sourced from the GitHub environment via OIDC (`id-token: write`). No long-lived cloud keys are stored in CI.

---

## Cost Guardrails

| Layer | Mechanism | Effective behaviour | 🚚 Courier |
|-------|-----------|---------------------|-----------|
| Sizing | `cache.t3.micro`, `db.t3.micro`, `B_Standard_B1ms`, 0.5 vCPU container | Smallest paid SKUs available on each cloud — €1–3/day at idle | Smallest stalls you can rent at each depot — enough room for a single courier, no luxury pasture. |
| Tagging | `default_tags { project, environment, managed_by="terraform" }` on AWS; explicit tags on Azure resources | Lets the budget filter on `user:project=ai-gateway` | Coloured tag on every wing so the accountant can grep the bill for `project = ai-gateway`. |
| Budget alert | AWS Budget + Azure Consumption Budget, default cap **EUR 5** | SNS / Action Group fires at 80% and 100% | Owner's wall-clock alarm — chimes early at 80% so the depot hand can investigate calmly. |
| Kill switch | AWS Lambda + Azure Automation runbook subscribed to the 100% alert | Tears down ECS / Container App, RDS / Postgres, ElastiCache / Redis, ECR | Emergency shutdown process who unplugs every wing of the project the moment the 100% alarm screams. |
| ECR / ACR lifecycle | Untagged image GC after 14 days (AWS) | Prevents image storage from creeping past the budget | Locker-room sweep every fortnight — anonymous uniforms get tossed before they pile up. |

---

## Drift Detection

State management for this lab is intentionally **local** (`terraform.tfstate` next to the module). The recommended remote-backend block is present but commented out in `infra/aws/terraform.tf` so a team setup can flip it on without re-architecting. Drift detection in this lab relies on:

| Signal | How it surfaces drift | 🚚 Courier |
|--------|----------------------|-----------|
| `terraform plan` in CI | Run on every PR that touches `infra/**` (recommended addition) — non-empty diff → reviewer sees changes | Surveyor walks the plot before the meeting and flags every wall that doesn't match the blueprint. |
| Provider tags | `default_tags` mark every AWS resource as `managed_by=terraform`; Azure resources carry the same tag explicitly | Every wing wears a "terraform-built" badge so a manually-added wing stands out as untagged. |
| Budget killer outputs | The Lambda/runbook log every resource it deleted; replaying after a kill confirms which wings actually existed | The emergency shutdown process keeps a written list of every wing they unplugged for the morning post-mortem. |
| Outputs vs reality | `terraform output` prints the live endpoints; mismatch with what the running container holds in `REDIS_URL` / `DATABASE_URL` indicates drift | Daily check that the door numbers on the index card still match the addresses the dispatcher is actually dialling. |

For production use, switch the commented S3 + DynamoDB locking backend on (AWS) and introduce an equivalent Azure storage backend, then add a scheduled `terraform plan` job to fail when drift appears.

---

## 🚚 Courier Explainer

`infra/` is the **set of infrastructure blueprints**, not the depot itself. Two complete blueprint folders sit side by side — one labelled "AWS depot", one labelled "Azure hub" — and either can be raised, demolished, or rebuilt independently with a single `terraform apply` / `terraform destroy`.

Every wing is drawn for the same reason on both clouds: a yard for the gateway container (ECS cluster / Container Apps environment), the gateway service itself (Fargate task / Container App), a cache (ElastiCache / Azure Redis), a cost-tab database (RDS / Flexible Server), an image registry (ECR / ACR), keys for the right model provider (IAM roles / managed identity), and a log stream.

Glued onto both blueprints is an **owner-side cost guard**: a budget alarm at €5/month that pages an emergency automated pipeline. The runbook is brutal — when the 100% alarm screams, every wing the project owns is unplugged. That guarantee is what keeps the lab safe to leave running while you study other repos: nothing can quietly overshoot the monthly budget.
