---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
title: Full-stack GCP MVP implementation
date: 2026-08-31
---

# Full-stack GCP MVP implementation

## Goal

Build and deploy a production-shaped Coverset vertical slice on GCP:

1. upload or reference a screenplay,
2. run Gemini breakdown into candidate scene records,
3. review/accept schedulable candidates,
4. call the existing deterministic `coverset.solver` scheduling engine,
5. persist the board and diagnostics,
6. display the result in a web UI,
7. provision the dev cloud footprint with Terraform.

## Scope boundary

This pass creates a **dev MVP**, not the complete product in `SPEC.md`.

In scope:

- FastAPI backend wrapping the existing Python domain modules.
- Cloud SQL Postgres schema and local SQLite-compatible repository tests.
- Cloud Run deployable API and worker images.
- Minimal Next.js frontend for the screenplay-to-board flow.
- Terraform for GCP dev resources.
- Cloud Build remote image build/deploy path.
- Secret Manager references for Gemini/Parallel/API runtime values.
- GCS screenplay/artifact storage.
- BigQuery audit/telemetry dataset.

Out of scope for this pass:

- Multi-user org/billing model beyond private Cloud Run access.
- Full auth product UX; private Cloud Run is the dev access boundary.
- Locked-day replan implementation (UC-03) beyond schema placeholders.
- Full constraint-agent completion (CON-001/002/003), except interfaces/jobs shaped for it.
- Gemini Enterprise Agent Engine migration; current runtime keeps model calls behind protocols.

## Key decisions

### D-001: Keep the scheduler deterministic and central

`coverset.solver.solve()` remains the only board-deciding component. Gemini produces candidates; Parallel produces grounded evidence; humans/validators activate typed records; the scheduler decides.

### D-002: Cloud SQL Postgres is the system of record

Use Postgres for productions, assets, candidate scenes, accepted scenes, schedule runs, boards, assignments, and audit events. BigQuery is append-only analytics/export only, not transactional state.

### D-003: Worker owns long-running jobs

Breakdown and scheduling can exceed interactive request budgets and must produce durable run state. The API records/starts jobs; the worker executes them. For the first dev slice, endpoints may support synchronous local execution while preserving job records.

### D-004: Private Cloud Run first

Deploy API/web/worker privately for dev validation. Public auth/Firebase can be added after the core path is stable.

### D-005: Cloud Build only

Local Docker is not required. Cloud Build builds API, worker, and web images and pushes to Artifact Registry.

## System shape

```text
apps/web (Next.js)
  -> coverset.api (FastAPI on Cloud Run)
      -> Cloud SQL Postgres
      -> GCS screenplay/artifact bucket
      -> Cloud Tasks/PubSub-ready job records
      -> coverset.worker (Cloud Run worker/job)
          -> Gemini via coverset.breakdown.GeminiBreakdown
          -> Parallel via coverset.grounding
          -> coverset.solver.solve
      -> BigQuery audit/telemetry export
```

## Implementation units

### IU-001 Terraform dev foundation

Files:

- `infra/terraform/providers.tf`
- `infra/terraform/variables.tf`
- `infra/terraform/main.tf`
- `infra/terraform/outputs.tf`
- `infra/terraform/dev.auto.tfvars.example`
- `scripts/bootstrap_gcp_secrets.sh`
- `scripts/deploy_dev.sh`

Tests/checks:

- `terraform fmt -check infra/terraform`
- `terraform -chdir=infra/terraform init`
- `terraform -chdir=infra/terraform validate`
- `terraform -chdir=infra/terraform plan`

### IU-002 Backend API and DB layer

Files:

- `src/coverset.api/main.py`
- `src/coverset.api/config.py`
- `src/coverset.api/db.py`
- `src/coverset.api/models.py`
- `src/coverset.api/schemas.py`
- `src/coverset.api/services.py`
- `src/coverset.api/storage.py`
- `tests/test_api.py`

Tests/scenarios:

- Health endpoint returns app metadata.
- Production creation seeds demo roster/location data.
- Screenplay upload persists asset metadata.
- Breakdown endpoint creates candidate scenes from an injected/offline agent.
- Candidate acceptance persists an active scene JSON snapshot.
- Solve endpoint calls `coverset.solver.solve` and persists rendered stripboard.

### IU-003 Worker

Files:

- `src/coverset.worker/main.py`
- `src/coverset.worker/jobs.py`
- `tests/test_worker.py`

Tests/scenarios:

- Worker can run a pending breakdown job.
- Worker can run a pending scheduling job.
- Failed jobs retain error text and do not disappear.

### IU-004 Frontend MVP

Files:

- `apps/web/package.json`
- `apps/web/next.config.js`
- `apps/web/app/page.tsx`
- `apps/web/app/globals.css`
- `apps/web/lib/api.ts`
- `apps/web/Dockerfile`

Tests/checks:

- `npm --prefix apps/web install`
- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`

### IU-005 Containers and Cloud Build

Files:

- `Dockerfile.api`
- `Dockerfile.worker`
- `cloudbuild.yaml`
- `.dockerignore`

Tests/checks:

- Cloud Build builds all images without local Docker.
- Deployment uses private Cloud Run services.
- Smoke test can call API with an identity token.

## Setup requirements

Already supplied/confirmed:

- GCP project: `spoonepa`
- Region: `us-central1`
- Billing: enabled
- Cloud Build remote builds
- Private Cloud Run access
- Secret Manager wiring for Gemini and Parallel runtime values

User still should rotate the pasted Gemini key before production-like use, then place the rotated values in Secret Manager rather than repo-local files.

## Verification ladder

1. `uv run pytest`
2. `uv run pytest tests/test_live_breakdown.py -m live`
3. `terraform fmt -check infra/terraform`
4. `terraform -chdir=infra/terraform validate`
5. `scripts/bootstrap_gcp_secrets.sh`
6. `scripts/deploy_dev.sh`
7. API smoke: `/readyz`
8. E2E smoke: production -> screenplay -> breakdown -> accept -> solve -> board

## Risks

- Cloud SQL can take several minutes and costs money even in dev sizing.
- Secret values must not be committed or stored in Terraform state.
- Private Cloud Run web UI requires identity-token-aware access; easiest dev proof may be API smoke first.
- Full ConstraintAgent remains separate; the deployed shape reserves the job pathway for it.
