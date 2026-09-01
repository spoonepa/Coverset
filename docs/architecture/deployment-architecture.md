# Coverset deployment architecture

## Environment

Initial target:

- GCP project: `spoonepa`
- Region: `us-central1`
- Access: private Cloud Run
- Build path: Cloud Build remote builds, not local Docker
- Infrastructure: Terraform-managed dev resources

## Deployed services

```text
Cloud Run: coverset-web-dev
Cloud Run: coverset-api-dev
Cloud Run: coverset-worker-dev
Cloud SQL: coverset-dev Postgres
GCS: screenplay/artifact buckets
Artifact Registry: coverset containers
Secret Manager: API/model/database secrets
BigQuery: coverset analytics dataset
```

## Request path

```text
User browser
  -> coverset-web-dev
      -> coverset-api-dev
          -> Cloud SQL / GCS
          -> coverset-worker-dev or synchronous dev execution
```

Private Cloud Run means access requires Google identity/IAM unless explicitly opened later.

## Build/deploy path

```text
scripts/deploy_dev.sh
  -> terraform init/validate/apply with placeholder images if needed
  -> gcloud builds submit using cloudbuild.yaml
  -> pushes images to Artifact Registry
  -> terraform apply with built image URIs
  -> smoke checks deployed endpoints
```

## Secrets

Secret values must not be stored in Terraform state. `scripts/bootstrap_gcp_secrets.sh` reads local `.env` and writes versions into Secret Manager via `gcloud secrets versions add` without printing values.

Expected local `.env` keys:

```text
GEMINI_API_KEY=...
GOOGLE_API_KEY=...
PARALLEL_API_KEY=...
```

Terraform references the Secret Manager secret names and grants Cloud Run service accounts access.

## Terraform state

Terraform state is stored in a GCS backend. Bootstrap or repair the local backend
configuration with:

```sh
scripts/bootstrap_terraform_state.sh
```

By default this creates/uses `gs://coverset-spoonepa-terraform-state` with the prefix
`coverset/dev`, enables bucket versioning, and writes the gitignored
`infra/terraform/backend.auto.hcl`. The deploy script runs the same bootstrap in
`--no-init` mode before Terraform commands, so normal deploys continue to use remote
state.

## Database connectivity

Cloud Run connects to Cloud SQL through the Cloud SQL Unix socket mount. Application config builds the SQLAlchemy URL from:

- `COVERSET_DB_USER`,
- `COVERSET_DB_PASSWORD`,
- `COVERSET_DB_NAME`,
- `COVERSET_CLOUDSQL_INSTANCE`.

Local development may use SQLite with `COVERSET_DATABASE_URL=sqlite:///...`.

## Rollback

Each deploy tags images with the current git SHA. A rollback is either:

1. apply Terraform with a previous image URI, or
2. use Cloud Run revision rollback in the console/CLI.

Database migrations must be forward-compatible during MVP deploys.

## Audit and exports

Cloud SQL is the transactional source of truth. The API exposes board exports as text,
CSV, and JSON, plus audit exports as CSV/JSON. The `audit_events` BigQuery table is an
append-only analytics sink populated from explicit export calls; BigQuery is never read
for interactive product state.

## Operations controls

P4 dev hardening provisions:

- Cloud SQL automated backups at 03:00 UTC with point-in-time recovery and seven retained backups,
- a log-based Cloud Monitoring metric for API/worker/web Cloud Run error logs,
- a Cloud Monitoring alert policy over that metric,
- a monthly budget alert when the deploy script can detect or is given a billing account,
- lifecycle rules on screenplay and artifact buckets.

## Cost posture

Dev resources use low-cost settings where practical:

- Cloud Run min instances 0,
- small Cloud SQL tier,
- lifecycle rules on GCS objects,
- one regional Artifact Registry repository,
- BigQuery audit table only, no scheduled queries.
