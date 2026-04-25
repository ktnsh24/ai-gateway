# CI/CD — Deep Dive

> `Dockerfile` + `.github/workflows/` — three GitHub Actions workflows that lint, test, build, and (manually) deploy the gateway to AWS Fargate or Azure Container Apps.

> **Related docs:**
>
> - [Infrastructure Explained](infra-explained.md) — the Terraform these pipelines apply
> - [Terraform Guide](../setup-and-tooling/terraform-guide.md) — running the same commands locally
> - [Architecture Overview](architecture.md) — what's actually in the deployed image
> - [Testing](../ai-engineering/testing.md) — what `pytest` runs in CI

---

## Table of Contents

- [Pipeline Overview](#pipeline-overview)
- [Per-Stage Breakdown](#per-stage-breakdown)
- [Secrets Management](#secrets-management)
- [Branch Strategy](#branch-strategy)
- [Failure Recovery](#failure-recovery)
- [Courier Explainer](#courier-explainer)

---

## Pipeline Overview

```
.github/workflows/
├── ci.yml           # PRs + pushes to main/develop  → lint → test → docker build
├── deploy-aws.yml   # workflow_dispatch              → build → push to ECR  → terraform apply → ECS update
└── deploy-azure.yml # workflow_dispatch              → build → push to ACR  → terraform apply → Container App update
```

| Workflow | Trigger | Stages | 🚚 Courier |
|----------|---------|--------|-----------|
| `ci.yml` | `push` to `main`/`develop`, `pull_request` to `main` | Lint → Test → Docker Build | Automated pipeline who runs the report card on every shift change before letting anyone ride. |
| `deploy-aws.yml` | `workflow_dispatch` (manual, env = `dev` or `stg`) | OIDC login → ECR build & push → `terraform apply` → ECS service update | Same robot hand on the AWS side — only acts when an operator pushes the deploy button. |
| `deploy-azure.yml` | `workflow_dispatch` (manual, env = `dev` or `stg`) | Azure login → ACR build & push → `terraform apply` → Container App update | Same robot hand on the Azure hub side — also strictly manual to keep cloud spend on a leash. |

CI is automatic on every push or PR; deploys are intentionally manual and bound to a GitHub Environment so reviewers can gate them.

---

## Per-Stage Breakdown

### `ci.yml` — automatic on every push/PR

| Job | Image / runtime | Steps | What it asserts | 🚚 Courier |
|-----|-----------------|-------|-----------------|-----------|
| `lint` | `ubuntu-latest` + Python 3.12 | `pip install ruff` → `ruff check src/ tests/` | Source + test dirs are Ruff-clean | Quick uniform inspection — collar straight, boots polished — before any other check runs. |
| `test` | `ubuntu-latest` + Python 3.12 + Poetry 1.8.4 | `poetry install` → `poetry run pytest tests/ -v --cov=src --cov-report=term-missing` with `CLOUD_PROVIDER=local` and all gateway features (cache/rate-limit/cost-tracking/api-keys) **disabled** | Pure-Python tests pass with the in-memory backends; no Redis or PostgreSQL needed in CI | Dry-run shift in an empty test environment — courier, dispatcher, and ledger each tested without booting Redis or Postgres. |
| `docker` | `ubuntu-latest` | `docker build -t ai-gateway:ci .` | The `Dockerfile` still produces a runnable image with the current `pyproject.toml` | Build the dispatch-desk uniform from the latest pattern and confirm it actually fits the staff. |

The `test` job depends on `lint`, and `docker` depends on `test`. A red lint fails the whole pipeline before any test ever runs.

### `deploy-aws.yml` — manual `workflow_dispatch`

```
1. actions/checkout@v4
2. aws-actions/configure-aws-credentials@v4   ← OIDC, no static keys
        role-to-assume = ${{ secrets.AWS_ROLE_ARN }}
3. aws-actions/amazon-ecr-login@v2
4. docker build → docker push  (tagged with $GITHUB_SHA + retagged latest)
5. cd infra/aws && terraform init
   terraform apply -auto-approve
        -var environment=$inputs.environment
        -var image_tag=$GITHUB_SHA
6. aws ecs update-service --force-new-deployment
        --cluster ai-gateway-${env}
        --service ai-gateway
```

The `environment: aws-${env}` line binds the job to a GitHub Environment, so required reviewers / wait timers / restricted secrets all kick in before step 1 runs.

### `deploy-azure.yml` — manual `workflow_dispatch`

```
1. actions/checkout@v4
2. azure/login@v2                              ← OIDC: client-id, tenant-id, subscription-id
3. az acr login --name ${{ secrets.ACR_NAME }}
4. docker build → docker push  ($SHA tag)
5. cd infra/azure && terraform init
   terraform apply -auto-approve
        -var environment=$inputs.environment
        -var image_tag=$GITHUB_SHA
6. az containerapp update --image ...:$GITHUB_SHA
```

Same shape as the AWS workflow, deliberately mirrored to keep the per-cloud differences obvious to a reader.

| Stage | AWS workflow | Azure workflow | 🚚 Courier |
|-------|--------------|----------------|-----------|
| Auth | OIDC role assumption | OIDC federated identity | Robot hand presents a temporary badge each shift; never carries a permanent cloud key. |
| Image registry | ECR (image scan on push) | ACR | Two locker rooms, one per depot — the hand drops the new uniform in whichever the operator chose. |
| IaC | `terraform init && apply -auto-approve` in `infra/aws` | Same in `infra/azure` | Same drafting tools applied to whichever blueprint set the operator pointed at. |
| Runtime update | `aws ecs update-service --force-new-deployment` | `az containerapp update --image …` | Hand walks into the dispatch shed and tells the crew to swap into the freshly hung uniform mid-shift. |

---

## Secrets Management

| Secret | Where stored | Used by | 🚚 Courier |
|--------|--------------|---------|-----------|
| `AWS_ROLE_ARN` | GitHub Environment `aws-dev` / `aws-stg` | `aws-actions/configure-aws-credentials` | Address of the AWS role badge the robot hand asks for at the start of every AWS shift. |
| `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` | GitHub Environment `azure-dev` / `azure-stg` | `azure/login` | Three-piece Azure identity card the robot hand flashes to start an Azure shift. |
| `ACR_NAME` | GitHub Environment | `az acr login` | Name on the Azure-side locker room door so the hand finds the right place to hang the new uniform. |
| Application keys (`GATEWAY_API_KEYS`, `MASTER_API_KEY`) | **Not** in CI — injected at runtime via Terraform / cloud secret manager | The running container | Permission-slip stamp lives in the dispatch shed's safe; the robot hand never carries it. |

There is no static cloud credential anywhere in the repo. OIDC is the only auth path the deploy workflows use, and `id-token: write` permission is the entry-point that makes that possible.

> Note: the lab Terraform inlines a development PostgreSQL password (`gateway-dev-password` in AWS, `GatewayDev2026!` in Azure) and notes "Use Secrets Manager / Key Vault in production". For any non-lab use, swap those literals for `aws_secretsmanager_secret` / `azurerm_key_vault_secret` references before applying.

---

## Branch Strategy

| Branch | What runs | What deploys | 🚚 Courier |
|--------|-----------|--------------|-----------|
| feature branches | Nothing (no PR open yet) | Nothing | Trainee schedules a shift but the robot hand only checks them in once they request a review. |
| open PR → `main` | `ci.yml` (lint + test + docker build) | Nothing | Report card runs on every push to the PR; merge gate stays shut until it's green. |
| push to `develop` | `ci.yml` | Nothing | Integration branch — report card runs but no deploy fires automatically. |
| push to `main` | `ci.yml` | Nothing automatic | Even a green main does not auto-deploy; an operator still presses the deploy button. |
| Manual dispatch on `deploy-aws.yml` / `deploy-azure.yml` | The chosen deploy workflow | Selected env (`dev` or `stg`) | Operator hands the robot hand a deploy ticket pinned to a specific environment. |

There is intentionally no `prd` environment in the workflow inputs (`type: choice` lists only `dev` and `stg`). A production rollout requires deliberately editing the workflow — a friction-on-purpose design that matches the €5/month budget guard.

---

## Failure Recovery

| Failure | Symptom in CI | Recovery | 🚚 Courier |
|---------|---------------|----------|-----------|
| Lint regression | `lint` job red on PR | Run `ruff check src/ tests/ --fix` locally, push the fix | Inspector spots a wrinkled collar; trainee straightens it before stepping back in line. |
| Test regression | `test` job red on PR | Reproduce locally with `poetry run pytest -v`; the in-memory backends mean no Docker is needed | Dry-run shift exposed a misbehaving courier; rehearse in the empty test environment until it passes. |
| Docker build fail | `docker` job red, usually after a `pyproject.toml` change | `docker build -t ai-gateway:dev .` locally, fix dependency pin | Tailor's pattern broke after a fabric change; cut a sample uniform and verify it fits before pushing. |
| ECR / ACR push fail | Deploy job red at "Build and push" step | Check OIDC role permissions on the GitHub Environment; re-run the workflow | Robot hand's badge was missing a stamp; fix the badge then ask for a new shift slot. |
| `terraform apply` fail | Deploy job red at "Deploy Terraform" step | Read the error in the runner log; fix HCL or reconcile drift locally with `terraform plan` | Surveyor refuses to build the wing because the blueprint contradicts the existing wall; reconcile before re-trying. |
| `update-service` / `containerapp update` fail | Deploy job red at the runtime step but image is in the registry | Re-run the workflow (idempotent); or run the update CLI command manually | Crew refused the new uniform mid-shift; second nudge usually takes, otherwise hand the swap order in person. |
| Budget killer fired between deploys | Workflow may target a deleted resource | Re-run the deploy workflow — Terraform recreates everything; expect a few minutes of cold start | Emergency shutdown process demolished the wing; robot hand re-applies the blueprint and the dispatch desk is back. |

A failed deploy never leaves a half-deployed image without a Terraform record, because `terraform apply` runs *before* the runtime update — if Terraform fails, the running task definition / container app revision is unchanged.

---

## 🚚 Courier Explainer

CI/CD is the **automated pipeline**. On every code push it runs a fixed report-card routine — lint (Ruff), test (`pytest` with in-memory backends), and image build (`docker build`). A red mark anywhere stops the merge.

Deploys are deliberately a separate, **manual** lever. An operator hands the automated pipeline a deploy ticket that says either "AWS dev/stg" or "Azure dev/stg". The hand:

1. flashes a temporary OIDC badge at the chosen cloud (no permanent keys in the repo),
2. pushes the freshly built image to the right registry (ECR or ACR),
3. re-applies the infrastructure blueprints (`terraform apply`) so the depot layout matches the current HCL,
4. tells the running gateway service to roll over to the new image.

Production is intentionally not on the dropdown — anyone wanting a production deploy has to edit the workflow by hand. That, plus the €5 budget killer, keeps a single accidental click from running up a real bill.
