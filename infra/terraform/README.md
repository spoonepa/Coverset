# Coverset dev Terraform

Dev target:

- project: `spoonepa`
- region: `us-central1`
- private Cloud Run services
- Cloud SQL Postgres system of record
- GCS screenplay/artifact storage
- Secret Manager placeholders
- BigQuery analytics dataset
- Artifact Registry for Cloud Build images

Run through `scripts/deploy_dev.sh`; do not hand-edit generated `*.tfvars` files.

```sh
scripts/deploy_dev.sh
```

To call a private API endpoint:

```sh
API_URL=$(terraform -chdir=infra/terraform output -raw api_url)
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$API_URL/readyz"
```

Real Gemini/Parallel keys should be added to Secret Manager after rotating leaked keys. Do not commit `.env` or `*.tfvars` files.
